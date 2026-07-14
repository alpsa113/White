"""services/model_runtime.py — DualYOLO 로컬 추론 런타임.

services/video_analyzer.py(사전 분석)와 /detect API가 이 모듈을 공유하며,
스레드 락(_model_lock)으로 동시 호출을 직렬화합니다.
"""
import os
import threading
import time

import numpy as np
from PIL import Image

from inference import DualYOLOPredictor

MODEL_PATH = os.getenv("MODEL_PATH", "checkpoints/phase3/best.pt")
MODEL_CFG_PATH = os.getenv("MODEL_CFG_PATH", "configs/model.yaml")
DEVICE = os.getenv("DEVICE")
CONF_THRESHOLD = float(os.getenv("CONF_THRESHOLD", "0.50"))
NMS_THRESHOLD = float(os.getenv("NMS_THRESHOLD", "0.4"))

DISPLAY_CLASS_NAMES = {
    "person": "사람",
    "boar": "멧돼지",
    "deer": "고라니",
    "non_target": "소형동물",
}

_model = None
_model_lock = threading.Lock()


def load_model() -> None:
    """서버 구동 시 1회 호출합니다."""
    global _model
    if not os.path.isfile(MODEL_PATH):
        raise FileNotFoundError(
            f"DualYOLO checkpoint를 찾을 수 없습니다: {MODEL_PATH}\n"
            "환경변수 MODEL_PATH로 phase 학습 결과 checkpoint를 지정하세요. "
            "(예: MODEL_PATH=/경로/checkpoints/phase3/best.pt)"
        )
    if not os.path.isfile(MODEL_CFG_PATH):
        raise FileNotFoundError(
            f"DualYOLO model config를 찾을 수 없습니다: {MODEL_CFG_PATH}\n"
            "환경변수 MODEL_CFG_PATH로 configs/model.yaml 경로를 지정하세요."
        )
    _model = DualYOLOPredictor(
        checkpoint_path=MODEL_PATH,
        model_cfg_path=MODEL_CFG_PATH,
        device=DEVICE,
        conf_thresh=CONF_THRESHOLD,
        nms_thresh=NMS_THRESHOLD,
    )
    print(f"DualYOLO 모델 로드 완료: {MODEL_PATH}")


def is_loaded() -> bool:
    return _model is not None


def infer(pil_img: Image.Image) -> tuple[list[dict], float, float, float]:
    """이미지 1장을 추론합니다. 반환: (detections, conf_thresh_used, nms_thresh_used, latency_ms)."""
    start = time.perf_counter()
    rgb_image = np.asarray(pil_img.convert("RGB"))
    with _model_lock:
        result = _model.predict(rgb_image=rgb_image)
    latency_ms = round((time.perf_counter() - start) * 1000, 3)

    detections = []
    for det in result.detections:
        x1, y1, x2, y2 = [float(v) for v in det.bbox]
        class_name = DISPLAY_CLASS_NAMES.get(det.class_name, det.class_name)
        detections.append({
            "class_id": int(det.class_id),
            "class_name": class_name,
            "confidence": round(float(det.score), 4),
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })
    return detections, CONF_THRESHOLD, NMS_THRESHOLD, latency_ms
