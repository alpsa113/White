from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import torch
import yaml

from model import DualYOLO

from .postprocessing import postprocess_output
from .preprocessing import load_rgb_image, load_thermal_image, preprocess_inputs
from .schemas import PredictionResult


class DualYOLOPredictor:
    """DualYOLO checkpoint 기반 추론 래퍼."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        model_cfg_path: str | Path = "configs/model.yaml",
        device: str | None = None,
        conf_thresh: float = 0.25,
        nms_thresh: float = 0.6,
        max_detections: int = 300,
    ):
        self.checkpoint_path = Path(checkpoint_path)
        self.model_cfg_path = Path(model_cfg_path)
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.conf_thresh = conf_thresh
        self.nms_thresh = nms_thresh
        self.max_detections = max_detections

        self.model_cfg = self._load_yaml(self.model_cfg_path)
        self.input_size = int(self.model_cfg.get("training", {}).get("img_size", 640))
        self.model = self._build_model()
        self._load_checkpoint(self.checkpoint_path)
        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def _load_yaml(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _build_model(self) -> DualYOLO:
        model_cfg = self.model_cfg["model"]
        model = DualYOLO(
            fusion_dim=model_cfg.get("fusion_dim", 256),
            fpn_dim=model_cfg.get("fpn_dim", 256),
            cond_dim=model_cfg.get("cond_dim", 3),
            backbone_cfg=model_cfg.get("backbone", {}),
        )
        model.set_aux_active(False)
        model.set_uncertainty_active(False)
        return model

    def _load_checkpoint(self, checkpoint_path: Path):
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"추론 checkpoint를 찾지 못했습니다: {checkpoint_path}")

        checkpoint = torch.load(
            checkpoint_path,
            map_location=self.device,
            weights_only=False,
        )
        state_dict = self._extract_state_dict(checkpoint)
        self.model.load_state_dict(state_dict)

    @staticmethod
    def _looks_like_state_dict(value) -> bool:
        return isinstance(value, dict) and value and all(
            isinstance(k, str) and torch.is_tensor(v)
            for k, v in value.items()
        )

    @staticmethod
    def _strip_module_prefix(state_dict: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        if not any(key.startswith("module.") for key in state_dict):
            return state_dict
        return {
            key.removeprefix("module."): value
            for key, value in state_dict.items()
        }

    @classmethod
    def _extract_state_dict(cls, checkpoint) -> dict[str, torch.Tensor]:
        """여러 저장 포맷에서 DualYOLO state_dict를 추출."""
        if cls._looks_like_state_dict(checkpoint):
            return cls._strip_module_prefix(checkpoint)

        if not isinstance(checkpoint, dict):
            raise ValueError(
                "checkpoint 형식을 해석하지 못했습니다. "
                "DualYOLO state_dict 또는 Trainer checkpoint를 사용해야 합니다."
            )

        for key in ("model", "model_state_dict", "state_dict"):
            value = checkpoint.get(key)
            if cls._looks_like_state_dict(value):
                return cls._strip_module_prefix(value)

        if "ema" in checkpoint or "train_args" in checkpoint:
            raise ValueError(
                "Ultralytics checkpoint로 보입니다. "
                "추론에는 weights/yolo26m-coco.pt가 아니라 "
                "DualYOLO 학습 결과 checkpoint(checkpoints/phase*/best.pt)를 사용해야 합니다."
            )

        raise ValueError(
            "checkpoint에서 DualYOLO state_dict를 찾지 못했습니다. "
            "지원 형식: raw state_dict, {'model': ...}, "
            "{'model_state_dict': ...}, {'state_dict': ...}."
        )

    @torch.no_grad()
    def predict(
        self,
        rgb_path: str | Path | None = None,
        thermal_path: str | Path | None = None,
        rgb_image: np.ndarray | None = None,
        thermal_image: np.ndarray | None = None,
        cond_vec: list[float] | tuple[float, ...] | None = None,
    ) -> PredictionResult:
        """파일 경로 또는 ndarray 입력으로 단일 이미지 추론을 수행."""
        if rgb_image is None and rgb_path is not None:
            rgb_image = load_rgb_image(rgb_path)
        if thermal_image is None and thermal_path is not None:
            thermal_image = load_thermal_image(thermal_path)

        pre = preprocess_inputs(
            rgb_image=rgb_image,
            thermal_image=thermal_image,
            cond_vec=cond_vec,
            input_size=self.input_size,
            device=self.device,
        )

        start = time.perf_counter()
        model_out = self.model(pre.rgb, pre.thermal, pre.cond_vec)
        detections = postprocess_output(
            model_out,
            meta=pre.meta,
            conf_thresh=self.conf_thresh,
            nms_thresh=self.nms_thresh,
            max_detections=self.max_detections,
        )
        latency_ms = (time.perf_counter() - start) * 1000.0

        return PredictionResult(
            detections=detections,
            latency_ms=round(latency_ms, 2),
            input_modality=pre.input_modality,
            image_width=pre.meta.orig_w,
            image_height=pre.meta.orig_h,
        )
