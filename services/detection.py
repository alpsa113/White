"""services/detection.py — 탐지 추론 호출 및 시각화(바운딩 박스 오버레이) 로직."""
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
    """클래스명이 '사람' 카테고리에 속하는지 판별합니다(대소문자 무관)."""
    return class_name.strip().lower() in {c.lower() for c in PERSON_CLASSES}


def draw_boxes(image: Image.Image, detections: list[dict]) -> Image.Image:
    """이미지 복사본에 바운딩 박스와 클래스명/신뢰도 라벨을 그려 반환합니다."""
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


def simulate_detections(width: int, height: int) -> list[dict]:
    """데모 모드용 무작위 탐지 결과를 생성합니다('사람 등장 비율' 설정에 따름)."""
    animal_pool = ["고라니", "멧돼지", "소형동물"]
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
    """프레임을 백엔드 API로 분석하거나(비데모), 데모 모드면 시뮬레이션 결과를 반환합니다."""
    if st.session_state.get("simulate", True):
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
