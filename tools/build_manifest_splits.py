#!/usr/bin/env python3
import argparse
import json
import random
import re
from collections import defaultdict
from pathlib import Path

import yaml

try:
    import cv2
except ImportError:
    cv2 = None


LABEL_MAP = {"person": 0, "boar": 1, "deer": 2, "non_target": 3}
DEFAULT_COND = [0.0, 0.5, 1.0]


def _read_json(path: Path):
    with open(path) as f:
        return json.load(f)


def _write_manifest(path: Path, samples: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"samples": samples}, f, indent=2)


def _print_counter(title: str, counter: dict, denominator: int):
    print(f"  {title}:")
    if not counter:
        print("    (없음)")
        return
    for key, value in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        pct = value / max(denominator, 1) * 100.0
        print(f"    {key}: {value} ({pct:.1f}%)")


def _summarize_manifest(name: str, samples: list[dict]):
    class_names = {0: "person", 1: "boar", 2: "deer", 3: "non_target"}
    by_source = defaultdict(int)
    by_modality = defaultdict(int)
    by_class = defaultdict(int)
    by_tag = defaultdict(int)
    empty_images = 0

    for item in samples:
        by_source[item.get("source", "unknown")] += 1
        by_modality[item.get("modality", "unknown")] += 1

        labels = item.get("labels", [])
        boxes = item.get("boxes", [])
        if not labels or not boxes:
            empty_images += 1
        for label in labels:
            label = int(label)
            by_class[class_names.get(label, str(label))] += 1

        for tag in item.get("tags", []):
            by_tag[tag] += 1

    total_boxes = sum(by_class.values())
    print(f"\n{name}: 전체 이미지 수={len(samples)}")
    _print_counter("source별 분포", by_source, len(samples))
    _print_counter("모달리티별 분포", by_modality, len(samples))
    _print_counter("클래스별 box 분포", by_class, max(total_boxes, 1))
    empty_pct = empty_images / max(len(samples), 1) * 100.0
    print(f"  빈 라벨 이미지: {empty_images} ({empty_pct:.1f}%)")
    _print_counter("tag별 분포", by_tag, len(samples))


def _as_path(root: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else root / path)


def _keep(labels: list[int], require_labels=None, require_boxes=False) -> bool:
    if require_labels is not None:
        required = {int(label) for label in require_labels}
        return any(int(label) in required for label in labels)
    if require_boxes:
        return len(labels) > 0
    return True


def _split_group(item: dict, pattern: str | None = None) -> str:
    if item.get("split_group"):
        return str(item["split_group"])
    base = str(item.get("image") or item.get("rgb") or item.get("thermal") or item["image_id"])
    if pattern:
        match = re.search(pattern, base)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return str(item["image_id"])


def _primary_key(item: dict) -> str:
    labels = sorted({int(label) for label in item.get("labels", [])})
    if labels:
        return "+".join(map(str, labels))
    return "empty"


def _split_items(items: list[dict], val_ratio: float, seed: int) -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    for item in items:
        groups[item["split_group"]].append(item)

    buckets = defaultdict(list)
    for group_items in groups.values():
        buckets[_primary_key(group_items[0])].append(group_items)

    rng = random.Random(seed)
    train, val = [], []
    for bucket_groups in buckets.values():
        rng.shuffle(bucket_groups)
        if len(bucket_groups) <= 1:
            val_count = 0
        else:
            val_count = max(1, round(len(bucket_groups) * val_ratio))
        val_groups = bucket_groups[:val_count]
        train_groups = bucket_groups[val_count:]
        for group in train_groups:
            train.extend(group)
        for group in val_groups:
            val.extend(group)
    return train, val


def _load_coco_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    data = _read_json(Path(src["ann_file"]))
    id2cat = {cat["id"]: cat["name"] for cat in data["categories"]}
    images = {img["id"]: img for img in data["images"]}
    ann_by_img = defaultdict(list)
    for ann in data["annotations"]:
        ann_by_img[ann["image_id"]].append(ann)

    samples = []
    for image_id, image_info in images.items():
        boxes, labels = [], []
        for ann in ann_by_img.get(image_id, []):
            cls_name = id2cat.get(ann["category_id"], "non_target")
            if cls_name == "background":
                continue
            label = LABEL_MAP.get(cls_name, 3)
            x, y, w, h = ann["bbox"]
            boxes.append([x, y, x + w, y + h])
            labels.append(label)
        if not _keep(labels, src.get("require_labels"), src.get("require_boxes", False)):
            continue

        file_name = image_info["file_name"]
        rgb_path = (
            Path(src["rgb_dir"]) / file_name
            if src.get("rgb_dir") else Path(file_name)
        )
        thermal_path = (
            Path(src["thermal_dir"]) / Path(file_name).name
            if src.get("thermal_dir") else None
        )
        modality = src.get("modality", "rgb")
        image_value = None if modality == "thermal" else _as_path(root, str(rgb_path))
        thermal_value = (
            _as_path(root, str(rgb_path)) if modality == "thermal"
            else _as_path(root, str(thermal_path)) if thermal_path else None
        )
        item = {
            "image_id": str(image_id),
            "image": image_value,
            "thermal": thermal_value,
            "boxes": boxes,
            "labels": labels,
            "cond_vec": src.get("cond_vec", DEFAULT_COND),
            "source": src["name"],
            "modality": modality,
            "tags": src.get("tags", []),
        }
        item["split_group"] = _split_group(item, src.get("split_group_pattern"))
        samples.append(item)
    return samples


