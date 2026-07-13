"""phase3 검증 manifest를 standard/hard 난이도로 분리."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2


CLASS_NAMES = {
    0: "person",
    1: "boar",
    2: "deer",
    3: "non_target",
}


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


def resolve_image_path(sample: dict, root: Path) -> Path | None:
    path_value = (
        sample.get("image")
        or sample.get("rgb")
        or sample.get("rgb_path")
        or sample.get("thermal")
        or sample.get("thermal_path")
    )
    if not path_value:
        return None
    path = Path(path_value)
    return path if path.is_absolute() else root / path


def image_size(sample: dict, root: Path) -> tuple[int, int]:
    image_path = resolve_image_path(sample, root)
    if image_path is not None and image_path.exists():
        img = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        if img is not None:
            height, width = img.shape[:2]
            return int(width), int(height)

    max_x = 0.0
    max_y = 0.0
    for box in sample.get("boxes", []):
        if len(box) >= 4:
            max_x = max(max_x, float(box[0]), float(box[2]))
            max_y = max(max_y, float(box[1]), float(box[3]))
    return int(max(max_x, 1.0)), int(max(max_y, 1.0))


def box_area_ratio(box: list[float], width: int, height: int) -> float:
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    image_area = max(float(width * height), 1.0)
    return box_area / image_area


def hard_reason(label: int, area_ratio: float) -> str | None:
    if label == 0 and area_ratio < 0.0025:
        return "person_area_lt_0.25pct"
    if label in (1, 2) and area_ratio < 0.01:
        return f"{CLASS_NAMES[label]}_area_lt_1pct"
    if label == 3 and area_ratio < 0.0025:
        return "non_target_area_lt_0.25pct"
    return None


def classify_sample(sample: dict, root: Path) -> tuple[str, list[str]]:
    labels = [int(label) for label in sample.get("labels", [])]
    boxes = sample.get("boxes", [])
    tags = set(sample.get("tags", []))

    if not labels or not boxes or "empty_background" in tags:
        return "hard", ["empty_background"]

    width, height = image_size(sample, root)
    reasons = []
    for box, label in zip(boxes, labels):
        reason = hard_reason(label, box_area_ratio(box, width, height))
        if reason:
            reasons.append(reason)

    return ("hard", reasons) if reasons else ("standard", [])


def summarize(samples: list[dict], name: str) -> dict:
    class_counts = Counter()
    modality_counts = Counter()
    source_counts = Counter()
    empty_count = 0

    for sample in samples:
        labels = [int(label) for label in sample.get("labels", [])]
        if not labels:
            empty_count += 1
        for label in set(labels):
            class_counts[CLASS_NAMES.get(label, str(label))] += 1
        modality_counts[str(sample.get("modality", "unknown"))] += 1
        source_counts[str(sample.get("source", "unknown"))] += 1

    return {
        "name": name,
        "samples": len(samples),
        "empty": empty_count,
        "classes": dict(sorted(class_counts.items())),
        "modalities": dict(sorted(modality_counts.items())),
        "sources": dict(sorted(source_counts.items())),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="phase3_val manifest를 bbox 면적 기준 standard/hard로 분리"
    )
    parser.add_argument("--input", default="data/manifests/phase3_val.json")
    parser.add_argument("--standard-output", default="data/manifests/phase3_val_standard.json")
    parser.add_argument("--hard-output", default="data/manifests/phase3_val_hard.json")
    parser.add_argument("--summary-output", default="data/manifests/phase3_val_difficulty_summary.json")
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    samples, wrap_samples = load_manifest(Path(args.input))

    standard_samples = []
    hard_samples = []
    reason_counts = Counter()

    for sample in samples:
        bucket, reasons = classify_sample(sample, root)
        if bucket == "hard":
            hard_samples.append(sample)
            reason_counts.update(reasons)
        else:
            standard_samples.append(sample)

    write_manifest(standard_samples, Path(args.standard_output), wrap_samples)
    write_manifest(hard_samples, Path(args.hard_output), wrap_samples)

    summary = {
        "input": args.input,
        "standard_output": args.standard_output,
        "hard_output": args.hard_output,
        "criteria": {
            "person_hard": "bbox area < 0.25%",
            "boar_deer_hard": "bbox area < 1%",
            "non_target_hard": "bbox area < 0.25%",
            "empty_background": "hard",
        },
        "hard_reasons": dict(sorted(reason_counts.items())),
        "splits": [
            summarize(standard_samples, "standard"),
            summarize(hard_samples, "hard"),
        ],
    }
    Path(args.summary_output).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"standard 저장: {args.standard_output} ({len(standard_samples)}개)")
    print(f"hard 저장: {args.hard_output} ({len(hard_samples)}개)")
    print(f"요약 저장: {args.summary_output}")


if __name__ == "__main__":
    main()
