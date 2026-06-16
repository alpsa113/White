#!/usr/bin/env python3
"""LLVIP 원본 데이터를 phase2 표준 pair 디렉토리로 변환.

출력 구조:
    data/phase2_raw/pair/0/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/

LLVIP는 person 중심 데이터셋이므로 class id는 0으로 기록한다.
"""

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")


def _image_size(path: Path) -> tuple[int, int]:
    if cv2 is None:
        raise RuntimeError("이미지 크기 확인을 위해 opencv-python이 필요합니다")
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    height, width = image.shape[:2]
    return width, height


def _clip_box(box: list[float], width: int, height: int) -> list[float] | None:
    x1, y1, x2, y2 = box
    x1 = max(0.0, min(float(width), x1))
    y1 = max(0.0, min(float(height), y1))
    x2 = max(0.0, min(float(width), x2))
    y2 = max(0.0, min(float(height), y2))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _to_yolo_line(box: list[float], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    cx = ((x1 + x2) / 2) / width
    cy = ((y1 + y2) / 2) / height
    bw = (x2 - x1) / width
    bh = (y2 - y1) / height
    return f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def _parse_voc_xml(xml_path: Path) -> list[list[float]]:
    boxes = []
    if not xml_path.exists():
        return boxes
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return boxes

    for obj in root.findall("object"):
        name = (obj.findtext("name", "person") or "person").lower()
        if name not in {"person", "people", "pedestrian"}:
            continue
        bb = obj.find("bndbox")
        if bb is None:
            continue
        x1 = float(bb.findtext("xmin", "0"))
        y1 = float(bb.findtext("ymin", "0"))
        x2 = float(bb.findtext("xmax", "0"))
        y2 = float(bb.findtext("ymax", "0"))
        boxes.append([x1, y1, x2, y2])
    return boxes


def _load_coco_boxes(ann_file: Path) -> dict[str, list[list[float]]]:
    with open(ann_file) as f:
        data = json.load(f)

    images = {image["id"]: image for image in data.get("images", [])}
    id2cat = {cat["id"]: cat.get("name", "person") for cat in data.get("categories", [])}
    boxes_by_stem: dict[str, list[list[float]]] = {}
    for ann in data.get("annotations", []):
        image = images.get(ann["image_id"])
        if image is None:
            continue
        cls_name = id2cat.get(ann.get("category_id"), "person").lower()
        if cls_name not in {"person", "people", "pedestrian"}:
            continue
        x, y, w, h = ann["bbox"]
        stem = Path(image["file_name"]).stem
        boxes_by_stem.setdefault(stem, []).append([x, y, x + w, y + h])
    return boxes_by_stem


def _find_image_by_stem(directory: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        candidate = directory / f"{stem}{ext}"
        if candidate.exists():
            return candidate
    return None


def _iter_visible_images(visible_dir: Path) -> list[Path]:
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(visible_dir.glob(f"*{ext}"))
    return sorted(images)


def convert_llvip(
    root: Path,
    output: Path,
    split: str = "train",
    ann_file: Path | None = None,
    overwrite: bool = False,
) -> int:
    visible_dir = root / "visible" / split
    infrared_dir = root / "infrared" / split
    xml_dir = root / "Annotations"
    if not visible_dir.exists():
        raise FileNotFoundError(f"LLVIP visible 디렉토리가 없습니다: {visible_dir}")
    if not infrared_dir.exists():
        raise FileNotFoundError(f"LLVIP infrared 디렉토리가 없습니다: {infrared_dir}")

    boxes_by_stem = _load_coco_boxes(ann_file) if ann_file else None
    target_root = output / "0"
    rgb_img_dir = target_root / "rgb" / "img"
    rgb_label_dir = target_root / "rgb" / "label"
    tir_img_dir = target_root / "tir" / "img"
    tir_label_dir = target_root / "tir" / "label"
    for path in (rgb_img_dir, rgb_label_dir, tir_img_dir, tir_label_dir):
        path.mkdir(parents=True, exist_ok=True)

    converted = 0
    for rgb_path in _iter_visible_images(visible_dir):
        stem = rgb_path.stem
        tir_path = _find_image_by_stem(infrared_dir, stem)
        if tir_path is None:
            continue

        boxes = (
            boxes_by_stem.get(stem, [])
            if boxes_by_stem is not None else
            _parse_voc_xml(xml_dir / f"{stem}.xml")
        )
        width, height = _image_size(rgb_path)
        yolo_lines = []
        for box in boxes:
            clipped = _clip_box(box, width, height)
            if clipped is not None:
                yolo_lines.append(_to_yolo_line(clipped, width, height))

        for src, dst_dir in ((rgb_path, rgb_img_dir), (tir_path, tir_img_dir)):
            dst = dst_dir / src.name
            if overwrite or not dst.exists():
                shutil.copy2(src, dst)

        label_text = "\n".join(yolo_lines)
        if label_text:
            label_text += "\n"
        for label_dir in (rgb_label_dir, tir_label_dir):
            label_path = label_dir / f"{stem}.txt"
            if overwrite or not label_path.exists():
                label_path.write_text(label_text)
        converted += 1
    return converted


def main():
    parser = argparse.ArgumentParser(description="LLVIP를 phase2_raw/pair 구조로 변환")
    parser.add_argument("--root", default="data/llvip", help="LLVIP 원본 루트")
    parser.add_argument("--split", default="train", help="visible/<split>, infrared/<split>")
    parser.add_argument("--output", default="data/phase2_raw/pair", help="출력 pair 루트")
    parser.add_argument("--ann-file", default=None, help="선택 COCO JSON annotation")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력 파일 덮어쓰기")
    args = parser.parse_args()

    count = convert_llvip(
        root=Path(args.root),
        output=Path(args.output),
        split=args.split,
        ann_file=Path(args.ann_file) if args.ann_file else None,
        overwrite=args.overwrite,
    )
    print(f"LLVIP 변환 완료: {count}개 pair")


if __name__ == "__main__":
    main()
