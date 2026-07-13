"""
DualYOLO — 전체 모델 조립

입력 → DualBackbone → AdaptiveFusion → FPN → MultiScaleHeads
                              ↓
                     AuxHead (RGB C4, Thermal C4)
"""

import torch
import torch.nn as nn

from .backbone import DualBackbone
from .fusion import AdaptiveFusion
from .fpn import FPN
from .heads import AuxHead, MultiScaleHeads


class DualYOLO(nn.Module):
    """GOP 경계 탐지용 이중 백본 + 조건 적응형 융합 YOLO 모델.

    Args:
        fusion_dim:   Adaptive Fusion 출력 채널 수 (기본 256)
        fpn_dim:      FPN 출력 채널 수 (기본 256)
        cond_dim:     조건벡터 차원 (기본 3)
        backbone_cfg:     YOLO26-M COCO checkpoint 및 C3/C4 추출 설정
        aux_active:       보조 헤드 활성화 (Phase 1·2)
        uncertainty_active: 불확실성 헤드 활성화 (Phase 2 후반~3)
    """

    def __init__(
        self,
        fusion_dim: int = 256,
        fpn_dim: int = 256,
        cond_dim: int = 3,
        backbone_cfg: dict | None = None,
        aux_active: bool = True,
        uncertainty_active: bool = False,
    ):
        super().__init__()

        self.aux_active = aux_active
        self.uncertainty_active = uncertainty_active

        # ── 백본 ─────────────────────────────────────────────────
        self.backbone = DualBackbone(backbone_cfg=backbone_cfg)
        rgb_c3 = self.backbone.rgb.out_channels["c3"]
        rgb_c4 = self.backbone.rgb.out_channels["c4"]
        thm_c3 = self.backbone.thm.out_channels["c3"]
        thm_c4 = self.backbone.thm.out_channels["c4"]

        # ── 조건 적응형 융합 ─────────────────────────────────────
        self.fusion = AdaptiveFusion(
            rgb_c3=rgb_c3, rgb_c4=rgb_c4,
            thm_c3=thm_c3, thm_c4=thm_c4,
            fusion_dim=fusion_dim,
            cond_dim=cond_dim,
        )

        # ── 특징 피라미드 ───────────────────────────────────────
        self.fpn = FPN(in_channels=fusion_dim, fpn_dim=fpn_dim)

        # ── 탐지 헤드 ───────────────────────────────────────────
        self.ms_heads = MultiScaleHeads(fpn_dim=fpn_dim)

        # ── 보조 헤드 ───────────────────────────────────────────
        self.aux_rgb = AuxHead(in_channels=rgb_c4)
        self.aux_thm = AuxHead(in_channels=thm_c4)

    # ------------------------------------------------------------------
    def set_aux_active(self, flag: bool):
        self.aux_active = flag

    def set_uncertainty_active(self, flag: bool):
        self.uncertainty_active = flag

    # ------------------------------------------------------------------
    def forward(
        self,
        rgb: torch.Tensor | None,
        thermal: torch.Tensor | None,
        cond_vec: torch.Tensor,
    ) -> dict:
        """
        Args:
            rgb:      [B, 3, H, W] or None
            thermal:  [B, 1, H, W] or None
            cond_vec: [B, 3]  조건벡터 (없으면 DEFAULT_COND)

        Returns: {
            'detections': {
                'p3': {'cls', 'reg', 'obj', ['log_var_cls', 'log_var_reg']},
                'p4': {...}
            },
            'fusion_weights': {'alpha_c4', 'beta_c4', 'alpha_c3', 'beta_c3'},
            'aux_rgb':  [B, 3] or None,
            'aux_thm':  [B, 3] or None,
        }
        """
        # 1. 백본
        rgb_feats, thm_feats = self.backbone(rgb, thermal)

        # 2. 조건 적응형 융합
        fused = self.fusion(rgb_feats, thm_feats, cond_vec)

        # 3. 특징 피라미드
        fpn_feats = self.fpn(fused)

        # 4. 탐지
        detections = self.ms_heads(fpn_feats, self.uncertainty_active)

        # 5. 보조 헤드
        aux_rgb_out = None
        aux_thm_out = None
        if self.aux_active:
            if rgb_feats is not None:
                aux_rgb_out = self.aux_rgb(rgb_feats["c4"])
            if thm_feats is not None:
                aux_thm_out = self.aux_thm(thm_feats["c4"])

        return {
            "detections": detections,
            "fusion_weights": {
                "alpha_c4": fused["_alpha_c4"],
                "beta_c4":  fused["_beta_c4"],
                "alpha_c3": fused["_alpha_c3"],
                "beta_c3":  fused["_beta_c3"],
            },
            "aux_rgb": aux_rgb_out,
            "aux_thm": aux_thm_out,
        }

    # ------------------------------------------------------------------
    def freeze_backbone(self):
        """3단계 전반부 — 백본 파라미터 동결."""
        for p in self.backbone.parameters():
            p.requires_grad_(False)

    def unfreeze_backbone(self):
        """3단계 후반부 — 백본 동결 해제."""
        for p in self.backbone.parameters():
            p.requires_grad_(True)

    def get_param_groups(self, phase: int) -> list[dict]:
        """페이즈별 optimizer 파라미터 그룹 반환.

        Phase 1: backbone lr=1e-5, rest lr=1e-4
        Phase 2: backbone lr=5e-6, rest lr=1e-5, uncertainty lr=1e-4
        Phase 3: backbone frozen (or lr=5e-6), rest lr=1e-5
        """
        backbone_params = list(self.backbone.parameters())
        fusion_fpn_params = (
            list(self.fusion.parameters())
            + list(self.fpn.parameters())
        )
        head_params = (
            list(self.ms_heads.det_heads.parameters())
            + list(self.aux_rgb.parameters())
            + list(self.aux_thm.parameters())
        )
        unc_params = list(self.ms_heads.unc_heads.parameters())

        if phase == 1:
            return [
                {"params": backbone_params,         "lr": 1e-5, "name": "backbone"},
                {"params": fusion_fpn_params + head_params, "lr": 1e-4, "name": "fusion_fpn_head"},
                {"params": unc_params,               "lr": 1e-4, "name": "uncertainty"},
            ]
        elif phase == 2:
            return [
                {"params": backbone_params,         "lr": 5e-6, "name": "backbone"},
                {"params": fusion_fpn_params + head_params, "lr": 1e-5, "name": "fusion_fpn_head"},
                {"params": unc_params,               "lr": 1e-4, "name": "uncertainty"},
            ]
        else:  # 3단계
            return [
                {"params": backbone_params,         "lr": 5e-6, "name": "backbone"},
                {"params": fusion_fpn_params + head_params + unc_params, "lr": 1e-5, "name": "rest"},
            ]
