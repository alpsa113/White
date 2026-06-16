"""
LLVIP (Low-Light Visible-Infrared Pair) Dataset 로더

공식 디렉토리 구조:
    <root>/
        visible/train/  (또는 test/)
            xxxxxx.jpg
        infrared/train/
            xxxxxx.jpg
        Annotations/
            xxxxxx.xml  (PASCAL VOC 포맷) — 혹은 COCO JSON 제공 시 사용

COCO JSON 포맷도 지원 (ann_file 인자 전달 시).
조건벡터: 모든 이미지 야간 (illuminance=0), weather는 0~1 정규화값.
"""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from ..dataset import apply_weather_to_cond, image_to_tensor, thermal_to_tensor

LLVIP_COND = [0.0, 0.2, 0.0]  # 맑음, 가을~겨울 야간, 야간


def _parse_voc_xml(xml_path: Path) -> list[list[float]]:
    """PASCAL VOC XML → xyxy box 리스트."""
    boxes = []
    if not xml_path.exists():
        return boxes
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for obj in root.findall("object"):
            bb = obj.find("bndbox")
            if bb is None:
                continue
            x1 = float(bb.findtext("xmin", "0"))
            y1 = float(bb.findtext("ymin", "0"))
            x2 = float(bb.findtext("xmax", "0"))
            y2 = float(bb.findtext("ymax", "0"))
            boxes.append([x1, y1, x2, y2])
    except ET.ParseError:
        pass
    return boxes


class LLVIPDataset(Dataset):
    """LLVIP 야간 페어 데이터셋.

    Args:
        root:       LLVIP 루트 경로
        split:      "train" | "test"
        ann_file:   COCO JSON 어노테이션 (None이면 XML 자동 파싱)
        transforms: albumentations 기반 transform
        max_samples: 디버그용 최대 샘플 수
    """

    def __init__(
        self,
        root: str,
        split: str = "train",
        ann_file: str | None = None,
        transforms: Callable | None = None,
        max_samples: int | None = None,
    ):
        self.root = Path(root)
        self.split = split
        self.transforms = transforms
        self.samples: list[dict] = []

        self.vis_dir = self.root / "visible"  / split
        self.ir_dir  = self.root / "infrared" / split
        self.ann_dir = self.root / "Annotations"

        if ann_file and Path(ann_file).exists():
            self._load_coco(ann_file)
        else:
            self._load_xml()

        if max_samples:
            self.samples = self.samples[:max_samples]

    def _load_xml(self):
        if not self.vis_dir.exists():
            return
        for img_path in sorted(self.vis_dir.glob("*.jpg")):
            stem = img_path.stem
            xml_path = self.ann_dir / f"{stem}.xml"
            self.samples.append({
                "stem":     stem,
                "vis_path": img_path,
                "ir_path":  self.ir_dir / f"{stem}.jpg",
                "boxes":    _parse_voc_xml(xml_path),
                "labels":   None,  # XML에는 person만 있음
            })

    def _load_coco(self, ann_file: str):
        with open(ann_file) as f:
            data = json.load(f)

        id2cat = {c["id"]: c["name"] for c in data.get("categories", [])}
        img_map = {img["id"]: img for img in data["images"]}
        ann_by_img: dict = {}
        for ann in data.get("annotations", []):
            ann_by_img.setdefault(ann["image_id"], []).append(ann)

        for img_id, img_info in img_map.items():
            stem = Path(img_info["file_name"]).stem
            anns = ann_by_img.get(img_id, [])
            boxes, labels = [], []
            for ann in anns:
                x, y, w, h = ann["bbox"]
                boxes.append([x, y, x + w, y + h])
                cls_name = id2cat.get(ann["category_id"], "person")
                labels.append(0 if cls_name == "person" else 3)

            self.samples.append({
                "stem":     stem,
                "vis_path": self.vis_dir / img_info["file_name"],
                "ir_path":  self.ir_dir  / img_info["file_name"],
                "boxes":    boxes,
                "labels":   labels,
            })

    # ------------------------------------------------------------------
    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        s = self.samples[idx]

        rgb_img = None
        if s["vis_path"].exists():
            img = cv2.imread(str(s["vis_path"]))
            if img is not None:
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        thm_img = None
        if s["ir_path"].exists():
            thm_img = cv2.imread(str(s["ir_path"]), cv2.IMREAD_GRAYSCALE)

        boxes  = s["boxes"]
        labels = s["labels"] if s["labels"] is not None else [0] * len(boxes)

        weather_id = None
        if self.transforms is not None:
            base = rgb_img if rgb_img is not None else (
                np.stack([thm_img]*3, -1) if thm_img is not None
                else np.zeros((1080, 1280, 3), dtype=np.uint8)
            )
            result = self.transforms(
                image=base,
                thermal=thm_img,
                bboxes=boxes,
                labels=labels,
            )
            if rgb_img is not None:
                rgb_img = result["image"]
            if thm_img is not None:
                thm_img = result.get("thermal", thm_img)
            boxes  = [list(b) for b in result["bboxes"]]
            labels = result["labels"]
            weather_id = result.get("weather_id")

        out: dict = {}
        if rgb_img is not None:
            out["rgb"] = image_to_tensor(rgb_img)
        if thm_img is not None:
            out["thermal"] = thermal_to_tensor(thm_img)

        out["boxes"]  = (torch.tensor(boxes,  dtype=torch.float32)
                         if boxes else torch.zeros((0, 4), dtype=torch.float32))
        out["labels"] = (torch.tensor(labels, dtype=torch.int64)
                         if labels else torch.zeros((0,), dtype=torch.int64))
        out["aux_label"] = torch.tensor(0, dtype=torch.int64)  # person 라벨
        out["cond_vec"]  = apply_weather_to_cond(
            torch.tensor(LLVIP_COND, dtype=torch.float32), weather_id
        )
        out["image_id"]  = s["stem"]
        return out
