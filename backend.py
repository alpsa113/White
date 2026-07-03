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

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

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
