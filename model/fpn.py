"""
특징 피라미드 네트워크(FPN)

융합된 {c3, c4} 피처를 받아 P3(small), P4(large)를 생성.

    P4 = conv(c4)
    P3 = conv(upsample(P4) + c3)

출력 채널은 모두 fpn_dim (기본 256).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


def _conv_bn_relu(in_ch: int, out_ch: int, k: int = 3, p: int = 1) -> nn.Sequential:
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, k, padding=p, bias=False),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
    )


class FPN(nn.Module):
    """2단계 FPN: P4(stride 16) → P3(stride 8)."""

    def __init__(self, in_channels: int = 256, fpn_dim: int = 256):
        super().__init__()
        # 측면 투영
        self.lat_c4 = nn.Conv2d(in_channels, fpn_dim, 1, bias=False)
        self.lat_c3 = nn.Conv2d(in_channels, fpn_dim, 1, bias=False)

        # 출력 합성곱
        self.out_p4 = _conv_bn_relu(fpn_dim, fpn_dim)
        self.out_p3 = _conv_bn_relu(fpn_dim, fpn_dim)

        self.out_channels = fpn_dim

    def forward(self, fused: dict) -> dict[str, torch.Tensor]:
        """
        Args:
            fused: {'c3': [B, C, H/8, W/8], 'c4': [B, C, H/16, W/16], ...}
        Returns:
            {'p3': [B, fpn_dim, H/8, W/8],
             'p4': [B, fpn_dim, H/16, W/16]}
        """
        c4 = fused["c4"]
        c3 = fused["c3"]

        p4_lat = self.lat_c4(c4)                                     # [B, fpn_dim, H/16]
        p4 = self.out_p4(p4_lat)

        p4_up = F.interpolate(p4_lat, size=c3.shape[-2:], mode="nearest")
        p3_lat = self.lat_c3(c3) + p4_up
        p3 = self.out_p3(p3_lat)

        return {"p3": p3, "p4": p4}
