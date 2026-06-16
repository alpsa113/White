"""
Manifest 기반 탐지 데이터셋.

배치 키:
    rgb:       [3, H, W] float32   (없으면 키 없음)
    thermal:   [1, H, W] float32   (없으면 키 없음)
    cond_vec:  [3] float32          (메타데이터 없으면 DEFAULT_COND)
    boxes:     [N, 4] float32 xyxy
    labels:    [N] int64
    aux_label: int64  (이미지 레벨 dominant target class, 없으면 -1)

조건벡터 3차원 정의 (index):
    0: weather  (MLP 입력값: weather_id / 3.0)
    1: temp_c   (정규화된 기온)
    2: illuminance (0=야간, 1=주간)  — fusion_reg_loss 기준
"""

import json
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

# 클래스명 → ID 매핑 (non_target은 박스가 있는 비대상 객체)
LABEL_MAP = {"person": 0, "boar": 1, "deer": 2, "non_target": 3}
DEFAULT_COND = [0.0, 0.5, 1.0]  # 맑음, 중간 기온, 주간
DEFAULT_SMALL_BOX_AREA = 32 * 32


def normalize_cond_vec(vec) -> list[float]:
    """조건벡터를 아키텍처 v0.5.3의 3차원 MLP 입력으로 정규화."""
    if isinstance(vec, dict):
        weather = float(vec.get("weather", 0.0)) / 3.0
        temp_c = vec.get("temp_c", 0.5)
        illuminance = vec.get("illuminance", 1.0)
    else:
        vals = list(vec)
        if len(vals) >= 3:
            weather, temp_c, illuminance = vals[:3]
        else:
            weather, temp_c, illuminance = DEFAULT_COND

    weather = float(weather)
    return [
        max(0.0, min(1.0, weather)),
        max(0.0, min(1.0, float(temp_c))),
        0.0 if float(illuminance) <= 0.0 else 1.0,
    ]


def dominant_aux_label(labels) -> int:
    counts = [0, 0, 0]
    for lbl in labels:
        lbl = int(lbl)
        if 0 <= lbl < 3:
            counts[lbl] += 1
    return counts.index(max(counts)) if max(counts) > 0 else -1


def compute_tags(
    boxes,
    labels,
    small_box_area: float = DEFAULT_SMALL_BOX_AREA,
) -> set[str]:
    tags: set[str] = set()
    for box, label in zip(boxes, labels):
        x1, y1, x2, y2 = box[:4]
        area = max(0.0, float(x2) - float(x1)) * max(0.0, float(y2) - float(y1))
        label = int(label)
        if label == 0 and area < small_box_area:
            tags.add("distant_person")
        if label == 3:
            tags.add("non_target")
            if area < small_box_area:
                tags.add("small_non_target")
    return tags


def apply_weather_to_cond(cond_vec: torch.Tensor, weather_id) -> torch.Tensor:
    if weather_id is None:
        return cond_vec
    cond_vec = cond_vec.clone()
    cond_vec[0] = float(weather_id) / 3.0
    return cond_vec


def image_to_tensor(img: np.ndarray) -> torch.Tensor:
    arr = img.astype(np.float32)
    if np.issubdtype(img.dtype, np.integer):
        arr = arr / 255.0
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    return torch.from_numpy(arr.transpose(2, 0, 1))


def thermal_to_tensor(img: np.ndarray) -> torch.Tensor:
    arr = img.astype(np.float32)
    if np.issubdtype(img.dtype, np.integer):
        arr = arr / 255.0
    if arr.ndim == 3:
        arr = arr[..., 0]
    return torch.from_numpy(arr[None])


