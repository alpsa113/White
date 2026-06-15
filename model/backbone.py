"""
Dual Backbone: YOLO26-M 사전학습 모델을 C4까지만 자른 특징 추출기.

RGB/열화상 브랜치는 모두 stride 16(C4)까지만 실행한다.
학습 forward 경로에서는 YOLO26 neck과 detection head를 호출하지 않는다.
"""

from __future__ import annotations

import copy
from pathlib import Path
import sys
from typing import Any

import torch
import torch.nn as nn


class YOLO26Backbone(nn.Module):
    """YOLO26-M 탐지 checkpoint를 C4까지만 사용하는 래퍼."""

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
                f"YOLO26 C3/C4 레이어 순서가 올바르지 않습니다: c3={self.c3_layer}, "
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
                        f"YOLO26 {key.upper()} 채널 수가 맞지 않습니다: "
                        f"기대값 {channels}, 실제값 {self.out_channels[key]}. "
                        "올바른 체크포인트/레이어 index를 설정하거나, 후속 모듈을 "
                        "함께 수정한 뒤에만 strict_shapes를 비활성화하세요."
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
                f"YOLO26 C3/C4 특징맵 추출에 실패했습니다 "
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
                f"체크포인트에서 YOLO26 특징 레이어를 추론하지 못했습니다: {missing}. "
                "configs/model.yaml에 c3_layer/c4_layer를 명시하세요."
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
            raise ValueError("설정된 C3/C4 레이어의 채널 수를 추론하지 못했습니다.")
        return out_channels


class DualBackbone(nn.Module):
    """RGB + 열화상 YOLO26-M/M 절단 사전학습 백본."""

    def __init__(self, backbone_cfg: dict | None = None):
        super().__init__()
        cfg = backbone_cfg or {}
        provider = cfg.get("provider", "local_checkpoint")
        if provider != "local_checkpoint":
            raise ValueError(f"지원하지 않는 YOLO26 백본 제공자입니다: {provider}")

        rgb_pretrained = bool(cfg.get("rgb_pretrained", True))
        thm_pretrained = bool(cfg.get("thm_pretrained", True))
        if not rgb_pretrained or not thm_pretrained:
            raise ValueError(
                "YOLO26-M COCO 사전학습 모드는 rgb_pretrained와 "
                "thm_pretrained가 모두 true여야 합니다."
            )

        provider_code = cfg.get("provider_code")
        if provider_code:
            _add_provider_code_to_path(provider_code)

        weights = cfg.get("weights")
        if not weights:
            raise ValueError("configs/model.yaml에 model.backbone.weights를 설정해야 합니다.")

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
            f"YOLO26-M COCO 사전학습 체크포인트를 찾지 못했습니다: {path}. "
            "Colab에서는 Google Drive를 마운트하거나 model.backbone.weights를 수정하세요."
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
            "YOLO26 체크포인트는 'ema' 또는 'model' 키 아래에 nn.Module을 포함해야 합니다. "
            "state_dict만 있는 체크포인트는 매칭되는 YOLO26 모델 코드가 필요하므로 "
            "local_checkpoint 제공자에서 지원하지 않습니다."
        )

    raise ValueError(f"지원하지 않는 YOLO26 체크포인트 타입입니다: {type(checkpoint)!r}")


def _add_provider_code_to_path(provider_code: str | Path):
    path = Path(provider_code).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    if not path.exists():
        raise FileNotFoundError(
            f"YOLO26 provider_code 경로를 찾지 못했습니다: {path}. "
            "model.backbone.provider_code를 YOLO26 제공자 package가 들어 있는 "
            "디렉터리로 설정하세요."
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
        "YOLO26 모델은 레이어 graph를 model.model(ModuleList 또는 Sequential)로 "
        "노출해야 합니다."
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
        raise TypeError(f"tensor 형태의 레이어 출력을 기대했지만 {type(value)!r} 값을 받았습니다.")
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
                    f"YOLO26 첫 번째 conv의 입력 채널은 3이어야 하지만 "
                    f"실제값은 {child.in_channels}입니다."
                )
            return module, name, child
        try:
            return _find_first_conv_parent(child)
        except LookupError:
            continue
    raise LookupError("YOLO26 체크포인트 모델에서 첫 번째 Conv2d를 찾지 못했습니다.")
