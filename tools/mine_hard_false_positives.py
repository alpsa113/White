#!/usr/bin/env python3
"""검증 manifest에서 person false positive 샘플을 추출."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference import DualYOLOPredictor
from inference.preprocessing import load_rgb_image, load_thermal_image


CLASS_NAMES = ["person", "boar", "deer", "non_target"]
PERSON_CLASS_ID = 0
NON_TARGET_CLASS_ID = 3


def load_manifest(path: Path) -> tuple[list[dict], bool]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return list(data.get("samples", [])), True
    return list(data), False


def write_manifest(samples: list[dict], path: Path, wrap_samples: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"samples": samples} if wrap_samples else samples
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_path(path_value: str | None, root: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else root / path


def sample_paths(sample: dict, root: Path) -> tuple[Path | None, Path | None]:
    modality = sample.get("modality")
    image_path = sample.get("image")
    rgb_path = sample.get("rgb") or sample.get("rgb_path")
    thermal_path = sample.get("thermal") or sample.get("thermal_path")
    if modality == "thermal" and thermal_path is None:
        thermal_path = image_path
    elif rgb_path is None:
        rgb_path = image_path
    return resolve_path(rgb_path, root), resolve_path(thermal_path, root)


def box_iou_one(box: list[float], boxes: list[list[float]]) -> float:
    if not boxes:
        return 0.0
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    area1 = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    best = 0.0
    for gt in boxes:
        gx1, gy1, gx2, gy2 = [float(v) for v in gt[:4]]
        inter_x1 = max(x1, gx1)
        inter_y1 = max(y1, gy1)
        inter_x2 = min(x2, gx2)
        inter_y2 = min(y2, gy2)
        inter = max(0.0, inter_x2 - inter_x1) * max(0.0, inter_y2 - inter_y1)
        area2 = max(0.0, gx2 - gx1) * max(0.0, gy2 - gy1)
        union = area1 + area2 - inter
        if union > 0:
            best = max(best, inter / union)
    return best


def fp_reason(sample: dict, has_unmatched_person_pred: bool) -> str | None:
    if not has_unmatched_person_pred:
        return None

    labels = [int(label) for label in sample.get("labels", [])]
    tags = set(sample.get("tags", []))
    if not labels or "empty_background" in tags:
        return "empty_person_fp"
    if PERSON_CLASS_ID not in labels and NON_TARGET_CLASS_ID in labels:
        return "nontarget_person_fp"
    if PERSON_CLASS_ID not in labels:
        return "other_class_person_fp"
    return "person_unmatched_fp"


def load_preview_image(rgb_path: Path | None, thermal_path: Path | None) -> np.ndarray:
    if rgb_path is not None and rgb_path.exists():
        return load_rgb_image(rgb_path)
    if thermal_path is not None and thermal_path.exists():
        gray = load_thermal_image(thermal_path)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    raise FileNotFoundError(f"preview 이미지를 찾지 못했습니다: {rgb_path or thermal_path}")


def draw_preview(
    image_rgb: np.ndarray,
    sample: dict,
    person_fps: list[dict],
    path: Path,
) -> None:
    canvas = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    for box, label in zip(sample.get("boxes", []), sample.get("labels", [])):
        x1, y1, x2, y2 = [int(round(float(v))) for v in box[:4]]
        color = (0, 200, 0) if int(label) == PERSON_CLASS_ID else (0, 180, 255)
        name = CLASS_NAMES[int(label)] if 0 <= int(label) < len(CLASS_NAMES) else str(label)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            canvas,
            f"GT {name}",
            (x1, max(0, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )

    for pred in person_fps:
        x1, y1, x2, y2 = [int(round(float(v))) for v in pred["bbox"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(
            canvas,
            f"FP person {pred['score']:.2f}",
            (x1, min(canvas.shape[0] - 2, y2 + 16)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            1,
            cv2.LINE_AA,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)


def mine_false_positives(args: argparse.Namespace) -> None:
    root = Path(args.root)
    samples, wrap_samples = load_manifest(Path(args.manifest))
    predictor = DualYOLOPredictor(
        checkpoint_path=args.checkpoint,
        model_cfg_path=args.model_cfg,
        device=args.device,
        conf_thresh=args.conf,
        nms_thresh=args.nms,
    )

    mined = []
    reason_counts = Counter()
    processed = 0
    skipped = 0

    preview_dir = Path(args.preview_dir) if args.preview_dir else None

    for idx, sample in enumerate(samples):
        if args.max_samples is not None and processed >= args.max_samples:
            break

        rgb_path, thermal_path = sample_paths(sample, root)
        try:
            result = predictor.predict(rgb_path=rgb_path, thermal_path=thermal_path)
        except Exception as exc:
            skipped += 1
            print(f"[건너뜀] {sample.get('image_id', idx)}: {exc}")
            continue

        gt_person_boxes = [
            box for box, label in zip(sample.get("boxes", []), sample.get("labels", []))
            if int(label) == PERSON_CLASS_ID
        ]
        person_fps = []
        for det in result.detections:
            if det.class_id != PERSON_CLASS_ID or det.score < args.person_conf:
                continue
            best_iou = box_iou_one(det.bbox, gt_person_boxes)
            if best_iou < args.iou:
                person_fps.append({
                    "class_id": det.class_id,
                    "class_name": det.class_name,
                    "score": det.score,
                    "bbox": det.bbox,
                    "best_person_iou": best_iou,
                })

        reason = fp_reason(sample, bool(person_fps))
        if reason is None:
            processed += 1
            continue

        mined_sample = dict(sample)
        mined_sample["tags"] = sorted(set(sample.get("tags", [])) | {"hard_fp", reason})
        mined_sample["hard_fp_reason"] = reason
        mined_sample["fp_predictions"] = person_fps
        mined.append(mined_sample)
        reason_counts[reason] += 1

        if preview_dir is not None and len(mined) <= args.max_previews:
            try:
                image = load_preview_image(rgb_path, thermal_path)
                preview_name = f"{len(mined):05d}_{reason}_{sample.get('image_id', idx)}.jpg"
                safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in preview_name)
                draw_preview(image, sample, person_fps, preview_dir / reason / safe_name)
            except Exception as exc:
                print(f"[preview 실패] {sample.get('image_id', idx)}: {exc}")

        processed += 1

    write_manifest(mined, Path(args.output_manifest), wrap_samples)
    summary = {
        "manifest": args.manifest,
        "checkpoint": args.checkpoint,
        "conf": args.conf,
        "person_conf": args.person_conf,
        "nms": args.nms,
        "iou": args.iou,
        "processed": processed,
        "skipped": skipped,
        "mined": len(mined),
        "reasons": dict(sorted(reason_counts.items())),
        "output_manifest": args.output_manifest,
        "preview_dir": args.preview_dir,
    }
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"처리 샘플: {processed}")
    print(f"건너뜀: {skipped}")
    print(f"오탐 샘플: {len(mined)}")
    print(f"reason 분포: {dict(sorted(reason_counts.items()))}")
    print(f"manifest 저장: {args.output_manifest}")
    print(f"summary 저장: {args.summary}")
    if args.preview_dir:
        print(f"preview 저장: {args.preview_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="person false positive hard sample mining")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--model-cfg", default="configs/model.yaml")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-manifest", default="data/manifests/phase3_hard_fp.json")
    parser.add_argument("--summary", default="outputs/hard_mining/summary.json")
    parser.add_argument("--preview-dir", default="outputs/hard_mining/previews")
    parser.add_argument("--root", default=".")
    parser.add_argument("--device", default=None)
    parser.add_argument("--conf", type=float, default=0.45, help="모델 후처리 confidence")
    parser.add_argument("--person-conf", type=float, default=0.45, help="person FP 채택 confidence")
    parser.add_argument("--nms", type=float, default=0.4)
    parser.add_argument("--iou", type=float, default=0.5, help="person GT와 이 값 미만이면 FP")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--max-previews", type=int, default=300)
    return parser.parse_args()


def main() -> None:
    mine_false_positives(parse_args())


if __name__ == "__main__":
    main()
