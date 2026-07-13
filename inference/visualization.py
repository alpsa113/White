from __future__ import annotations

import cv2
import numpy as np


COLORS = {
    "person": (0, 0, 255),
    "boar": (0, 165, 255),
    "deer": (0, 255, 255),
    "non_target": (180, 180, 180),
}


def draw_detections_rgb(image: np.ndarray, detections: list[dict]) -> np.ndarray:
    """RGB 이미지에 bbox를 그리고 OpenCV 저장용 BGR 이미지를 반환."""
    canvas = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    for det in detections:
        x1, y1, x2, y2 = [int(round(v)) for v in det["bbox"]]
        class_name = det["class_name"]
        score = det["score"]
        color = COLORS.get(class_name, (255, 255, 255))
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        track_id = det.get("track_id")
        label = (
            f"{class_name} #{track_id} {score:.2f}"
            if track_id is not None
            else f"{class_name} {score:.2f}"
        )
        cv2.putText(
            canvas,
            label,
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )
    return canvas
