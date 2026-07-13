"""탐지 검증 지표."""

from __future__ import annotations

import torch


STRIDES = {"p3": 8, "p4": 16}


def box_iou(boxes1: torch.Tensor, boxes2: torch.Tensor) -> torch.Tensor:
    if boxes1.numel() == 0 or boxes2.numel() == 0:
        return boxes1.new_zeros((boxes1.shape[0], boxes2.shape[0]))

    x11, y11, x12, y12 = boxes1.unbind(dim=1)
    x21, y21, x22, y22 = boxes2.unbind(dim=1)

    inter_x1 = torch.maximum(x11[:, None], x21[None])
    inter_y1 = torch.maximum(y11[:, None], y21[None])
    inter_x2 = torch.minimum(x12[:, None], x22[None])
    inter_y2 = torch.minimum(y12[:, None], y22[None])
    inter = (inter_x2 - inter_x1).clamp(min=0) * (inter_y2 - inter_y1).clamp(min=0)

    area1 = (x12 - x11).clamp(min=0) * (y12 - y11).clamp(min=0)
    area2 = (x22 - x21).clamp(min=0) * (y22 - y21).clamp(min=0)
    return inter / (area1[:, None] + area2[None] - inter + 1e-7)


def nms(boxes: torch.Tensor, scores: torch.Tensor, iou_thresh: float) -> torch.Tensor:
    if boxes.numel() == 0:
        return torch.empty(0, dtype=torch.long, device=boxes.device)

    keep = []
    order = scores.argsort(descending=True)
    while order.numel() > 0:
        i = order[0]
        keep.append(i)
        if order.numel() == 1:
            break
        ious = box_iou(boxes[i].unsqueeze(0), boxes[order[1:]]).squeeze(0)
        order = order[1:][ious <= iou_thresh]
    return torch.stack(keep) if keep else torch.empty(0, dtype=torch.long, device=boxes.device)


def _decode_scale(pred: dict, stride: int) -> tuple[torch.Tensor, torch.Tensor]:
    reg = pred["reg"]
    cls = pred["cls"].sigmoid()
    obj = pred["obj"].sigmoid()
    B, _, H, W = reg.shape
    device = reg.device

    gy, gx = torch.meshgrid(
        torch.arange(H, device=device, dtype=torch.float32),
        torch.arange(W, device=device, dtype=torch.float32),
        indexing="ij",
    )
    cx = (reg[:, 0] + gx) * stride
    cy = (reg[:, 1] + gy) * stride
    bw = reg[:, 2].clamp(-4, 4).exp() * stride
    bh = reg[:, 3].clamp(-4, 4).exp() * stride
    boxes = torch.stack(
        [cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2],
        dim=-1,
    ).reshape(B, H * W, 4)

    scores = (cls * obj).permute(0, 2, 3, 1).reshape(B, H * W, cls.shape[1])
    return boxes, scores


def decode_detections(
    model_out: dict,
    conf_thresh: float = 0.05,
    nms_thresh: float = 0.6,
    max_detections: int = 300,
) -> list[dict[str, torch.Tensor]]:
    scale_boxes = []
    scale_scores = []
    for scale, stride in STRIDES.items():
        boxes, scores = _decode_scale(model_out["detections"][scale], stride)
        scale_boxes.append(boxes)
        scale_scores.append(scores)

    boxes_all = torch.cat(scale_boxes, dim=1)
    scores_all = torch.cat(scale_scores, dim=1)
    B = boxes_all.shape[0]
    out = []

    for b in range(B):
        scores, labels = scores_all[b].max(dim=1)
        keep = scores >= conf_thresh
        boxes_b = boxes_all[b][keep]
        scores_b = scores[keep]
        labels_b = labels[keep]

        selected = []
        for cls_id in labels_b.unique():
            cls_mask = labels_b == cls_id
            cls_keep = nms(boxes_b[cls_mask], scores_b[cls_mask], nms_thresh)
            original = cls_mask.nonzero(as_tuple=False).squeeze(1)[cls_keep]
            selected.append(original)

        if selected:
            selected = torch.cat(selected)
            selected = selected[scores_b[selected].argsort(descending=True)]
            selected = selected[:max_detections]
            out.append({
                "boxes": boxes_b[selected],
                "scores": scores_b[selected],
                "labels": labels_b[selected],
            })
        else:
            out.append({
                "boxes": boxes_b.new_zeros((0, 4)),
                "scores": scores_b.new_zeros((0,)),
                "labels": labels_b.new_zeros((0,), dtype=torch.long),
            })
    return out


