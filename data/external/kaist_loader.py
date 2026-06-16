"""
KAIST Multispectral Pedestrian Dataset 로더

디렉토리 구조 (공식 배포 기준):
    <root>/
        images/
            set00/V000/visible/I00000.jpg
            set00/V000/lwir/I00000.jpg
        annotations/
            set00/V000/I00000.txt   (person x y w h 형식)

조건벡터 주·야간 자동 설정:
    set00~set05: 낮 (illuminance=1)
    set06~set11: 밤 (illuminance=0)
"""

import re
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

from ..dataset import apply_weather_to_cond, image_to_tensor, thermal_to_tensor

KAIST_LABEL_MAP = {"person": 0}
NIGHT_SETS = {f"set{i:02d}" for i in range(6, 12)}


def _parse_kaist_ann(ann_path: Path) -> list[list[float]]:
    """KAIST annotation .txt → xyxy box 리스트."""
    boxes = []
    if not ann_path.exists():
        return boxes
    with open(ann_path) as f:
        for line in f:
            parts = line.strip().split()
            if not parts or parts[0] != "person":
                continue
            try:
                x, y, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                boxes.append([x, y, x + w, y + h])
            except (ValueError, IndexError):
                continue
    return boxes


def _build_cond_vec(set_name: str) -> list[float]:
    """set 번호에서 조건벡터 자동 생성."""
    is_night = set_name in NIGHT_SETS
    return [
        0.0,                  # weather: 맑음 (weather_id / 3.0)
        0.3,                  # temp_c: 한국 사계절 혼합 매크로값
        0.0 if is_night else 1.0,  # illuminance
    ]


class KAISTDataset(Dataset):
    """KAIST 다중스펙트럼 보행자 페어 데이터셋.

    Args:
        root:        KAIST 루트 경로
        split_file:  사용할 split 파일 (공식 train/test split .txt)
                     None이면 전체 탐색
        transforms:  albumentations 기반 transform
        max_samples: 디버그용 최대 샘플 수
    """

    def __init__(
        self,
        root: str,
        split_file: str | None = None,
        transforms: Callable | None = None,
        max_samples: int | None = None,
        require_person: bool = True,
    ):
        self.root = Path(root)
        self.transforms = transforms
        self.require_person = require_person
        self.samples: list[dict] = []

        if split_file and Path(split_file).exists():
            self._load_from_split(split_file)
        else:
            self._load_all()

        if max_samples:
            self.samples = self.samples[:max_samples]

    def _load_from_split(self, split_file: str):
        """공식 split .txt: 'set00/V000/I00000' 형식."""
        with open(split_file) as f:
            entries = [l.strip() for l in f if l.strip()]

        for entry in entries:
            parts = entry.split("/")
            if len(parts) < 3:
                continue
            set_name, vid, img_id = parts[0], parts[1], parts[2]
            self._add_sample(set_name, vid, img_id)

    def _load_all(self):
        img_root = self.root / "images"
        for set_dir in sorted(img_root.iterdir()):
            if not set_dir.is_dir():
                continue
            for vid_dir in sorted(set_dir.iterdir()):
                if not vid_dir.is_dir():
                    continue
                vis_dir = vid_dir / "visible"
                if not vis_dir.exists():
                    continue
                for img_path in sorted(vis_dir.glob("*.jpg")):
                    self._add_sample(set_dir.name, vid_dir.name, img_path.stem)

    def _add_sample(self, set_name: str, vid: str, img_id: str):
        rgb_path  = self.root / "images" / set_name / vid / "visible" / f"{img_id}.jpg"
        thm_path  = self.root / "images" / set_name / vid / "lwir"    / f"{img_id}.jpg"
        ann_path  = self.root / "annotations" / set_name / vid / f"{img_id}.txt"
        if not rgb_path.exists() and not thm_path.exists():
            return
        boxes = _parse_kaist_ann(ann_path)
        if self.require_person and not boxes:
            return
        self.samples.append({
            "rgb_path":  rgb_path,
            "thm_path":  thm_path,
            "ann_path":  ann_path,
            "boxes":     boxes,
            "set_name":  set_name,
            "cond_vec":  _build_cond_vec(set_name),
            "image_id":  f"{set_name}_{vid}_{img_id}",
        })

    # ------------------------------------------------------------------
    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        s = self.samples[idx]

        rgb_img = None
        if s["rgb_path"].exists():
            img = cv2.imread(str(s["rgb_path"]))
            if img is not None:
                rgb_img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        thm_img = None
        if s["thm_path"].exists():
            thm_img = cv2.imread(str(s["thm_path"]), cv2.IMREAD_GRAYSCALE)

        boxes  = [list(box) for box in s["boxes"]]
        labels = [0] * len(boxes)  # 모두 person

        # transform 적용
        weather_id = None
        if self.transforms is not None:
            transform_thermal = (
                np.stack([thm_img] * 3, axis=-1)
                if thm_img is not None and thm_img.ndim == 2 else thm_img
            )
            base = rgb_img if rgb_img is not None else (
                transform_thermal if transform_thermal is not None
                else np.zeros((512, 640, 3), dtype=np.uint8)
            )
            result = self.transforms(
                image=base,
                thermal=transform_thermal,
                bboxes=boxes,
                labels=labels,
            )
            if rgb_img is not None:
                rgb_img = result["image"]
            if thm_img is not None:
                thm_img = result.get("thermal", thm_img)
                if thm_img.ndim == 3:
                    thm_img = thm_img[..., 0]
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
            torch.tensor(s["cond_vec"], dtype=torch.float32), weather_id
        )
        out["image_id"]  = s["image_id"]
        return out
