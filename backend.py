"""
FastAPI 백엔드 — 모델 추론 담당

역할: 프론트엔드에서 전송한 이미지 프레임을 받아 YOLO 모델로 분석하고 탐지 결과(JSON)를 반환합니다.
특징: 상태를 저장하지 않는(Stateless) 구조입니다. DB 연동/로그 저장은 프론트엔드가 담당하며, 이 서버는 '추론'만 책임집니다.
신뢰도 임계값(conf_thresh)은 이 파일 한 곳에서만 정의됩니다. 프론트엔드와 DB는 이 값을 직접 들고 있지 않고,
매 추론마다 이 서버의 응답(conf_thresh_used)을 통해서만 전달받습니다.

실행 방법:
    uvicorn backend:app --reload --port 8000
"""
import io
import os
import time
import threading
from urllib.parse import unquote

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

import cv2
from services.detection import draw_boxes

app = FastAPI(title="탐지 추론 API")

# 다른 도메인(Streamlit 프론트엔드 등)에서 호출할 수 있도록 CORS를 전체 허용합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------------ #
# 시스템 환경 변수 및 모델 초기화
# ------------------------------------------------------------------ #
# 신뢰도 임계값의 단일 출처
# 코드 수정 없이 운영값을 바꾸고 싶다면 환경변수 CONF_THRESHOLD, NMS_THRESHOLD 지정하면 됩니다.
MODEL_PATH = os.getenv("MODEL_PATH", "weights/best.pt")
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.7"))
NMS_THRESHOLD = float(os.getenv("NMS_THRESHOLD", "0.7"))

model = None
model_lock = threading.Lock()  # 여러 스레드가 동시에 model()을 호출하지 못하도록 보호

@app.on_event("startup")
def load_model():
    """서버 구동 시 최초 1회만 모델을 메모리에 적재하여 응답 속도를 높입니다."""
    global model
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(
            f"가중치 파일을 찾을 수 없습니다: {MODEL_PATH}\n"
            f"환경변수로 지정하거나 경로를 확인하세요. (예: MODEL_PATH=/경로/best.pt)"
        )
    from ultralytics import YOLO
    model = YOLO(MODEL_PATH)
    print(f"모델 로드 완료: {MODEL_PATH}")


# ------------------------------------------------------------------ #
# 핵심 라우터: 추론 API
# ------------------------------------------------------------------ #
@app.post("/detect")
async def detect(image: UploadFile = File(...)):
    """
    이미지 1장을 받아 탐지 결과를 반환합니다.
    latency_ms(추론 소요 시간)와 conf_thresh_used(실제 적용된 임계값)를 함께 반환
    """
    data = await image.read()
    pil_img = Image.open(io.BytesIO(data)).convert("RGB")

    start_time = time.perf_counter()
    with model_lock:
        results = model(pil_img, conf=CONF_THRESHOLD, iou=NMS_THRESHOLD, verbose=False)[0]
    latency_ms = round((time.perf_counter() - start_time) * 1000, 3)

    detections = []
    for box in results.boxes:
        cls_id = int(box.cls[0])
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]

        detections.append({
            "class_id": cls_id,
            "class_name": model.names[cls_id],
            "confidence": round(float(box.conf[0]), 4),
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })

    return {
        "image_width": pil_img.width,
        "image_height": pil_img.height,
        "latency_ms": latency_ms,
        "conf_thresh_used": CONF_THRESHOLD,
        "nms_thresh_used": NMS_THRESHOLD,
        "detections": detections,
    }


@app.get("/health")
def health():
    """서버가 정상적으로 작동 중인지 확인하는 상태 체크 엔드포인트입니다."""
    return {"status": "ok", "model_loaded": model is not None}

# ------------------------------------------------------------------ #
# 화면 표시 전용 실시간 스트리밍 (탐지 결과를 로그/알람으로 연결하는 작업은
# 여전히 Streamlit 쪽(services/playback.py)이 독립적으로 수행합니다 — 이
# 엔드포인트는 오직 "부드러운 화면 표시"만을 위한 것입니다.)
# ------------------------------------------------------------------ #
@app.get("/stream")
def stream(path: str, fps: float = 30.0, detect_every: float = 0.3):
    """업로드된 영상 파일 경로를 받아, 실시간 속도로 프레임을 읽고 박스를
    그려 MJPEG(multipart) 스트림으로 계속 전송합니다. 브라우저의 <img> 태그가
    이 주소를 가리키기만 하면, Streamlit의 rerun 주기와 무관하게 자체적으로
    프레임을 이어받아 표시하므로 훨씬 매끄럽습니다."""
    video_path = unquote(path)

    def _generate():
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return
        video_fps = cap.get(cv2.CAP_PROP_FPS) or fps
        frame_interval = 1.0 / video_fps

        state = {"dets": [], "busy": False}
        last_detect_time = 0.0

        def _detect_async(pil_img):
            """추론을 별도 스레드에서 수행 — 프레임 전송 루프는 이 결과를
            기다리지 않고 계속 진행되므로, 추론이 아무리 오래 걸려도
            프레임 전송 자체는 끊기지 않습니다."""
            try:
                with model_lock:
                    results = model(pil_img, conf=CONF_THRESHOLD, iou=NMS_THRESHOLD, verbose=False)[0]
                state["dets"] = [
                    {
                        "class_name": model.names[int(box.cls[0])],
                        "confidence": round(float(box.conf[0]), 4),
                        "box": {
                            "x1": float(box.xyxy[0][0]), "y1": float(box.xyxy[0][1]),
                            "x2": float(box.xyxy[0][2]), "y2": float(box.xyxy[0][3]),
                        },
                    }
                    for box in results.boxes
                ]
            except Exception as e:
                print(f"[stream] 추론 실패: {e}")  # 콘솔에서 바로 확인 가능하도록                
            finally:
                state["busy"] = False

        try:
            while True:
                start = time.perf_counter()
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # 끝까지 재생되면 처음으로 되돌아가 반복
                    continue

                pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                now = time.perf_counter()
                if now - last_detect_time >= detect_every and not state["busy"]:
                    last_detect_time = now
                    state["busy"] = True
                    threading.Thread(target=_detect_async, args=(pil_img.copy(),), daemon=True).start()

                annotated = draw_boxes(pil_img, state["dets"])
                buf = io.BytesIO()
                annotated.save(buf, format="JPEG", quality=80)

                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buf.getvalue() + b"\r\n")

                elapsed = time.perf_counter() - start
                time.sleep(max(0.0, frame_interval - elapsed))
        finally:
            cap.release()

    return StreamingResponse(_generate(), media_type="multipart/x-mixed-replace; boundary=frame")