def _compute_ap(tp: torch.Tensor, fp: torch.Tensor, n_gt: int) -> float:
    if n_gt == 0:
        return float("nan")
    if tp.numel() == 0:
        return 0.0

    tp_cum = tp.cumsum(0)
    fp_cum = fp.cumsum(0)
    recall = tp_cum / max(n_gt, 1)
    precision = tp_cum / (tp_cum + fp_cum + 1e-7)

    mrec = torch.cat((recall.new_tensor([0.0]), recall, recall.new_tensor([1.0])))
    mpre = torch.cat((precision.new_tensor([0.0]), precision, precision.new_tensor([0.0])))
    for i in range(mpre.numel() - 1, 0, -1):
        mpre[i - 1] = torch.maximum(mpre[i - 1], mpre[i])
    idx = (mrec[1:] != mrec[:-1]).nonzero(as_tuple=False).squeeze(1)
    return float(((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]).sum().item())


class MeanAveragePrecision:
    def __init__(
        self,
        num_classes: int = 4,
        iou_thresh: float = 0.5,
        iou_thresholds: list[float] | tuple[float, ...] | None = None,
        operating_conf: float = 0.25,
        person_class_id: int = 0,
    ):
        self.num_classes = num_classes
        self.iou_thresh = iou_thresh
        self.iou_thresholds = list(iou_thresholds or [iou_thresh])
        if iou_thresh not in self.iou_thresholds:
            self.iou_thresholds.insert(0, iou_thresh)
        self.operating_conf = operating_conf
        self.person_class_id = person_class_id
        self.pred_scores = [
            [[] for _ in range(num_classes)]
            for _ in self.iou_thresholds
        ]
        self.pred_tp = [
            [[] for _ in range(num_classes)]
            for _ in self.iou_thresholds
        ]
        self.pred_fp = [
            [[] for _ in range(num_classes)]
            for _ in self.iou_thresholds
        ]
        self.n_gt = [0 for _ in range(num_classes)]

    def update(
        self,
        preds: list[dict[str, torch.Tensor]],
        gt_boxes: list[torch.Tensor],
        gt_labels: list[torch.Tensor],
    ):
        for pred, boxes_gt, labels_gt in zip(preds, gt_boxes, gt_labels):
            boxes_pred = pred["boxes"].detach().cpu()
            scores_pred = pred["scores"].detach().cpu()
            labels_pred = pred["labels"].detach().cpu()
            boxes_gt = boxes_gt.detach().cpu()
            labels_gt = labels_gt.detach().cpu()

            for cls_id in range(self.num_classes):
                gt_mask = labels_gt == cls_id
                pred_mask = labels_pred == cls_id
                cls_gt_boxes = boxes_gt[gt_mask]
                cls_pred_boxes = boxes_pred[pred_mask]
                cls_scores = scores_pred[pred_mask]
                self.n_gt[cls_id] += int(cls_gt_boxes.shape[0])

                if cls_pred_boxes.numel() == 0:
                    continue

                order = cls_scores.argsort(descending=True)
                cls_pred_boxes = cls_pred_boxes[order]
                cls_scores = cls_scores[order]
                matched_by_thresh = [
                    torch.zeros(cls_gt_boxes.shape[0], dtype=torch.bool)
                    for _ in self.iou_thresholds
                ]

                for box, score in zip(cls_pred_boxes, cls_scores):
                    if cls_gt_boxes.numel() == 0:
                        for thresh_idx in range(len(self.iou_thresholds)):
                            self.pred_scores[thresh_idx][cls_id].append(float(score.item()))
                            self.pred_tp[thresh_idx][cls_id].append(0.0)
                            self.pred_fp[thresh_idx][cls_id].append(1.0)
                        continue

                    ious = box_iou(box.unsqueeze(0), cls_gt_boxes).squeeze(0)
                    best_iou, best_idx = ious.max(dim=0)
                    for thresh_idx, thresh in enumerate(self.iou_thresholds):
                        matched = matched_by_thresh[thresh_idx]
                        self.pred_scores[thresh_idx][cls_id].append(float(score.item()))
                        if best_iou >= thresh and not matched[best_idx]:
                            matched[best_idx] = True
                            self.pred_tp[thresh_idx][cls_id].append(1.0)
                            self.pred_fp[thresh_idx][cls_id].append(0.0)
                        else:
                            self.pred_tp[thresh_idx][cls_id].append(0.0)
                            self.pred_fp[thresh_idx][cls_id].append(1.0)

    def _class_ap(self, thresh_idx: int, cls_id: int) -> float:
        scores = torch.tensor(self.pred_scores[thresh_idx][cls_id])
        tp = torch.tensor(self.pred_tp[thresh_idx][cls_id])
        fp = torch.tensor(self.pred_fp[thresh_idx][cls_id])
        if scores.numel() > 0:
            order = scores.argsort(descending=True)
            tp = tp[order]
            fp = fp[order]
        return _compute_ap(tp, fp, self.n_gt[cls_id])

    def _person_prf(self, thresh_idx: int) -> tuple[float, float, float]:
        cls_id = self.person_class_id
        scores = torch.tensor(self.pred_scores[thresh_idx][cls_id])
        tp = torch.tensor(self.pred_tp[thresh_idx][cls_id])
        fp = torch.tensor(self.pred_fp[thresh_idx][cls_id])
        if scores.numel() == 0:
            return 0.0, 0.0, 0.0

        keep = scores >= self.operating_conf
        tp_sum = float(tp[keep].sum().item())
        fp_sum = float(fp[keep].sum().item())
        n_gt = max(self.n_gt[cls_id], 0)
        precision = tp_sum / (tp_sum + fp_sum + 1e-7) if tp_sum + fp_sum > 0 else 0.0
        recall = tp_sum / max(n_gt, 1) if n_gt > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall + 1e-7)
            if precision + recall > 0 else 0.0
        )
        return precision, recall, f1

    def compute(self) -> dict[str, float]:
        metrics: dict[str, float] = {}
        valid_ap = []
        valid_ap_5095 = []
        names = ["person", "boar", "deer", "non_target"]
        ap50_idx = self.iou_thresholds.index(self.iou_thresh)
        for cls_id in range(self.num_classes):
            ap = self._class_ap(ap50_idx, cls_id)
            key = f"AP_{names[cls_id] if cls_id < len(names) else cls_id}"
            metrics[key] = ap
            if ap == ap:
                valid_ap.append(ap)
            for thresh_idx in range(len(self.iou_thresholds)):
                ap_at_thresh = self._class_ap(thresh_idx, cls_id)
                if ap_at_thresh == ap_at_thresh:
                    valid_ap_5095.append(ap_at_thresh)
        metrics["mAP50"] = sum(valid_ap) / len(valid_ap) if valid_ap else 0.0
        metrics["mAP50_95"] = (
            sum(valid_ap_5095) / len(valid_ap_5095)
            if valid_ap_5095 else 0.0
        )
        precision, recall, f1 = self._person_prf(ap50_idx)
        metrics["Precision_person"] = precision
        metrics["Recall_person"] = recall
        metrics["F1_person"] = f1
        return metrics
