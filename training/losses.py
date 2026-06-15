"""
손실 함수 모음

1. detection_loss    — focal cls + CIoU reg + BCE obj
2. aux_loss          — CrossEntropy (보조 분류 헤드)
3. uncertainty_loss  — heteroscedastic NLL (Kendall & Gal 2017)
4. fusion_reg_loss   — 야간 조건에서 열화상 가중치 하한 유도

DualYOLOLoss: 위 손실들을 페이즈 설정에 따라 합산.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


def focal_loss(
    pred: torch.Tensor,   # [N, C] logits
    target: torch.Tensor, # [N, C] one-hot
    alpha: float = 0.25,
    gamma: float = 2.0,
    class_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    p = torch.sigmoid(pred)
    ce = F.binary_cross_entropy_with_logits(pred, target, reduction="none")
    if class_weights is not None:
        ce = ce * class_weights.view(1, -1)
    p_t = p * target + (1 - p) * (1 - target)
    loss = alpha * (1 - p_t) ** gamma * ce
    return loss.mean()


def _decode_pos_boxes(
    reg: torch.Tensor,
    grid_x: torch.Tensor,
    grid_y: torch.Tensor,
    stride: int,
) -> torch.Tensor:
    """Positive 위치의 (cx_rel, cy_rel, log_w, log_h)를 절대 xyxy로 decode."""
    cx = (grid_x.float() + reg[:, 0]) * stride
    cy = (grid_y.float() + reg[:, 1]) * stride
    w = reg[:, 2].clamp(-4, 4).exp() * stride
    h = reg[:, 3].clamp(-4, 4).exp() * stride
    return torch.stack(
        [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
        dim=1,
    )


def ciou_per_box(pred_boxes: torch.Tensor, gt_boxes: torch.Tensor) -> torch.Tensor:
    """Aligned CIoU for xyxy boxes. Returns [N] loss values."""
    eps = 1e-7
    px1, py1, px2, py2 = pred_boxes.unbind(dim=1)
    gx1, gy1, gx2, gy2 = gt_boxes.unbind(dim=1)

    inter_x1 = torch.maximum(px1, gx1)
    inter_y1 = torch.maximum(py1, gy1)
    inter_x2 = torch.minimum(px2, gx2)
    inter_y2 = torch.minimum(py2, gy2)
    inter = (inter_x2 - inter_x1).clamp(min=0) * (inter_y2 - inter_y1).clamp(min=0)

    p_area = (px2 - px1).clamp(min=eps) * (py2 - py1).clamp(min=eps)
    g_area = (gx2 - gx1).clamp(min=eps) * (gy2 - gy1).clamp(min=eps)
    union = p_area + g_area - inter + eps
    iou = inter / union

    pcx = (px1 + px2) / 2
    pcy = (py1 + py2) / 2
    gcx = (gx1 + gx2) / 2
    gcy = (gy1 + gy2) / 2
    rho2 = (pcx - gcx).pow(2) + (pcy - gcy).pow(2)

    cx1 = torch.minimum(px1, gx1)
    cy1 = torch.minimum(py1, gy1)
    cx2 = torch.maximum(px2, gx2)
    cy2 = torch.maximum(py2, gy2)
    c2 = (cx2 - cx1).pow(2) + (cy2 - cy1).pow(2) + eps

    pw = (px2 - px1).clamp(min=eps)
    ph = (py2 - py1).clamp(min=eps)
    gw = (gx2 - gx1).clamp(min=eps)
    gh = (gy2 - gy1).clamp(min=eps)
    v = (4 / torch.pi**2) * (torch.atan(gw / gh) - torch.atan(pw / ph)).pow(2)
    with torch.no_grad():
        alpha = v / (1 - iou + v + eps)
    ciou = iou - rho2 / c2 - alpha * v
    return 1 - ciou


# ---------------------------------------------------------------------------
# Detection Loss
# ---------------------------------------------------------------------------

class DetectionLoss(nn.Module):
    """단일 스케일 anchor-free detection loss.

    타겟 매칭: SimOTA 대신 간소화된 center-based 매칭 사용.
    """

    def __init__(
        self,
        stride: int,
        num_classes: int = 4,
        cls_weight: float = 1.0,
        reg_weight: float = 5.0,
        obj_weight: float = 1.0,
        class_weights: torch.Tensor | None = None,
    ):
        super().__init__()
        self.stride = stride
        self.num_classes = num_classes
        self.cls_w = cls_weight
        self.reg_w = reg_weight
        self.obj_w = obj_weight
        self.register_buffer(
            "class_weights",
            class_weights if class_weights is not None
            else torch.ones(num_classes),
        )

    def _assign_targets(
        self,
        gt_boxes: list[torch.Tensor],  # list[N_i × 4] xyxy
        gt_labels: list[torch.Tensor], # list[N_i]
        H: int, W: int,
        device: torch.device,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Center-point 기반 간단한 타겟 할당.

        Returns:
            obj_mask:  [B, H, W] bool
            cls_target:[B, H, W, C]
            reg_target:[B, H, W, 4]  (cx_rel, cy_rel, log_w, log_h)
        """
        B = len(gt_boxes)
        obj_mask  = torch.zeros(B, H, W, dtype=torch.bool, device=device)
        cls_tgt   = torch.zeros(B, H, W, self.num_classes, device=device)
        reg_tgt   = torch.zeros(B, H, W, 4, device=device)

        for b, (boxes, labels) in enumerate(zip(gt_boxes, gt_labels)):
            if boxes.numel() == 0:
                continue
            # boxes: xyxy 절대 좌표
            cx = (boxes[:, 0] + boxes[:, 2]) / 2 / self.stride
            cy = (boxes[:, 1] + boxes[:, 3]) / 2 / self.stride
            gx = cx.long().clamp(0, W - 1)
            gy = cy.long().clamp(0, H - 1)

            for i, (ix, iy, lab) in enumerate(zip(gx, gy, labels)):
                obj_mask[b, iy, ix] = True
                cls_tgt[b, iy, ix, lab] = 1.0
                w = (boxes[i, 2] - boxes[i, 0]) / self.stride
                h = (boxes[i, 3] - boxes[i, 1]) / self.stride
                reg_tgt[b, iy, ix] = torch.stack([
                    cx[i] - ix.float(),
                    cy[i] - iy.float(),
                    (w.clamp(min=1e-4)).log(),
                    (h.clamp(min=1e-4)).log(),
                ])
        return obj_mask, cls_tgt, reg_tgt

    def forward(
        self,
        pred: dict,                    # {'cls', 'reg', 'obj'}
        gt_boxes: list[torch.Tensor],
        gt_labels: list[torch.Tensor],
        log_var_cls: torch.Tensor | None = None,
        log_var_reg: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        cls_p = pred["cls"]   # [B, C, H, W]
        reg_p = pred["reg"]   # [B, 4, H, W]
        obj_p = pred["obj"]   # [B, 1, H, W]

        B, C, H, W = cls_p.shape
        device = cls_p.device

        obj_mask, cls_tgt, reg_tgt = self._assign_targets(
            gt_boxes, gt_labels, H, W, device
        )

        # --- objectness loss (전체 위치) ---
        obj_tgt = obj_mask.float().unsqueeze(1)  # [B, 1, H, W]
        loss_obj = F.binary_cross_entropy_with_logits(
            obj_p, obj_tgt, pos_weight=torch.tensor(5.0, device=device)
        )

        n_pos = obj_mask.sum().clamp(min=1)

        # --- cls loss (positive 위치만) ---
        cls_p_pos = cls_p.permute(0, 2, 3, 1)[obj_mask]   # [N, C]
        cls_tgt_pos = cls_tgt[obj_mask]                    # [N, C]
        if cls_p_pos.numel() > 0:
            if log_var_cls is not None:
                s = log_var_cls.permute(0, 2, 3, 1)[obj_mask]
                ce = F.binary_cross_entropy_with_logits(cls_p_pos, cls_tgt_pos, reduction="none")
                if self.class_weights is not None:
                    ce = ce * self.class_weights.view(1, -1)
                loss_cls = (0.5 * (-s).exp() * ce + 0.5 * s).mean()
            else:
                loss_cls = focal_loss(
                    cls_p_pos, cls_tgt_pos, class_weights=self.class_weights
                )
        else:
            loss_cls = torch.tensor(0.0, device=device)

        # --- reg loss (positive 위치만) ---
        reg_p_pos = reg_p.permute(0, 2, 3, 1)[obj_mask]   # [N, 4]
        reg_tgt_pos = reg_tgt[obj_mask]                    # [N, 4]
        if reg_p_pos.numel() > 0:
            pos_idx = obj_mask.nonzero(as_tuple=False)
            gy = pos_idx[:, 1]
            gx = pos_idx[:, 2]
            pred_boxes = _decode_pos_boxes(reg_p_pos, gx, gy, self.stride)
            gt_boxes_dec = _decode_pos_boxes(reg_tgt_pos, gx, gy, self.stride)
            ciou_base = ciou_per_box(pred_boxes, gt_boxes_dec)
            if log_var_reg is not None:
                s = log_var_reg.permute(0, 2, 3, 1)[obj_mask].mean(dim=1)
                loss_reg = (0.5 * (-s).exp() * ciou_base + 0.5 * s).mean()
            else:
                loss_reg = ciou_base.mean()
        else:
            loss_reg = torch.tensor(0.0, device=device)

        return {
            "cls":  loss_cls * self.cls_w,
            "reg":  loss_reg * self.reg_w,
            "obj":  loss_obj * self.obj_w,
        }


# ---------------------------------------------------------------------------
# Aux Loss
# ---------------------------------------------------------------------------

def aux_loss(
    pred: torch.Tensor,    # [B, 3]
    labels: torch.Tensor,  # [B] — 이미지/패치 레벨 dominant label
) -> torch.Tensor:
    valid = labels >= 0
    if valid.sum() == 0:
        return pred.sum() * 0.0
    return F.cross_entropy(pred[valid], labels[valid])


# ---------------------------------------------------------------------------
# Fusion Regularization Loss
# ---------------------------------------------------------------------------

def fusion_reg_loss(
    beta_c3: torch.Tensor,   # [B, D]
    beta_c4: torch.Tensor,   # [B, D]
    cond_vec: torch.Tensor,  # [B, 3]
) -> torch.Tensor:
    """야간 조건에서 열화상 가중치(beta)가 높도록 유도.

    야간 배치: β 가 낮을수록 패널티.
    낮 배치: 자유롭게 (정규화 없음).
    """
    illuminance = cond_vec[:, 2]  # 0=야간, 1=주간
    night_mask = illuminance == 0

    if night_mask.sum() == 0:
        return torch.tensor(0.0, device=beta_c3.device)

    beta_night = (
        beta_c3[night_mask].mean(dim=1) + beta_c4[night_mask].mean(dim=1)
    ) / 2
    loss = F.relu(0.4 - beta_night).mean()
    return loss


# ---------------------------------------------------------------------------
# Main Loss Aggregator
# ---------------------------------------------------------------------------

class DualYOLOLoss(nn.Module):
    """페이즈별 손실 항목 제어."""

    STRIDES = {"p3": 8, "p4": 16}

    def __init__(
        self,
        num_classes: int = 4,
        aux_weight: float = 0.3,
        unc_weight: float = 1.0,
        fus_reg_weight: float = 0.1,
        class_weights: torch.Tensor | None = None,
    ):
        super().__init__()
        self.aux_w = aux_weight
        self.unc_w = unc_weight
        self.fus_reg_w = fus_reg_weight

        self.det_losses = nn.ModuleDict({
            s: DetectionLoss(
                stride=stride,
                num_classes=num_classes,
                class_weights=class_weights,
            )
            for s, stride in self.STRIDES.items()
        })

    def forward(
        self,
        model_out: dict,
        gt_boxes: list[torch.Tensor],
        gt_labels: list[torch.Tensor],
        aux_labels_rgb: torch.Tensor | None,
        aux_labels_thm: torch.Tensor | None,
        cond_vec: torch.Tensor,
        aux_active: bool = True,
        uncertainty_active: bool = False,
        fusion_reg_active: bool = False,
    ) -> dict[str, torch.Tensor]:
        """
        model_out: DualYOLO.forward() 반환값
        """
        detections = model_out["detections"]
        fw = model_out["fusion_weights"]
        total = torch.tensor(0.0, device=cond_vec.device)
        losses: dict[str, torch.Tensor] = {}

        # ── Detection Loss (P3 + P4) ──────────────────────────────
        for scale, det_loss_fn in self.det_losses.items():
            pred = detections[scale]
            lv_cls = pred.get("log_var_cls") if uncertainty_active else None
            lv_reg = pred.get("log_var_reg") if uncertainty_active else None

            scale_losses = det_loss_fn(pred, gt_boxes, gt_labels, lv_cls, lv_reg)
            for k, v in scale_losses.items():
                key = f"det_{scale}_{k}"
                losses[key] = v
                total = total + v

        # ── Aux Loss ─────────────────────────────────────────────
        if aux_active:
            if model_out["aux_rgb"] is not None and aux_labels_rgb is not None:
                l_aux_rgb = aux_loss(model_out["aux_rgb"], aux_labels_rgb)
                losses["aux_rgb"] = l_aux_rgb
                total = total + self.aux_w * l_aux_rgb

            if model_out["aux_thm"] is not None and aux_labels_thm is not None:
                l_aux_thm = aux_loss(model_out["aux_thm"], aux_labels_thm)
                losses["aux_thm"] = l_aux_thm
                total = total + self.aux_w * l_aux_thm

        # ── Fusion Regularization ─────────────────────────────────
        if fusion_reg_active:
            l_fus = fusion_reg_loss(fw["beta_c3"], fw["beta_c4"], cond_vec)
            losses["fusion_reg"] = l_fus
            total = total + self.fus_reg_w * l_fus

        losses["total"] = total
        return losses