class ManifestDetectionDataset(Dataset):
    """manifest JSON을 읽는 표준 학습 데이터셋.

    Args:
        root:          데이터 루트 디렉토리
        ann_file:      어노테이션 파일 경로
            - manifest JSON: [{image/rgb, thermal, boxes, labels, ...}]
        rgb_dir:       RGB 이미지 디렉토리 (None이면 root 하위 자동 탐색)
        thermal_dir:   열화상 이미지 디렉토리 (None이면 열화상 없음)
        meta_file:     조건벡터 JSON 파일 (image_id → cond_vec 딕셔너리)
        transforms:    albumentations 기반 transform
        modality:      "rgb" | "thermal" | "pair"  — 없는 모달은 None 반환
        label_map:     클래스명 → ID 매핑 (기본: LABEL_MAP)
    """

    def __init__(
        self,
        root: str,
        ann_file: str,
        rgb_dir: str | None = None,
        thermal_dir: str | None = None,
        meta_file: str | None = None,
        transforms: Callable | None = None,
        modality: str = "pair",
        small_box_area: float = DEFAULT_SMALL_BOX_AREA,
        require_boxes: bool = False,
        require_labels: list[int] | None = None,
    ):
        self.root = Path(root)
        self.rgb_dir = Path(rgb_dir) if rgb_dir else None
        self.thermal_dir = Path(thermal_dir) if thermal_dir else None
        self.transforms = transforms
        self.modality = modality
        self.small_box_area = small_box_area
        self.require_boxes = require_boxes
        self.require_labels = (
            {int(label) for label in require_labels}
            if require_labels is not None else None
        )

        # 조건벡터 메타데이터
        self.meta: dict = {}
        if meta_file and Path(meta_file).exists():
            with open(meta_file) as f:
                self.meta = json.load(f)

        self.samples = self._load_manifest(ann_file)

    # ------------------------------------------------------------------
    def _keep_sample(self, labels) -> bool:
        if self.require_labels is not None:
            return any(int(label) in self.require_labels for label in labels)
        if self.require_boxes:
            return len(labels) > 0
        return True

    def _load_manifest(self, ann_file: str) -> list[dict]:
        with open(ann_file) as f:
            data = json.load(f)

        items = data.get("samples", data) if isinstance(data, dict) else data
        samples = []
        for idx, item in enumerate(items):
            boxes = [list(box[:4]) for box in item.get("boxes", [])]
            labels = [int(label) for label in item.get("labels", [])]
            if not self._keep_sample(labels):
                continue

            image_id = item.get("image_id") or item.get("id") or f"manifest_{idx}"
            modality = item.get("modality")
            image_path = item.get("image")
            rgb_path = item.get("rgb") or item.get("rgb_path")
            thermal_path = item.get("thermal") or item.get("thermal_path")
            if modality == "thermal" and thermal_path is None:
                thermal_path = image_path
            elif rgb_path is None:
                rgb_path = image_path
            meta_tags = set(item.get("tags", []))
            samples.append({
                "image_id": str(image_id),
                "file_name": rgb_path or thermal_path or "",
                "rgb_path": rgb_path,
                "thermal_path": thermal_path,
                "boxes": boxes,
                "labels": labels,
                "cond_vec": item.get("cond_vec", item.get("meta", DEFAULT_COND)),
                "tags": sorted(
                    meta_tags | compute_tags(boxes, labels, self.small_box_area)
                ),
                "source": item.get("source"),
                "split_group": item.get("split_group"),
                "modality": modality,
            })
        return samples

    # ------------------------------------------------------------------
    def _load_image(self, path: Path, gray: bool = False) -> np.ndarray | None:
        if not path.exists():
            return None
        flag = cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR
        img = cv2.imread(str(path), flag)
        if img is None:
            return None
        if not gray:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        return img

    def _resolve_path(self, path_value) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else self.root / path

    def _get_cond_vec(self, image_id) -> torch.Tensor:
        key = str(image_id)
        if key in self.meta:
            vec = self.meta[key]
        else:
            vec = DEFAULT_COND
        return torch.tensor(normalize_cond_vec(vec), dtype=torch.float32)

    def _get_meta_tags(self, image_id) -> set[str]:
        item = self.meta.get(str(image_id), {})
        if isinstance(item, dict):
            return set(item.get("tags", []))
        return set()

    # ------------------------------------------------------------------
    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        sample = self.samples[idx]
        img_id = sample["image_id"]
        fname = sample["file_name"]
        sample_modality = sample.get("modality") or self.modality

        # ── 이미지 로드 ──────────────────────────────────────────
        rgb_img: np.ndarray | None = None
        thm_img: np.ndarray | None = None

        if sample_modality in ("rgb", "pair"):
            if sample.get("rgb_path"):
                rgb_path = self._resolve_path(sample["rgb_path"])
            else:
                rgb_path = self.rgb_dir / fname if self.rgb_dir else self.root / fname
            rgb_img = self._load_image(rgb_path, gray=False)

        if sample_modality in ("thermal", "pair"):
            if sample.get("thermal_path"):
                thm_path = self._resolve_path(sample["thermal_path"])
                thm_img = self._load_image(thm_path, gray=True)
            elif self.thermal_dir is not None:
                thm_path = self.thermal_dir / Path(fname).name
                thm_img = self._load_image(thm_path, gray=True)

        # ── 박스 / 라벨 ──────────────────────────────────────────
        raw_boxes = sample["boxes"]
        raw_labels = sample["labels"]

        ref_img = rgb_img if rgb_img is not None else thm_img
        H, W = (ref_img.shape[:2] if ref_img is not None else (640, 640))

        boxes = []
        for b in raw_boxes:
            if sample.get("yolo_normalized"):
                cx, cy, bw, bh = b[0] * W, b[1] * H, b[2] * W, b[3] * H
                boxes.append([cx - bw/2, cy - bh/2, cx + bw/2, cy + bh/2])
            else:
                boxes.append(b[:4])

        # ── 변환 적용 ───────────────────────────────────────────
        weather_id = None
        if self.transforms is not None:
            transform_thermal = (
                np.stack([thm_img] * 3, axis=-1)
                if thm_img is not None and thm_img.ndim == 2 else thm_img
            )
            result = self.transforms(
                image=rgb_img if rgb_img is not None else (
                    np.stack([thm_img]*3, axis=-1) if thm_img is not None else
                    np.zeros((H, W, 3), dtype=np.uint8)
                ),
                thermal=transform_thermal,
                bboxes=boxes,
                labels=raw_labels,
            )
            if rgb_img is not None:
                rgb_img = result["image"]
            if thm_img is not None:
                thm_img = result.get("thermal", thm_img)
                if thm_img.ndim == 3:
                    thm_img = thm_img[..., 0]
            boxes = [list(b) for b in result["bboxes"]]
            raw_labels = result["labels"]
            weather_id = result.get("weather_id")

        # ── tensor 변환 ─────────────────────────────────────────
        out: dict = {}
        if rgb_img is not None:
            out["rgb"] = image_to_tensor(rgb_img)
        if thm_img is not None:
            out["thermal"] = thermal_to_tensor(thm_img)

        if boxes:
            out["boxes"]  = torch.tensor(boxes, dtype=torch.float32)
            out["labels"] = torch.tensor(raw_labels, dtype=torch.int64)
        else:
            out["boxes"]  = torch.zeros((0, 4), dtype=torch.float32)
            out["labels"] = torch.zeros((0,),   dtype=torch.int64)

        # 대표 대상 클래스 계산(보조 헤드용, non_target/empty는 무시)
        out["aux_label"] = torch.tensor(
            dominant_aux_label(raw_labels), dtype=torch.int64
        )

        cond_vec = (
            torch.tensor(normalize_cond_vec(sample["cond_vec"]), dtype=torch.float32)
            if "cond_vec" in sample else self._get_cond_vec(img_id)
        )
        out["cond_vec"] = apply_weather_to_cond(cond_vec, weather_id)
        out["image_id"] = img_id
        out["tags"] = sorted(
            set(sample.get("tags", []))
            | compute_tags(boxes, raw_labels, self.small_box_area)
        )

        return out


# ---------------------------------------------------------------------------
# Collate 함수
# ---------------------------------------------------------------------------

def collate_fn(batch: list[dict]) -> dict:
    """가변 길이 boxes/labels 를 리스트로 묶는 collate 함수."""
    keys = batch[0].keys()
    out: dict = {}
    for k in keys:
        vals = [b[k] for b in batch]
        if k in ("boxes", "labels"):
            out[k] = vals  # tensor 리스트
        elif isinstance(vals[0], torch.Tensor):
            try:
                out[k] = torch.stack(vals)
            except Exception:
                out[k] = vals
        else:
            out[k] = vals
    return out
