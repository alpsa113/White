"""backend.py — FastAPI 추론 서버. 프레임을 받아 YOLO로 분석하고 탐지 결과(JSON)를 반환합니다(Stateless).

실행: uvicorn backend:app --reload --port 8000
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_PATH = os.getenv("MODEL_PATH", "weights/best.pt")
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.7"))
NMS_THRESHOLD = float(os.getenv("NMS_THRESHOLD", "0.7"))

model = None
model_lock = threading.Lock()


@app.on_event("startup")
def load_model():
    """서버 구동 시 모델을 1회 로드합니다."""
    global model
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(
            f"가중치 파일을 찾을 수 없습니다: {MODEL_PATH}\n"
            f"환경변수로 지정하거나 경로를 확인하세요. (예: MODEL_PATH=/경로/best.pt)"
        )
    from ultralytics import YOLO
    model = YOLO(MODEL_PATH)
    print(f"모델 로드 완료: {MODEL_PATH}")


@app.post("/detect")
async def detect(image: UploadFile = File(...)):
    """이미지 1장을 받아 탐지 결과와 latency_ms/conf_thresh_used를 반환합니다."""
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
    """서버 상태 체크 엔드포인트입니다."""
    return {"status": "ok", "model_loaded": model is not None}


@app.get("/stream")
def stream(path: str, fps: float = 30.0, detect_every: float = 0.3):
    """영상 파일을 실시간 속도로 읽어 박스를 그려 MJPEG 스트림으로 전송합니다."""
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
            """추론을 별도 스레드에서 수행해 프레임 전송이 끊기지 않게 합니다."""
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
                print(f"[stream] 추론 실패: {e}")
            finally:
                state["busy"] = False

        try:
            while True:
                start = time.perf_counter()
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
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
