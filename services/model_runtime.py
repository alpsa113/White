"""services/model_runtime.py — YOLO 로컬 추론. services/video_analyzer.py(사전 분석)와
/detect API가 이 모듈을 공유하며, 스레드 락(_model_lock)으로 동시 호출을 직렬화합니다."""
import os
import threading
import time

from PIL import Image

MODEL_PATH = os.getenv("MODEL_PATH", "weights/best.pt")
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.7"))
NMS_THRESHOLD = float(os.getenv("NMS_THRESHOLD", "0.7"))

_model = None
_model_lock = threading.Lock()


def load_model() -> None:
    """서버 구동 시 1회 호출합니다."""
    global _model
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(
            f"가중치 파일을 찾을 수 없습니다: {MODEL_PATH}\n"
            f"환경변수로 지정하거나 경로를 확인하세요. (예: MODEL_PATH=/경로/best.pt)"
        )
    from ultralytics import YOLO
    _model = YOLO(MODEL_PATH)
    print(f"모델 로드 완료: {MODEL_PATH}")


def is_loaded() -> bool:
    return _model is not None


def infer(pil_img: Image.Image) -> tuple[list[dict], float, float, float]:
    """이미지 1장을 추론합니다. 반환: (detections, conf_thresh_used, nms_thresh_used, latency_ms)."""
    start = time.perf_counter()
    with _model_lock:
        results = _model(pil_img, conf=CONF_THRESHOLD, iou=NMS_THRESHOLD, verbose=False)[0]
    latency_ms = round((time.perf_counter() - start) * 1000, 3)

    detections = []
    for box in results.boxes:
        cls_id = int(box.cls[0])
        x1, y1, x2, y2 = [float(v) for v in box.xyxy[0]]
        detections.append({
            "class_id": cls_id,
            "class_name": _model.names[cls_id],
            "confidence": round(float(box.conf[0]), 4),
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })
    return detections, CONF_THRESHOLD, NMS_THRESHOLD, latency_ms
