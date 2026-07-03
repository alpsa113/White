"""
services/detection.py — 탐지 추론 호출 및 시각화 로직

백엔드 API 호출(run_detection), 데모용 무작위 탐지 생성(simulate_detections),
바운딩 박스 오버레이(draw_boxes), 사람 클래스 판별(is_person)을 담당합니다.
Streamlit 렌더링(st.markdown 등)은 포함하지 않으며, 다른 서비스/페이지 모듈에서 호출됩니다.
"""
import io
import random

import requests
import streamlit as st
from PIL import Image, ImageDraw

from config import (
    API_URL, COLORS, DEFAULT_COLOR, PERSON_CLASSES,
    FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH,
)


def is_person(class_name: str) -> bool:
    """해당 클래스명이 보안상 가장 중요한 '사람' 카테고리에 속하는지 판별합니다."""
    return class_name.strip().lower() in {c.lower() for c in PERSON_CLASSES}


def draw_boxes(image: Image.Image, detections: list[dict]) -> Image.Image:
    """원본 이미지 프레임 위에 바운딩 박스와 클래스명, 신뢰도를 오버레이로 그려 반환합니다."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for det in detections:
        b = det["box"]
        color = COLORS.get(det["class_name"], DEFAULT_COLOR)
        draw.rectangle([b["x1"], b["y1"], b["x2"], b["y2"]], outline=color, width=3)
        label = f'{det["class_name"]} {det["confidence"]:.0%}'
        draw.rectangle([b["x1"], b["y1"] - 16, b["x1"] + len(label) * 9, b["y1"]], fill=color)
        draw.text((b["x1"] + 3, b["y1"] - 15), label, fill="white")
    return out


# ==================================================================== #
# 데모 모드 전용 구역
# 나중에 데모 모드를 제거하려면:
#   1) 아래 simulate_detections() 함수 전체 삭제
#   2) run_detection() 안의 "if st.session_state.get(...)" 3줄 블록 삭제
#   그 외 다른 파일(services/alerts.py, services/video_tracking.py 등)은
#   run_detection()을 블랙박스로만 호출하므로 손댈 필요가 없습니다.
# ==================================================================== #
def simulate_detections(width: int, height: int) -> list[dict]:
    """실제 API 서버 연결 없이 데모 환경을 구성하기 위해 무작위 탐지 결과를 생성합니다."""
    animal_pool = ["고라니", "멧돼지"]
    ratio = st.session_state.get("person_ratio", 0.5)
    n = random.choices([0, 1, 2], weights=[0.25, 0.5, 0.25])[0]

    detections = []
    for _ in range(n):
        name = "사람" if random.random() < ratio else random.choice(animal_pool)
        bw = random.uniform(0.12, 0.30) * width
        bh = random.uniform(0.20, 0.45) * height
        x1 = random.uniform(0, max(1, width - bw))
        y1 = random.uniform(0, max(1, height - bh))
        detections.append({
            "class_id": 0 if name in PERSON_CLASSES else 1,
            "class_name": name,
            "confidence": round(random.uniform(0.55, 0.97), 4),
            "box": {"x1": x1, "y1": y1, "x2": x1 + bw, "y2": y1 + bh},
        })
    return detections


def run_detection(image: Image.Image) -> tuple[list[dict], float, float]:
    """
    현재 프레임을 백엔드 API에 전송하여 분석하거나, 시뮬레이션 데이터를 반환합니다.
    반환값의 두 번째/세 번째 항목(conf_thresh, nms_thresh)은 항상 backend.py가
    실제 적용한 값을 그대로 전달합니다.
    """
    if st.session_state.get("simulate", True):                            # ← 데모 모드 전용 블록 (삭제 시 이 3줄만 제거)
        return simulate_detections(image.width, image.height), FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH

    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    buf.seek(0)
    res = requests.post(API_URL, files={"image": ("frame.jpg", buf, "image/jpeg")}, timeout=30)
    res.raise_for_status()
    data = res.json()
    return (
        data["detections"],
        data.get("conf_thresh_used", FALLBACK_CONF_THRESH),
        data.get("nms_thresh_used", FALLBACK_NMS_THRESH),
    )
