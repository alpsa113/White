"""services/detection.py — 탐지 추론 호출 및 시각화(바운딩 박스 오버레이) 로직."""
from PIL import Image, ImageDraw

from services import model_runtime
from config import COLORS, DEFAULT_COLOR, PERSON_CLASSES


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


def run_detection(image: Image.Image) -> tuple[list[dict], float, float, float]:
    """프레임을 모델로 직접 분석합니다. 반환: (detections, conf_thresh, nms_thresh, latency_ms).

    과거에는 자기 프로세스의 /detect로 HTTP 루프백 호출을 했는데, 카메라가 여러 대로
    늘어나면 FastAPI 이벤트 루프 하나를 두고 서로 경합해 서버 전체가 멈추는 문제가
    있었습니다(services/model_runtime.py 참고). 이제는 스레드 락으로만 직렬화되는 모델 함수를
    직접 호출합니다."""
    return model_runtime.infer(image)
