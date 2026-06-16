from pathlib import Path

from .common import (
    DEFAULT_COND,
    iter_images,
    keep_sample,
    read_yolo_boxes,
    tags_for_sample,
)


def _modality_cond(src: dict, modality: str) -> list[float]:
    by_modality = src.get("cond_vec_by_modality", {})
    return by_modality.get(modality, src.get("cond_vec", DEFAULT_COND))


def _modality_dir(src: dict, modality: str) -> str:
    dirs = src.get("modality_dirs", {})
    return dirs.get(modality, modality)


def load_gop_class_yolo_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    if not root.exists():
        if src.get("optional", False):
            return []
        raise FileNotFoundError(f"GOP raw single 루트가 없습니다: {root}")

    samples = []
    class_ids = [int(class_id) for class_id in src.get("classes", [0, 1, 2, 3])]
    modalities = src.get("include_modalities", ["rgb", "thermal"])
    image_dir_name = src.get("image_dir", "img")
    label_dir_name = src.get("label_dir", "label")
    strict_label_match = bool(src.get("strict_label_match", True))

    for class_id in class_ids:
        class_root = root / str(class_id)
        if not class_root.exists():
            if src.get("skip_missing_class_dirs", True):
                continue
            raise FileNotFoundError(f"GOP class 디렉토리가 없습니다: {class_root}")

        for modality in modalities:
            modality = "thermal" if modality == "tir" else modality
            modality_root = class_root / _modality_dir(src, modality)
            img_dir = modality_root / image_dir_name
            label_dir = modality_root / label_dir_name
            for image_path in iter_images(img_dir):
                label_path = label_dir / f"{image_path.stem}.txt"
                boxes, labels = read_yolo_boxes(
                    label_path,
                    image_path,
                    expected_label=class_id,
                    strict_label_match=strict_label_match,
                )
                if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", False)):
                    continue

                source_name = f"{src['name']}_{modality}"
                samples.append({
                    "image_id": f"{source_name}_{class_id}_{image_path.stem}",
                    "image": str(image_path) if modality == "rgb" else None,
                    "thermal": str(image_path) if modality == "thermal" else None,
                    "boxes": boxes,
                    "labels": labels,
                    "cond_vec": _modality_cond(src, modality),
                    "source": source_name,
                    "modality": modality,
                    "tags": tags_for_sample(src, labels),
                    "split_group": f"{src['name']}_{class_id}_{image_path.stem}",
                })
    return samples


def _images_by_stem(img_dir: Path) -> dict[str, Path]:
    return {path.stem: path for path in iter_images(img_dir)}


def load_gop_class_yolo_pair_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    if not root.exists():
        if src.get("optional", False):
            return []
        raise FileNotFoundError(f"GOP raw pair 루트가 없습니다: {root}")

    samples = []
    class_ids = [int(class_id) for class_id in src.get("classes", [0, 1, 2, 3])]
    image_dir_name = src.get("image_dir", "img")
    label_dir_name = src.get("label_dir", "label")
    rgb_dir_name = src.get("rgb_dir", "rgb")
    thermal_dir_name = src.get("thermal_dir", "tir")
    label_source = src.get("label_source", "rgb")
    strict_label_match = bool(src.get("strict_label_match", True))

    for class_id in class_ids:
        class_root = root / str(class_id)
        if not class_root.exists():
            if src.get("skip_missing_class_dirs", True):
                continue
            raise FileNotFoundError(f"GOP pair class 디렉토리가 없습니다: {class_root}")

        rgb_root = class_root / rgb_dir_name
        thermal_root = class_root / thermal_dir_name
        rgb_images = _images_by_stem(rgb_root / image_dir_name)
        thermal_images = _images_by_stem(thermal_root / image_dir_name)
        shared_stems = sorted(set(rgb_images) & set(thermal_images))

        for stem in shared_stems:
            rgb_path = rgb_images[stem]
            thermal_path = thermal_images[stem]
            label_root = rgb_root if label_source == "rgb" else thermal_root
            label_image = rgb_path if label_source == "rgb" else thermal_path
            label_path = label_root / label_dir_name / f"{stem}.txt"
            boxes, labels = read_yolo_boxes(
                label_path,
                label_image,
                expected_label=class_id,
                strict_label_match=strict_label_match,
            )
            if not keep_sample(labels, src.get("require_labels"), src.get("require_boxes", False)):
                continue

            samples.append({
                "image_id": f"{src['name']}_{class_id}_{stem}",
                "rgb": str(rgb_path),
                "thermal": str(thermal_path),
                "boxes": boxes,
                "labels": labels,
                "cond_vec": src.get("cond_vec", DEFAULT_COND),
                "source": src["name"],
                "modality": "pair",
                "tags": tags_for_sample(src, labels),
                "split_group": f"{src['name']}_{class_id}_{stem}",
            })
    return samples


def load_gop_empty_folder_source(src: dict) -> list[dict]:
    root = Path(src["root"])
    if not root.exists():
        if src.get("optional", False):
            return []
        raise FileNotFoundError(f"GOP empty 루트가 없습니다: {root}")

    samples = []
    modalities = src.get("include_modalities", ["rgb", "thermal"])
    image_dir_name = src.get("image_dir", "img")

    for modality in modalities:
        modality = "thermal" if modality == "tir" else modality
        img_dir = root / _modality_dir(src, modality) / image_dir_name
        for image_path in iter_images(img_dir):
            source_name = f"{src['name']}_{modality}"
            samples.append({
                "image_id": f"{source_name}_{image_path.stem}",
                "image": str(image_path) if modality == "rgb" else None,
                "thermal": str(image_path) if modality == "thermal" else None,
                "boxes": [],
                "labels": [],
                "cond_vec": _modality_cond(src, modality),
                "source": source_name,
                "modality": modality,
                "tags": tags_for_sample(src, [], ["empty_background"]),
                "split_group": f"{src['name']}_{image_path.stem}",
            })
    return samples
