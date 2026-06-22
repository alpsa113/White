from __future__ import annotations

from dataclasses import asdict, dataclass

import torch


CLASS_NAMES = ["person", "boar", "deer", "non_target"]
DEFAULT_COND_VEC = [0.0, 0.5, 1.0]


@dataclass(frozen=True)
class LetterboxMeta:
    """원본 좌표계와 모델 입력 좌표계 사이의 변환 정보."""

    orig_w: int
    orig_h: int
    input_size: int
    scale: float
    pad_x: float
    pad_y: float


@dataclass
class PreprocessResult:
    """모델 forward에 들어갈 tensor와 좌표 복원 메타데이터."""

    rgb: torch.Tensor | None
    thermal: torch.Tensor | None
    cond_vec: torch.Tensor
    meta: LetterboxMeta
    input_modality: str


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    score: float
    bbox: list[float]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PredictionResult:
    detections: list[Detection]
    latency_ms: float
    input_modality: str
    image_width: int
    image_height: int

    def to_dict(self) -> dict:
        return {
            "detections": [det.to_dict() for det in self.detections],
            "latency_ms": self.latency_ms,
            "input_modality": self.input_modality,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }
