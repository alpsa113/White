from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import torch

from .schemas import DEFAULT_COND_VEC, LetterboxMeta, PreprocessResult


IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
PADDING_VALUE = 114


def load_rgb_image(path: str | Path) -> np.ndarray:
    """RGB 이미지를 HWC RGB 배열로 로드."""
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"RGB 이미지를 읽지 못했습니다: {path}")
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def load_thermal_image(path: str | Path) -> np.ndarray:
    """열화상 이미지를 2D grayscale 배열로 로드."""
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise FileNotFoundError(f"열화상 이미지를 읽지 못했습니다: {path}")
    return image


def letterbox_image(
    image: np.ndarray,
    input_size: int,
    fill_value: int | tuple[int, int, int] = PADDING_VALUE,
) -> tuple[np.ndarray, LetterboxMeta]:
    """원본 비율을 유지한 채 정사각 입력 크기로 resize + padding."""
    orig_h, orig_w = image.shape[:2]
    if orig_h <= 0 or orig_w <= 0:
        raise ValueError(f"이미지 크기가 올바르지 않습니다: {(orig_w, orig_h)}")

    scale = min(input_size / orig_w, input_size / orig_h)
    new_w = max(1, round(orig_w * scale))
    new_h = max(1, round(orig_h * scale))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    if image.ndim == 2:
        canvas = np.full((input_size, input_size), fill_value, dtype=image.dtype)
    else:
        canvas = np.full((input_size, input_size, image.shape[2]), fill_value, dtype=image.dtype)

    pad_x = (input_size - new_w) // 2
    pad_y = (input_size - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    meta = LetterboxMeta(
        orig_w=orig_w,
        orig_h=orig_h,
        input_size=input_size,
        scale=scale,
        pad_x=float(pad_x),
        pad_y=float(pad_y),
    )
    return canvas, meta


def normalize_rgb(image: np.ndarray) -> torch.Tensor:
    """학습 transform과 같은 ImageNet normalize를 적용하고 CHW tensor로 변환."""
    arr = image.astype(np.float32) / 255.0
    arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
    return torch.from_numpy(arr.transpose(2, 0, 1)).float()


def normalize_thermal(image: np.ndarray) -> torch.Tensor:
    """열화상 입력을 학습 경로와 맞춰 1채널 normalize tensor로 변환."""
    arr = image.astype(np.float32) / 255.0
    arr = (arr - float(IMAGENET_MEAN[0])) / float(IMAGENET_STD[0])
    return torch.from_numpy(arr[None]).float()


def normalize_cond_vec(cond_vec: list[float] | tuple[float, ...] | None) -> torch.Tensor:
    vals = list(cond_vec if cond_vec is not None else DEFAULT_COND_VEC)
    if len(vals) < 3:
        vals = DEFAULT_COND_VEC
    weather, temp_c, illuminance = vals[:3]
    normalized = [
        max(0.0, min(1.0, float(weather))),
        max(0.0, min(1.0, float(temp_c))),
        0.0 if float(illuminance) <= 0.0 else 1.0,
    ]
    return torch.tensor(normalized, dtype=torch.float32).unsqueeze(0)


def preprocess_inputs(
    rgb_image: np.ndarray | None = None,
    thermal_image: np.ndarray | None = None,
    cond_vec: list[float] | tuple[float, ...] | None = None,
    input_size: int = 640,
    device: torch.device | str = "cpu",
) -> PreprocessResult:
    """RGB/TIR 입력을 모델 입력 tensor로 변환."""
    if rgb_image is None and thermal_image is None:
        raise ValueError("RGB 또는 열화상 이미지 중 하나는 필요합니다.")

    reference = rgb_image if rgb_image is not None else thermal_image
    _, meta = letterbox_image(reference, input_size)

    rgb_tensor = None
    if rgb_image is not None:
        rgb_lb, _ = letterbox_image(rgb_image, input_size)
        rgb_tensor = normalize_rgb(rgb_lb).unsqueeze(0).to(device)

    thermal_tensor = None
    if thermal_image is not None:
        thermal_lb, _ = letterbox_image(thermal_image, input_size)
        thermal_tensor = normalize_thermal(thermal_lb).unsqueeze(0).to(device)

    if rgb_tensor is not None and thermal_tensor is not None:
        input_modality = "pair"
    elif rgb_tensor is not None:
        input_modality = "rgb"
    else:
        input_modality = "thermal"

    return PreprocessResult(
        rgb=rgb_tensor,
        thermal=thermal_tensor,
        cond_vec=normalize_cond_vec(cond_vec).to(device),
        meta=meta,
        input_modality=input_modality,
    )
