from __future__ import annotations

import torch

from training.metrics import decode_detections

from .schemas import CLASS_NAMES, Detection, LetterboxMeta


def restore_boxes_to_original(
    boxes: torch.Tensor,
    meta: LetterboxMeta,
) -> torch.Tensor:
    """letterbox 입력 좌표의 bbox를 원본 이미지 좌표로 복원."""
    if boxes.numel() == 0:
        return boxes.new_zeros((0, 4))

    restored = boxes.clone()
    restored[:, [0, 2]] = (restored[:, [0, 2]] - meta.pad_x) / meta.scale
    restored[:, [1, 3]] = (restored[:, [1, 3]] - meta.pad_y) / meta.scale
    restored[:, [0, 2]] = restored[:, [0, 2]].clamp(0, meta.orig_w)
    restored[:, [1, 3]] = restored[:, [1, 3]].clamp(0, meta.orig_h)
    return restored


def postprocess_output(
    model_out: dict,
    meta: LetterboxMeta,
    conf_thresh: float = 0.50,
    nms_thresh: float = 0.4,
    max_detections: int = 300,
    class_names: list[str] | None = None,
) -> list[Detection]:
    """모델 raw output을 API/대시보드용 Detection 목록으로 변환."""
    names = class_names or CLASS_NAMES
    decoded = decode_detections(
        model_out,
        conf_thresh=conf_thresh,
        nms_thresh=nms_thresh,
        max_detections=max_detections,
    )
    if not decoded:
        return []

    pred = decoded[0]
    boxes = restore_boxes_to_original(pred["boxes"].detach().cpu(), meta)
    scores = pred["scores"].detach().cpu()
    labels = pred["labels"].detach().cpu()

    detections: list[Detection] = []
    for box, score, label in zip(boxes, scores, labels):
        class_id = int(label.item())
        class_name = names[class_id] if 0 <= class_id < len(names) else str(class_id)
        detections.append(
            Detection(
                class_id=class_id,
                class_name=class_name,
                score=float(score.item()),
                bbox=[round(float(v), 2) for v in box.tolist()],
            )
        )
    return detections