def _load_manifest_source(src: dict) -> list[dict]:
    root = Path(src.get("root", "."))
    data = _read_json(Path(src["ann_file"]))
    items = data.get("samples", data) if isinstance(data, dict) else data
    samples = []
    for idx, raw in enumerate(items):
        labels = [int(label) for label in raw.get("labels", [])]
        if not _keep(labels, src.get("require_labels"), src.get("require_boxes", False)):
            continue
        item = dict(raw)
        item["image_id"] = str(item.get("image_id") or item.get("id") or f"{src['name']}_{idx}")
        if item.get("image"):
            item["image"] = _as_path(root, item["image"])
        if item.get("rgb"):
            item["rgb"] = _as_path(root, item["rgb"])
        if item.get("thermal"):
            item["thermal"] = _as_path(root, item["thermal"])
        item.setdefault("source", src["name"])
        item.setdefault("modality", src.get("modality", "pair"))
        item.setdefault("cond_vec", src.get("cond_vec", DEFAULT_COND))
        item.setdefault("tags", src.get("tags", []))
        item["split_group"] = _split_group(item, src.get("split_group_pattern"))
        samples.append(item)
    return samples


def _load_yolo_source(src: dict) -> list[dict]:
    if cv2 is None:
        raise RuntimeError("YOLO 소스 split은 이미지 크기를 읽기 위해 opencv-python이 필요합니다")

    root = Path(src.get("root", "."))
    ann_file = Path(src["ann_file"])
    samples = []
    with open(ann_file) as f:
        image_paths = [line.strip() for line in f if line.strip()]

    for idx, image_path in enumerate(image_paths):
        path = Path(image_path)
        abs_path = path if path.is_absolute() else root / path
        label_path = abs_path.with_suffix(".txt")
        labels, boxes = [], []
        image = cv2.imread(str(abs_path))
        if image is None:
            continue
        height, width = image.shape[:2]
        if label_path.exists():
            with open(label_path) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) < 5:
                        continue
                    label = int(parts[0])
                    cx, cy, bw, bh = map(float, parts[1:5])
                    cx, cy, bw, bh = cx * width, cy * height, bw * width, bh * height
                    boxes.append([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2])
                    labels.append(label)
        if not _keep(labels, src.get("require_labels"), src.get("require_boxes", False)):
            continue
        modality = src.get("modality", "rgb")
        item = {
            "image_id": f"{src['name']}_{idx}_{abs_path.stem}",
            "image": None if modality == "thermal" else str(abs_path),
            "thermal": str(abs_path) if modality == "thermal" else None,
            "boxes": boxes,
            "labels": labels,
            "cond_vec": src.get("cond_vec", DEFAULT_COND),
            "source": src["name"],
            "modality": modality,
            "tags": src.get("tags", []),
        }
        item["split_group"] = _split_group(item, src.get("split_group_pattern"))
        samples.append(item)
    return samples


def _parse_kaist_ann(path: Path) -> list[list[float]]:
    boxes = []
    if not path.exists():
        return boxes
    with open(path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts or parts[0] != "person":
                continue
            try:
                x, y, w, h = map(float, parts[1:5])
            except ValueError:
                continue
            boxes.append([x, y, x + w, y + h])
    return boxes


def _load_kaist_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    split_file = Path(src["split_file"])
    samples = []
    with open(split_file) as f:
        entries = [line.strip() for line in f if line.strip()]
    for entry in entries:
        parts = entry.split("/")
        if len(parts) < 3:
            continue
        set_name, vid, img_id = parts[:3]
        rgb_path = root / "images" / set_name / vid / "visible" / f"{img_id}.jpg"
        thm_path = root / "images" / set_name / vid / "lwir" / f"{img_id}.jpg"
        ann_path = root / "annotations" / set_name / vid / f"{img_id}.txt"
        boxes = _parse_kaist_ann(ann_path)
        labels = [0] * len(boxes)
        if not _keep(labels, src.get("require_labels"), src.get("require_boxes", True)):
            continue
        item = {
            "image_id": f"{set_name}_{vid}_{img_id}",
            "rgb": str(rgb_path),
            "thermal": str(thm_path),
            "boxes": boxes,
            "labels": labels,
            "cond_vec": src.get("cond_vec", [0.0, 0.3, 0.0 if set_name >= "set06" else 1.0]),
            "source": src["name"],
            "modality": "pair",
            "tags": src.get("tags", []),
            "split_group": f"{set_name}/{vid}",
        }
        samples.append(item)
    return samples


LOADERS = {
    "coco": _load_coco_source,
    "manifest": _load_manifest_source,
    "yolo": _load_yolo_source,
    "kaist": _load_kaist_source,
}


def build_splits(config: dict):
    output_dir = Path(config.get("output_dir", "data/manifests"))
    seed = int(config.get("seed", 42))
    default_val_ratio = float(config.get("val_ratio", 0.2))

    for phase_name, phase_cfg in config["phases"].items():
        train_all, val_all = [], []
        val_ratio = float(phase_cfg.get("val_ratio", default_val_ratio))
        for src in phase_cfg.get("sources", []):
            loader = LOADERS[src.get("format", src.get("type", "manifest"))]
            items = loader(src)
            train_items, val_items = _split_items(items, val_ratio, seed)
            train_all.extend(train_items)
            val_all.extend(val_items)

        _write_manifest(output_dir / f"{phase_name}_train.json", train_all)
        _write_manifest(output_dir / f"{phase_name}_val.json", val_all)
        print(f"{phase_name}: 학습={len(train_all)} 검증={len(val_all)}")
        _summarize_manifest(f"{phase_name} train", train_all)
        _summarize_manifest(f"{phase_name} val", val_all)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/splits/manifest_splits.yaml")
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)
    build_splits(config)


if __name__ == "__main__":
    main()
