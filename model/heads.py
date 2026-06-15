"""
탐지 헤드 모음

1. YOLODetectionHead  — anchor-free, 클래스별 분류 + bbox 회귀 + objectness
2. AuxHead            — 단일 백본 피처에서 보조 분류(1·2단계 활성)
3. UncertaintyHead    — 데이터 자체 노이즈 기반 불확실성 추정(2단계 후반~3단계 활성)

클래스: 0=person, 1=boar, 2=deer, 3=non_target
"""

import torch
import torch.nn as nn


NUM_CLASSES = 4  # person / boar / deer / non_target 네 클래스


def _conv_bn_act(in_ch: int, out_ch: int, act: bool = True) -> nn.Sequential:
    layers: list[nn.Module] = [
        nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
        nn.BatchNorm2d(out_ch),
    ]
    if act:
        layers.append(nn.SiLU(inplace=True))
    return nn.Sequential(*layers)


# ---------------------------------------------------------------------------
class YOLODetectionHead(nn.Module):
    """분리형 anchor-free 탐지 헤드(YOLOX 스타일).

    각 스케일 피처에서 독립적으로 적용.
    출력:
        cls:  [B, num_classes, H, W]
        reg:  [B, 4, H, W]           (cx, cy, w, h) — 그리드 상대 좌표
        obj:  [B, 1, H, W]           (objectness logit)
    """

    def __init__(self, in_channels: int = 256, num_classes: int = NUM_CLASSES):
        super().__init__()
        self.num_classes = num_classes

        # 분류 브랜치
        self.cls_stem = nn.Sequential(
            _conv_bn_act(in_channels, in_channels),
            _conv_bn_act(in_channels, in_channels),
        )
        self.cls_pred = nn.Conv2d(in_channels, num_classes, 1)

        # 박스 회귀 브랜치
        self.reg_stem = nn.Sequential(
            _conv_bn_act(in_channels, in_channels),
            _conv_bn_act(in_channels, in_channels),
        )
        self.reg_pred = nn.Conv2d(in_channels, 4, 1)

        # 객체성 브랜치
        self.obj_pred = nn.Conv2d(in_channels, 1, 1)

        self._init_weights()

    def _init_weights(self):
        prior = 0.01
        import math
        bias_val = -math.log((1 - prior) / prior)
        nn.init.constant_(self.cls_pred.bias, bias_val)
        nn.init.constant_(self.obj_pred.bias, bias_val)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        cls_feat = self.cls_stem(x)
        reg_feat = self.reg_stem(x)
        return {
            "cls": self.cls_pred(cls_feat),          # [B, C, H, W]
            "reg": self.reg_pred(reg_feat),           # [B, 4, H, W]
            "obj": self.obj_pred(reg_feat),           # [B, 1, H, W]
        }


# ---------------------------------------------------------------------------
class AuxHead(nn.Module):
    """보조 분류 헤드 — 단일 백본 C4 피처 → 클래스별 분류 로짓.

    GAP 후 FC; bbox 없이 이미지/패치 레벨 분류만 수행.
    gradient 가 해당 백본으로 역전파돼 단독 모달 패치에서도
    백본을 효과적으로 학습시킨다.
    """

    def __init__(self, in_channels: int, num_classes: int = NUM_CLASSES - 1):
        """num_classes: non_target 제외(person/boar/deer = 3)."""
        super().__init__()
        self.gap = nn.AdaptiveAvgPool2d(1)
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(in_channels, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(256, num_classes),
        )

    def forward(self, feat: torch.Tensor) -> torch.Tensor:
        """입력 특징맵 [B, C, H, W]를 [B, num_classes] 로짓으로 변환."""
        return self.head(self.gap(feat))


# ---------------------------------------------------------------------------
class UncertaintyHead(nn.Module):
    """데이터 자체 노이즈 기반 불확실성 추정 헤드.

    탐지 헤드와 같은 피처를 공유하고,
    각 공간 위치에서 log σ² (log-variance)를 출력.
    손실: NLL loss  ℒ = 0.5 * exp(-s) * ℒ_det + 0.5 * s
          (s = log σ²; Kendall & Gal 2017)
    """

    def __init__(self, in_channels: int = 256):
        super().__init__()
        self.stem = nn.Sequential(
            _conv_bn_act(in_channels, in_channels),
            _conv_bn_act(in_channels, in_channels // 2),
        )
        # 분류 + 회귀 각각 log variance 출력
        self.log_var_cls = nn.Conv2d(in_channels // 2, NUM_CLASSES, 1)
        self.log_var_reg = nn.Conv2d(in_channels // 2, 4, 1)

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        feat = self.stem(x)
        return {
            "log_var_cls": self.log_var_cls(feat),  # [B, C, H, W]
            "log_var_reg": self.log_var_reg(feat),  # [B, 4, H, W]
        }


# ---------------------------------------------------------------------------
class MultiScaleHeads(nn.Module):
    """P3, P4 각 스케일에 탐지 헤드와 불확실성 헤드를 적용.

    aux_rgb / aux_thm 은 외부에서 직접 호출 (backbone C4 입력).
    """

    def __init__(self, fpn_dim: int = 256, scales: list[str] | None = None):
        super().__init__()
        if scales is None:
            scales = ["p3", "p4"]
        self.scales = scales

        # 스케일별 탐지 헤드(가중치 비공유)
        self.det_heads = nn.ModuleDict(
            {s: YOLODetectionHead(fpn_dim) for s in scales}
        )
        # 스케일별 불확실성 헤드
        self.unc_heads = nn.ModuleDict(
            {s: UncertaintyHead(fpn_dim) for s in scales}
        )

    def forward(
        self,
        fpn_feats: dict[str, torch.Tensor],
        uncertainty_active: bool = False,
    ) -> dict[str, dict]:
        """
        Returns:
            {
              'p3': {'cls': ..., 'reg': ..., 'obj': ...,
                     'log_var_cls': ..., 'log_var_reg': ...},  # 활성화 시 불확실성 출력
              'p4': {...},
            }
        """
        out: dict[str, dict] = {}
        for s in self.scales:
            feat = fpn_feats[s]
            det = self.det_heads[s](feat)
            if uncertainty_active:
                unc = self.unc_heads[s](feat)
                det.update(unc)
            out[s] = det
        return out
