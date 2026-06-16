import json
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None


LABEL_MAP = {"person": 0, "boar": 1, "deer": 2, "non_target": 3}
DEFAULT_COND = [0.0, 0.5, 1.0]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def read_json(path: Path):
    with open(path) as f:
        return json.load(f)


def as_path(root: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else root / path)


def keep_sample(labels: list[int], require_labels=None, require_boxes=False) -> bool:
    if require_labels is not None:
        required = {int(label) for label in require_labels}
        return any(int(label) in required for label in labels)
    if require_boxes:
        return len(labels) > 0
    return True


def split_group(item: dict, pattern: str | None = None) -> str:
    import re

    if item.get("split_group"):
        return str(item["split_group"])
    base = str(item.get("image") or item.get("rgb") or item.get("thermal") or item["image_id"])
    if pattern:
        match = re.search(pattern, base)
        if match:
            return match.group(1) if match.groups() else match.group(0)
    return str(item["image_id"])


def iter_images(img_dir: Path) -> list[Path]:
    if not img_dir.exists():
        return []
    return sorted(
        path for path in img_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def read_image_size(path: Path) -> tuple[int, int] | None:
    if cv2 is None:
        raise RuntimeError("YOLO 라벨을 절대 좌표로 변환하려면 opencv-python이 필요합니다")
    image = cv2.imread(str(path))
    if image is None:
        return None
    height, width = image.shape[:2]
    return width, height


def read_yolo_boxes(
    label_path: Path,
    image_path: Path,
    expected_label: int | None = None,
    strict_label_match: bool = False,
) -> tuple[list[list[float]], list[int]]:
    size = read_image_size(image_path)
    if size is None:
        return [], []

    width, height = size
    boxes, labels = [], []
    if not label_path.exists():
        return boxes, labels

    with open(label_path) as f:
        for line_no, line in enumerate(f, start=1):
            parts = line.strip().split()
            if not parts:
                continue
            if len(parts) < 5:
                raise ValueError(f"YOLO 라벨 형식이 올바르지 않습니다: {label_path}:{line_no}")

            label = int(parts[0])
            if (
                strict_label_match
                and expected_label is not None
                and label != expected_label
            ):
                raise ValueError(
                    f"라벨 class가 폴더 class와 다릅니다: "
                    f"{label_path}:{line_no} label={label}, folder={expected_label}"
                )

            cx, cy, bw, bh = map(float, parts[1:5])
            cx, cy, bw, bh = cx * width, cy * height, bw * width, bh * height
            boxes.append([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2])
            labels.append(label)
    return boxes, labels


def tags_for_sample(src: dict, labels: list[int], extra: list[str] | None = None) -> list[str]:
    tags = set(src.get("tags", []))
    if extra:
        tags.update(extra)
    if any(int(label) == 3 for label in labels):
        tags.add("non_target")
    return sorted(tags)
