from collections import defaultdict
from pathlib import Path

from .common import (
    DEFAULT_COND,
    LABEL_MAP,
    as_path,
    cv2,
    keep_sample,
    read_json,
    split_group,
)


def load_coco_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    data = read_json(Path(src["ann_file"]))
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
        if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", False)):
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
        image_value = None if modality == "thermal" else as_path(root, str(rgb_path))
        thermal_value = (
            as_path(root, str(rgb_path)) if modality == "thermal"
            else as_path(root, str(thermal_path)) if thermal_path else None
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
        item["split_group"] = split_group(item, src.get("split_group_pattern"))
        samples.append(item)
    return samples


def load_manifest_source(src: dict) -> list[dict]:
    root = Path(src.get("root", "."))
    data = read_json(Path(src["ann_file"]))
    items = data.get("samples", data) if isinstance(data, dict) else data
    samples = []
    for idx, raw in enumerate(items):
        labels = [int(label) for label in raw.get("labels", [])]
        if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", False)):
            continue
        item = dict(raw)
        item["image_id"] = str(item.get("image_id") or item.get("id") or f"{src['name']}_{idx}")
        if item.get("image"):
            item["image"] = as_path(root, item["image"])
        if item.get("rgb"):
            item["rgb"] = as_path(root, item["rgb"])
        if item.get("thermal"):
            item["thermal"] = as_path(root, item["thermal"])
        item.setdefault("source", src["name"])
        item.setdefault("modality", src.get("modality", "pair"))
        item.setdefault("cond_vec", src.get("cond_vec", DEFAULT_COND))
        item.setdefault("tags", src.get("tags", []))
        item["split_group"] = split_group(item, src.get("split_group_pattern"))
        samples.append(item)
    return samples


def load_yolo_source(src: dict) -> list[dict]:
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
        if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", False)):
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
        item["split_group"] = split_group(item, src.get("split_group_pattern"))
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


def load_kaist_source(src: dict) -> list[dict]:
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
        if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", True)):
            continue
        samples.append({
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
        })
    return samples
