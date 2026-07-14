"""checkpoint 기준 검증 지표와 시각화 산출물 생성."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

# matplotlib/fontconfig는 PR curve와 confusion matrix 저장 시 폰트 캐시를 만든다.
# Colab, 서버, Codex 샌드박스처럼 홈 디렉토리 캐시 권한이 제한된 환경에서도
# 경고 없이 동작하도록 쓰기 가능한 임시 디렉토리를 기본값으로 사용한다.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

import matplotlib.pyplot as plt
import torch
from torch.utils.data import ConcatDataset, DataLoader
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from data.builders import build_dataset
from data.dataset import collate_fn
from data.samplers import (
    ModalityHomogeneousBatchSampler,
    dataset_sample_modalities,
    validate_allowed_modalities,
)
from model import DualYOLO
from training.metrics import MeanAveragePrecision, box_iou, decode_detections
from training.trainer import Trainer


CLASS_NAMES = ["person", "boar", "deer", "non_target"]
COLAB_ARTIFACT_ROOT = Path("/content/drive/MyDrive/dual_yolo")


def default_output_dir() -> str:
    """Colab Drive가 마운트되어 있으면 Drive metrics 경로를 기본값으로 사용."""
    if COLAB_ARTIFACT_ROOT.exists():
        return str(COLAB_ARTIFACT_ROOT / "metrics")
    return "outputs/metrics"


def load_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_model(model_cfg: dict, checkpoint_path: Path, device: torch.device) -> DualYOLO:
    cfg = model_cfg["model"]
    model = DualYOLO(
        fusion_dim=cfg.get("fusion_dim", 256),
        fpn_dim=cfg.get("fpn_dim", 256),
        cond_dim=cfg.get("cond_dim", 3),
        backbone_cfg=cfg.get("backbone", {}),
    )
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    state_dict = Trainer._extract_model_state_dict(checkpoint)
    model.load_state_dict(state_dict)
    model.set_aux_active(False)
    model.set_uncertainty_active(False)
    model.to(device)
    model.eval()
    return model


def build_val_loader(
    phase_yaml: dict,
    batch_size: int,
    num_workers: int,
    img_size: int,
    val_manifest: str | None = None,
) -> DataLoader:
    val_cfgs = phase_yaml.get("val_datasets", [])
    if not val_cfgs:
        raise ValueError("phase 설정에 val_datasets 항목이 없습니다.")
    if val_manifest:
        base_cfg = dict(val_cfgs[0])
        base_cfg["ann_file"] = val_manifest
        val_cfgs = [base_cfg]

    small_box_area = phase_yaml.get("hard_negative_sampling", {}).get(
        "small_box_area", 32 * 32
    )
    datasets = [
        build_dataset(cfg, "val", img_size, small_box_area)
        for cfg in val_cfgs
    ]
    val_ds = ConcatDataset(datasets) if len(datasets) > 1 else datasets[0]
    validate_allowed_modalities(val_ds, phase_yaml, "val")
    sampler = ModalityHomogeneousBatchSampler(
        modalities=dataset_sample_modalities(val_ds),
        batch_size=batch_size,
        drop_last=False,
        shuffle=False,
    )
    return DataLoader(
        val_ds,
        batch_sampler=sampler,
        num_workers=num_workers,
        collate_fn=collate_fn,
        pin_memory=torch.cuda.is_available(),
    )


def to_device(batch: dict, device: torch.device) -> dict:
    out = {}
    for key, value in batch.items():
        if isinstance(value, torch.Tensor):
            out[key] = value.to(device)
        elif isinstance(value, list):
            out[key] = [
                item.to(device) if isinstance(item, torch.Tensor) else item
                for item in value
            ]
        else:
            out[key] = value
    return out


def threshold_rows(
    metric: MeanAveragePrecision,
    class_id: int,
    thresholds: list[float],
) -> list[dict[str, float]]:
    ap50_idx = metric.iou_thresholds.index(metric.iou_thresh)
    scores = torch.tensor(metric.pred_scores[ap50_idx][class_id])
    tp = torch.tensor(metric.pred_tp[ap50_idx][class_id])
    fp = torch.tensor(metric.pred_fp[ap50_idx][class_id])
    n_gt = metric.n_gt[class_id]

    rows = []
    for conf in thresholds:
        keep = scores >= conf
        tp_sum = float(tp[keep].sum().item()) if scores.numel() else 0.0
        fp_sum = float(fp[keep].sum().item()) if scores.numel() else 0.0
        precision = (
            tp_sum / (tp_sum + fp_sum + 1e-7)
            if tp_sum + fp_sum > 0 else 0.0
        )
        recall = tp_sum / max(n_gt, 1) if n_gt > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall + 1e-7)
            if precision + recall > 0 else 0.0
        )
        rows.append({
            "conf": conf,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        })
    return rows


def update_confusion_matrix(
    matrix: torch.Tensor,
    pred: dict[str, torch.Tensor],
    gt_boxes: torch.Tensor,
    gt_labels: torch.Tensor,
    conf_thresh: float,
    iou_thresh: float,
) -> None:
    bg = len(CLASS_NAMES)
    boxes_pred = pred["boxes"].detach().cpu()
    scores_pred = pred["scores"].detach().cpu()
    labels_pred = pred["labels"].detach().cpu()
    keep = scores_pred >= conf_thresh
    boxes_pred = boxes_pred[keep]
    scores_pred = scores_pred[keep]
    labels_pred = labels_pred[keep]
    gt_boxes = gt_boxes.detach().cpu()
    gt_labels = gt_labels.detach().cpu()

    matched_gt = torch.zeros(gt_boxes.shape[0], dtype=torch.bool)
    order = scores_pred.argsort(descending=True)
    for pred_idx in order:
        pred_box = boxes_pred[pred_idx]
        pred_label = int(labels_pred[pred_idx].item())
        if gt_boxes.numel() == 0:
            matrix[bg, pred_label] += 1
            continue

        ious = box_iou(pred_box.unsqueeze(0), gt_boxes).squeeze(0)
        best_iou, best_gt_idx = ious.max(dim=0)
        if best_iou >= iou_thresh and not matched_gt[best_gt_idx]:
            matched_gt[best_gt_idx] = True
            gt_label = int(gt_labels[best_gt_idx].item())
            matrix[gt_label, pred_label] += 1
        else:
            matrix[bg, pred_label] += 1

    for gt_idx, matched in enumerate(matched_gt):
        if not matched:
            matrix[int(gt_labels[gt_idx].item()), bg] += 1


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def plot_pr_curve(rows: list[dict[str, float]], path: Path, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    recalls = [row["recall"] for row in rows]
    precisions = [row["precision"] for row in rows]
    plt.figure(figsize=(6, 5))
    plt.plot(recalls, precisions, marker="o", linewidth=2)
    plt.xlabel("Recall")
    plt.ylabel("Precision")
    plt.title(title)
    plt.grid(True, alpha=0.25)
    plt.xlim(0, 1)
    plt.ylim(0, 1)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def write_confusion_matrix(matrix: torch.Tensor, csv_path: Path, png_path: Path) -> None:
    labels = CLASS_NAMES + ["background"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["actual/pred"] + labels)
        for label, row in zip(labels, matrix.tolist()):
            writer.writerow([label] + row)

    plt.figure(figsize=(7, 6))
    plt.imshow(matrix.numpy(), cmap="Blues")
    plt.colorbar(label="count")
    plt.xticks(range(len(labels)), labels, rotation=35, ha="right")
    plt.yticks(range(len(labels)), labels)
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.title("Confusion Matrix")
    for y in range(matrix.shape[0]):
        for x in range(matrix.shape[1]):
            value = int(matrix[y, x].item())
            if value:
                plt.text(x, y, str(value), ha="center", va="center", fontsize=8)
    plt.tight_layout()
    plt.savefig(png_path, dpi=160)
    plt.close()


@torch.no_grad()
def evaluate(args: argparse.Namespace) -> None:
    model_cfg = load_yaml(args.model_cfg)
    phases_yaml = load_yaml(args.phase_cfg)
    phase_yaml = phases_yaml[f"phase{args.phase}"]
    device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
    img_size = int(args.img_size or model_cfg.get("training", {}).get("img_size", 640))

    model = build_model(model_cfg, Path(args.checkpoint), device)
    val_loader = build_val_loader(
        phase_yaml,
        batch_size=args.batch,
        num_workers=args.num_workers,
        img_size=img_size,
        val_manifest=args.val_manifest,
    )
    metric = MeanAveragePrecision(
        num_classes=len(CLASS_NAMES),
        iou_thresh=args.iou,
        iou_thresholds=[x / 100 for x in range(50, 100, 5)],
        operating_conf=args.conf,
    )
    confusion = torch.zeros((len(CLASS_NAMES) + 1, len(CLASS_NAMES) + 1), dtype=torch.long)

    for batch_idx, batch in enumerate(val_loader):
        if args.max_batches is not None and batch_idx >= args.max_batches:
            break
        batch = to_device(batch, device)
        rgb = batch.get("rgb")
        thermal = batch.get("thermal")
        if rgb is None and thermal is None:
            raise RuntimeError(
                "배치에 RGB/TIR 입력 텐서가 없습니다. "
                "manifest의 image/rgb/thermal 경로와 실제 파일 존재 여부를 확인하세요."
            )
        out = model(rgb, thermal, batch["cond_vec"])
        preds = decode_detections(
            out,
            conf_thresh=args.min_conf,
            nms_thresh=args.nms,
            max_detections=args.max_detections,
        )
        gt_boxes = batch["boxes"]
        gt_labels = batch["labels"]
        metric.update(preds, gt_boxes, gt_labels)
        for pred, boxes, labels in zip(preds, gt_boxes, gt_labels):
            update_confusion_matrix(
                confusion,
                pred,
                boxes,
                labels,
                conf_thresh=args.conf,
                iou_thresh=args.iou,
            )

    metrics = metric.compute()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or f"phase{args.phase}"

    summary_path = output_dir / f"{prefix}_summary.json"
    summary_path.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    thresholds = [round(x / 100, 2) for x in range(5, 100, 5)]
    rows = threshold_rows(metric, class_id=0, thresholds=thresholds)
    threshold_csv = output_dir / f"{prefix}_threshold_table_person.csv"
    write_csv(rows, threshold_csv)
    pr_png = output_dir / f"{prefix}_pr_curve_person.png"
    plot_pr_curve(rows, pr_png, f"Phase {args.phase} Person PR Curve")

    cm_csv = output_dir / f"{prefix}_confusion_matrix.csv"
    cm_png = output_dir / f"{prefix}_confusion_matrix.png"
    write_confusion_matrix(confusion, cm_csv, cm_png)

    print(f"요약 저장: {summary_path}")
    print(f"threshold table 저장: {threshold_csv}")
    print(f"PR curve 저장: {pr_png}")
    print(f"confusion matrix 저장: {cm_csv}")
    print(f"confusion matrix 그림 저장: {cm_png}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DualYOLO checkpoint 검증/시각화")
    parser.add_argument("--checkpoint", required=True, help="평가할 checkpoint")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--model-cfg", default="configs/model.yaml")
    parser.add_argument("--phase-cfg", default="configs/phases.yaml")
    parser.add_argument(
        "--val-manifest",
        default=None,
        help="phase 설정의 val_datasets 대신 사용할 검증 manifest",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="평가 산출물 출력 디렉토리. Colab Drive가 있으면 기본값은 /content/drive/MyDrive/dual_yolo/metrics",
    )
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--img-size", type=int, default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--conf", type=float, default=0.50, help="운영 지표 기준 confidence")
    parser.add_argument("--min-conf", type=float, default=0.05, help="PR curve 후보 보존용 최소 confidence")
    parser.add_argument("--nms", type=float, default=0.4)
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--max-detections", type=int, default=300)
    parser.add_argument("--max-batches", type=int, default=None, help="smoke test용 최대 배치 수")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output_dir is None:
        args.output_dir = default_output_dir()
    evaluate(args)


if __name__ == "__main__":
    main()
