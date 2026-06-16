"""COCO/YOLO 직접 로딩용 legacy Dataset.

표준 학습 경로는 raw 데이터를 manifest로 변환한 뒤
ManifestDetectionDataset을 사용하는 방식이다. 이 모듈은 외부 데이터셋을
직접 실험할 때만 사용한다.
"""

import json
from pathlib import Path
from typing import Callable

from .dataset import (
    DEFAULT_COND,
    DEFAULT_SMALL_BOX_AREA,
    LABEL_MAP,
    ManifestDetectionDataset,
    compute_tags,
)


class LegacyDetectionDataset(ManifestDetectionDataset):
    """COCO JSON 또는 이미지 목록 기반 YOLO txt를 직접 읽는 호환 Dataset."""

    def __init__(
        self,
        root: str,
        ann_file: str,
        format: str = "coco",
        rgb_dir: str | None = None,
        thermal_dir: str | None = None,
        meta_file: str | None = None,
        transforms: Callable | None = None,
        modality: str = "pair",
        label_map: dict[str, int] | None = None,
        small_box_area: float = DEFAULT_SMALL_BOX_AREA,
        require_boxes: bool = False,
        require_labels: list[int] | None = None,
    ):
        self.root = Path(root)
        self.format = format.lower()
        self.rgb_dir = Path(rgb_dir) if rgb_dir else None
        self.thermal_dir = Path(thermal_dir) if thermal_dir else None
        self.transforms = transforms
        self.modality = modality
        self.label_map = label_map or LABEL_MAP
        self.small_box_area = small_box_area
        self.require_boxes = require_boxes
        self.require_labels = (
            {int(label) for label in require_labels}
            if require_labels is not None else None
        )

        self.meta: dict = {}
        if meta_file and Path(meta_file).exists():
            with open(meta_file) as f:
                self.meta = json.load(f)

        if self.format == "coco":
            self.samples = self._load_coco(ann_file)
        elif self.format == "yolo":
            self.samples = self._load_yolo(ann_file)
        else:
            raise ValueError(f"legacy Dataset은 coco/yolo 형식만 지원합니다: {format}")

    def _load_coco(self, ann_file: str) -> list[dict]:
        with open(ann_file) as f:
            data = json.load(f)

        id2cat = {c["id"]: c["name"] for c in data["categories"]}
        img_map: dict[int, dict] = {img["id"]: img for img in data["images"]}

        ann_by_img: dict[int, list] = {}
        for ann in data["annotations"]:
            ann_by_img.setdefault(ann["image_id"], []).append(ann)

        samples = []
        for img_id, img_info in img_map.items():
            anns = ann_by_img.get(img_id, [])
            boxes, labels = [], []
            for ann in anns:
                x, y, w, h = ann["bbox"]
                cls_name = id2cat.get(ann["category_id"], "non_target")
                if cls_name == "background":
                    continue
                cls_id = self.label_map.get(cls_name, 3)
                boxes.append([x, y, x + w, y + h])
                labels.append(cls_id)
            if not self._keep_sample(labels):
                continue
            samples.append({
                "image_id": img_id,
                "file_name": img_info["file_name"],
                "boxes": boxes,
                "labels": labels,
                "cond_vec": DEFAULT_COND,
                "tags": sorted(
                    compute_tags(boxes, labels, self.small_box_area)
                    | self._get_meta_tags(img_id)
                ),
            })
        return samples

    def _load_yolo(self, ann_file: str) -> list[dict]:
        """YOLO txt: 이미지 경로 목록 파일.

        각 이미지의 라벨 파일은 동일 경로에 .txt 확장자로 존재한다.
        라벨 형식은 class cx cy w h 정규화 좌표이다.
        """
        samples = []
        with open(ann_file) as f:
            img_paths = [line.strip() for line in f if line.strip()]

        for img_path in img_paths:
            path = Path(img_path)
            label_path = path.with_suffix(".txt")
            boxes, labels = [], []
            if label_path.exists():
                with open(label_path) as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) < 5:
                            continue
                        cls_id = int(parts[0])
                        cx, cy, w, h = map(float, parts[1:5])
                        boxes.append([cx, cy, w, h, 1.0])
                        labels.append(cls_id)
            if not self._keep_sample(labels):
                continue
            samples.append({
                "image_id": str(path.stem),
                "file_name": str(path),
                "boxes": boxes,
                "labels": labels,
                "cond_vec": DEFAULT_COND,
                "tags": sorted(self._get_meta_tags(str(path.stem))),
                "yolo_normalized": True,
            })
        return samples
