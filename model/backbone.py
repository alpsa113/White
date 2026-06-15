"""
Dual Backbone: YOLO26-M pretrained truncated feature extractors.

Both RGB and thermal branches execute only up to stride 16 (C4). Neck and
detection heads are not called in the training forward path.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sys
from typing import Any

import torch
import torch.nn as nn


class YOLO26Backbone(nn.Module):
    """YOLO26-M detection checkpoint wrapper truncated at C4."""

    def __init__(
        self,
        yolo_model: nn.Module,
        c3_layer: int | str = "auto",
        c4_layer: int | str = "auto",
        input_size: int = 640,
        input_channels: int = 3,
        expected_c3_channels: int = 256,
        expected_c4_channels: int = 512,
        strict_shapes: bool = True,
    ):
        super().__init__()
        layers = _extract_layer_list(yolo_model)
        self.layers = layers
        self.c3_layer = c3_layer
        self.c4_layer = c4_layer
        self.input_channels = input_channels
        self.out_channels: dict[str, int] = {}

        if self.c3_layer == "auto" or self.c4_layer == "auto":
            found = self._infer_feature_layers(input_size)
            if self.c3_layer == "auto":
                self.c3_layer = found["c3_layer"]
            if self.c4_layer == "auto":
                self.c4_layer = found["c4_layer"]
            self.out_channels = {
                "c3": found["c3_channels"],
                "c4": found["c4_channels"],
            }
        else:
            self.c3_layer = int(self.c3_layer)
            self.c4_layer = int(self.c4_layer)
            self.out_channels = self._infer_channels_from_layers(input_size)

        if int(self.c3_layer) >= int(self.c4_layer):
            raise ValueError(
                f"Invalid YOLO26 C3/C4 layer order: c3={self.c3_layer}, "
                f"c4={self.c4_layer}"
            )

        if strict_shapes:
            expected = {
                "c3": expected_c3_channels,
                "c4": expected_c4_channels,
            }
            for key, channels in expected.items():
                if self.out_channels[key] != channels:
                    raise ValueError(
                        f"YOLO26 {key.upper()} channels mismatch: "
                        f"expected {channels}, got {self.out_channels[key]}. "
                        "Set the correct checkpoint/layer indices or disable "
                        "strict_shapes only after updating downstream modules."
                    )

        self.layers = nn.ModuleList(
            list(self.layers.children())[: int(self.c4_layer) + 1]
        )

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        y: list[Any] = []
        c3 = None
        c4 = None

        for idx, layer in enumerate(self.layers):
            layer_input = _resolve_layer_input(layer, x, y)
            x = layer(layer_input)
            y.append(x)

            if idx == int(self.c3_layer):
                c3 = _select_tensor(x)
            if idx == int(self.c4_layer):
                c4 = _select_tensor(x)
                break

        if c3 is None or c4 is None:
            raise RuntimeError(
                f"Failed to extract YOLO26 C3/C4 features "
                f"(c3_layer={self.c3_layer}, c4_layer={self.c4_layer})."
            )
        return {"c3": c3, "c4": c4}

    @torch.no_grad()
    def _infer_feature_layers(self, input_size: int) -> dict[str, int]:
        training = self.training
        self.eval()
        device = next(self.parameters(), torch.empty(0)).device
        x = torch.zeros(1, self.input_channels, input_size, input_size, device=device)
        y: list[Any] = []
        found: dict[str, int] = {}
        c3_candidate: dict[str, int] | None = None
        c4_candidate: dict[str, int] | None = None

        for idx, layer in enumerate(self.layers):
            layer_input = _resolve_layer_input(layer, x, y)
            x = layer(layer_input)
            y.append(x)
            tensor = _select_tensor(x, required=False)
            if tensor is None or tensor.ndim != 4:
                continue

            stride = input_size // int(tensor.shape[-1])
            if stride == 8:
                c3_candidate = {
                    "c3_layer": idx,
                    "c3_channels": int(tensor.shape[1]),
                }
            elif stride == 16:
                if c3_candidate is not None:
                    found.update(c3_candidate)
                c4_candidate = {
                    "c4_layer": idx,
                    "c4_channels": int(tensor.shape[1]),
                }
            elif stride > 16 and c4_candidate is not None:
                found.update(c4_candidate)
                break

        self.train(training)
        if c4_candidate is not None and "c4_layer" not in found:
            found.update(c4_candidate)
        missing = [key for key in ("c3_layer", "c4_layer") if key not in found]
        if missing:
            raise ValueError(
                f"Could not infer YOLO26 feature layers from checkpoint: {missing}. "
                "Set c3_layer/c4_layer explicitly in configs/model.yaml."
            )
        return found

    @torch.no_grad()
    def _infer_channels_from_layers(self, input_size: int) -> dict[str, int]:
        training = self.training
        self.eval()
        device = next(self.parameters(), torch.empty(0)).device
        x = torch.zeros(1, self.input_channels, input_size, input_size, device=device)
        y: list[Any] = []
        out_channels: dict[str, int] = {}

        for idx, layer in enumerate(self.layers):
            layer_input = _resolve_layer_input(layer, x, y)
            x = layer(layer_input)
            y.append(x)
            if idx == int(self.c3_layer):
                out_channels["c3"] = int(_select_tensor(x).shape[1])
            if idx == int(self.c4_layer):
                out_channels["c4"] = int(_select_tensor(x).shape[1])
                break

        self.train(training)
        if set(out_channels) != {"c3", "c4"}:
            raise ValueError("Could not infer channels for configured C3/C4 layers.")
        return out_channels


class DualBackbone(nn.Module):
    """RGB + thermal YOLO26-M/M truncated pretrained backbones."""

    def __init__(self, backbone_cfg: dict | None = None):
        super().__init__()
        cfg = backbone_cfg or {}
        provider = cfg.get("provider", "local_checkpoint")
        if provider != "local_checkpoint":
            raise ValueError(f"Unsupported YOLO26 backbone provider: {provider}")

        rgb_pretrained = bool(cfg.get("rgb_pretrained", True))
        thm_pretrained = bool(cfg.get("thm_pretrained", True))
        if not rgb_pretrained or not thm_pretrained:
            raise ValueError(
                "YOLO26-M COCO pretrained mode requires both rgb_pretrained and "
                "thm_pretrained to be true."
            )

        provider_code = cfg.get("provider_code")
        if provider_code:
            _add_provider_code_to_path(provider_code)

        weights = cfg.get("weights")
        if not weights:
            raise ValueError("configs/model.yaml must set model.backbone.weights.")

        rgb_model = _load_yolo26_model(weights)
        thm_model = copy.deepcopy(rgb_model)
        _inflate_first_conv_to_one_channel(thm_model)

        wrapper_kwargs = {
            "c3_layer": cfg.get("c3_layer", "auto"),
            "c4_layer": cfg.get("c4_layer", "auto"),
            "input_size": int(cfg.get("input_size", 640)),
            "expected_c3_channels": int(cfg.get("expected_c3_channels", 256)),
            "expected_c4_channels": int(cfg.get("expected_c4_channels", 512)),
            "strict_shapes": bool(cfg.get("strict_shapes", True)),
        }
        self.rgb = YOLO26Backbone(rgb_model, input_channels=3, **wrapper_kwargs)
        self.thm = YOLO26Backbone(thm_model, input_channels=1, **wrapper_kwargs)

    def forward(
        self,
        rgb: torch.Tensor | None,
        thermal: torch.Tensor | None,
    ) -> tuple[dict | None, dict | None]:
        rgb_feats = self.rgb(rgb) if rgb is not None else None
        thm_feats = self.thm(thermal) if thermal is not None else None
        return rgb_feats, thm_feats


def _load_yolo26_model(weights: str | Path) -> nn.Module:
    path = Path(weights).expanduser()
    if not path.exists():
        raise FileNotFoundError(
            f"YOLO26-M COCO pretrained checkpoint not found: {path}. "
            "Mount Google Drive in Colab or update model.backbone.weights."
        )

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(checkpoint, nn.Module):
        return checkpoint.float()

    if isinstance(checkpoint, dict):
        for key in ("ema", "model"):
            model = checkpoint.get(key)
            if isinstance(model, nn.Module):
                return model.float()
        raise ValueError(
            "YOLO26 checkpoint must contain an nn.Module under 'ema' or 'model'. "
            "State-dict-only checkpoints require the matching YOLO26 model code "
            "and are not supported by the local_checkpoint provider."
        )

    raise ValueError(f"Unsupported YOLO26 checkpoint type: {type(checkpoint)!r}")


def _add_provider_code_to_path(provider_code: str | Path):
    path = Path(provider_code).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.exists():
        raise FileNotFoundError(
            f"YOLO26 provider_code path not found: {path}. "
            "Set model.backbone.provider_code to the directory containing the "
            "YOLO26 provider package."
        )
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _extract_layer_list(model: nn.Module) -> nn.ModuleList | nn.Sequential:
    candidate = model
    for _ in range(4):
        layers = getattr(candidate, "model", None)
        if isinstance(layers, (nn.ModuleList, nn.Sequential)):
            return layers
        if isinstance(layers, nn.Module):
            candidate = layers
            continue
        break
    raise ValueError(
        "YOLO26 model must expose its layer graph as model.model "
        "(ModuleList or Sequential)."
    )


def _resolve_layer_input(layer: nn.Module, x: Any, outputs: list[Any]) -> Any:
    from_idx = getattr(layer, "f", -1)
    if from_idx == -1:
        return x
    if isinstance(from_idx, int):
        return outputs[from_idx]
    if isinstance(from_idx, (list, tuple)):
        return [x if j == -1 else outputs[j] for j in from_idx]
    return x


def _select_tensor(value: Any, required: bool = True) -> torch.Tensor | None:
    if isinstance(value, torch.Tensor):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            tensor = _select_tensor(item, required=False)
            if tensor is not None:
                return tensor
    if isinstance(value, dict):
        for item in value.values():
            tensor = _select_tensor(item, required=False)
            if tensor is not None:
                return tensor
    if required:
        raise TypeError(f"Expected tensor-like layer output, got {type(value)!r}")
    return None


def _inflate_first_conv_to_one_channel(model: nn.Module):
    parent, name, conv = _find_first_conv_parent(model)
    new_conv = nn.Conv2d(
        in_channels=1,
        out_channels=conv.out_channels,
        kernel_size=conv.kernel_size,
        stride=conv.stride,
        padding=conv.padding,
        dilation=conv.dilation,
        groups=conv.groups,
        bias=conv.bias is not None,
        padding_mode=conv.padding_mode,
    )
    with torch.no_grad():
        new_conv.weight.copy_(conv.weight.mean(dim=1, keepdim=True))
        if conv.bias is not None:
            new_conv.bias.copy_(conv.bias)
    setattr(parent, name, new_conv)


def _find_first_conv_parent(module: nn.Module) -> tuple[nn.Module, str, nn.Conv2d]:
    for name, child in module.named_children():
        if isinstance(child, nn.Conv2d):
            if child.in_channels != 3:
                raise ValueError(
                    f"Expected first YOLO26 conv to have 3 input channels, "
                    f"got {child.in_channels}."
                )
            return module, name, child
        try:
            return _find_first_conv_parent(child)
        except LookupError:
            continue
    raise LookupError("Could not find first Conv2d in YOLO26 checkpoint model.")
