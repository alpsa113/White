"""
Adaptive Middle Fusion

날씨·온도·조도 3차원 조건벡터를 참조해 RGB / 열화상 가중치를
채널 단위로 동적 산출한 뒤 두 피처맵을 합산한다.

    α_i, β_i = softmax( MLP(cond_vec) )   ∀ i ∈ [0, fusion_dim)
    fused = α * proj_rgb + β * proj_thm

단독 모달 배치 처리:
  - rgb_only  : proj_rgb 그대로 반환, α = 1
  - thm_only  : proj_thm 그대로 반환, β = 1
  - pair       : 동적 가중치 합산
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class ConditionWeightNet(nn.Module):
    """조건벡터 → 채널별 가중치 쌍 (α, β) 생성."""

    def __init__(self, cond_dim: int, fusion_dim: int):
        super().__init__()
        hidden = max(64, cond_dim * 4)
        self.mlp = nn.Sequential(
            nn.Linear(cond_dim, hidden),
            nn.ReLU(inplace=True),
            nn.Linear(hidden, hidden),
            nn.ReLU(inplace=True),
            nn.Linear(hidden, fusion_dim * 2),  # 채널별 [α_raw, β_raw]
        )

    def forward(self, cond: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Args:
            cond: [B, cond_dim]
        Returns:
            alpha: [B, fusion_dim]
            beta:  [B, fusion_dim]
        """
        weights = self.mlp(cond)                    # [B, fusion_dim*2]
        weights = weights.view(weights.size(0), 2, -1)  # [B, 2, fusion_dim]
        weights = F.softmax(weights, dim=1)         # 채널별 합이 1
        return weights[:, 0, :], weights[:, 1, :]  # RGB/열화상 가중치


class AdaptiveFusion(nn.Module):
    """RGB + 열화상 C4/C3 피처를 조건벡터 기반으로 융합.

    두 스케일(C3, C4)에 독립적인 projection + weight net 을 적용.
    단독 모달 배치에서는 해당 projection 만 통과.
    """

    def __init__(
        self,
        rgb_c3: int = 256,
        rgb_c4: int = 512,
        thm_c3: int = 256,
        thm_c4: int = 512,
        fusion_dim: int = 256,
        cond_dim: int = 3,
    ):
        super().__init__()
        self.fusion_dim = fusion_dim

        # --- C4 (stride 16) ---
        self.proj_rgb_c4 = nn.Sequential(
            nn.Conv2d(rgb_c4, fusion_dim, 1, bias=False),
            nn.BatchNorm2d(fusion_dim),
            nn.ReLU(inplace=True),
        )
        self.proj_thm_c4 = nn.Sequential(
            nn.Conv2d(thm_c4, fusion_dim, 1, bias=False),
            nn.BatchNorm2d(fusion_dim),
            nn.ReLU(inplace=True),
        )
        self.weight_net_c4 = ConditionWeightNet(cond_dim, fusion_dim)

        # --- C3 (stride 8) ---
        self.proj_rgb_c3 = nn.Sequential(
            nn.Conv2d(rgb_c3, fusion_dim, 1, bias=False),
            nn.BatchNorm2d(fusion_dim),
            nn.ReLU(inplace=True),
        )
        self.proj_thm_c3 = nn.Sequential(
            nn.Conv2d(thm_c3, fusion_dim, 1, bias=False),
            nn.BatchNorm2d(fusion_dim),
            nn.ReLU(inplace=True),
        )
        self.weight_net_c3 = ConditionWeightNet(cond_dim, fusion_dim)

        self.out_channels = fusion_dim

    # ------------------------------------------------------------------
    def _fuse(
        self,
        proj_rgb: torch.Tensor | None,
        proj_thm: torch.Tensor | None,
        alpha: torch.Tensor,
        beta: torch.Tensor,
    ) -> torch.Tensor:
        """RGB/열화상 투영 결과 중 존재하는 것만 사용."""
        if proj_rgb is not None and proj_thm is not None:
            a = alpha.view(*alpha.shape, 1, 1)   # [B, C, 1, 1]
            b = beta.view(*beta.shape, 1, 1)
            return a * proj_rgb + b * proj_thm
        elif proj_rgb is not None:
            return proj_rgb
        else:
            return proj_thm

    def forward(
        self,
        rgb_feats: dict | None,
        thm_feats: dict | None,
        cond_vec: torch.Tensor,       # [B, 3] 조건벡터
    ) -> dict[str, torch.Tensor]:
        """
        Returns:
            {'c3': fused_c3, 'c4': fused_c4}
        """
        # --- C4 ---
        p_rgb_c4 = self.proj_rgb_c4(rgb_feats["c4"]) if rgb_feats is not None else None
        p_thm_c4 = self.proj_thm_c4(thm_feats["c4"]) if thm_feats is not None else None
        a4, b4 = self.weight_net_c4(cond_vec)
        fused_c4 = self._fuse(p_rgb_c4, p_thm_c4, a4, b4)

        # --- C3 ---
        p_rgb_c3 = self.proj_rgb_c3(rgb_feats["c3"]) if rgb_feats is not None else None
        p_thm_c3 = self.proj_thm_c3(thm_feats["c3"]) if thm_feats is not None else None
        a3, b3 = self.weight_net_c3(cond_vec)
        fused_c3 = self._fuse(p_rgb_c3, p_thm_c3, a3, b3)

        return {
            "c3": fused_c3,
            "c4": fused_c4,
            # 정규화 손실용 가중치 노출
            "_alpha_c4": a4,
            "_beta_c4": b4,
            "_alpha_c3": a3,
            "_beta_c3": b3,
        }
