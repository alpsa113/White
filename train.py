"""
DualYOLO 학습 엔트리포인트

사용법:
    # Phase 1 시작
    python train.py --phase 1

    # Phase 2 시작 (Phase 1 체크포인트에서)
    python train.py --phase 2 --resume checkpoints/phase1/best.pt

    # Phase 3 시작
    python train.py --phase 3 --resume checkpoints/phase2/best.pt

    # 커스텀 설정
    python train.py --phase 1 --batch 16 --epochs 50 --img-size 640
"""

import argparse
from dataclasses import replace
import logging
import os
import sys
from pathlib import Path

import torch
import yaml
from torch.utils.data import DataLoader, ConcatDataset, Sampler

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent))

from model import DualYOLO
from data import (
    GenericDetectionDataset,
    KAISTDataset,
    LLVIPDataset,
    build_transforms,
)
from data.dataset import collate_fn
from training import Trainer
from training.phases import PHASE_DEFAULTS, PhaseConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
def load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_dataset(
    ds_cfg: dict,
    mode: str,
    img_size: int,
    small_box_area: float = 32 * 32,
):
    """phases.yaml 의 dataset 항목 → Dataset 객체."""
    transforms = build_transforms(mode, img_size)
    ds_type = ds_cfg["type"]

    if ds_type == "kaist":
        return KAISTDataset(
            root=ds_cfg["root"],
            split_file=ds_cfg.get("split_file"),
            transforms=transforms,
            require_person=ds_cfg.get("require_person", True),
        )
    elif ds_type == "llvip":
        return LLVIPDataset(
            root=ds_cfg["root"],
            split=ds_cfg.get("split", "train"),
            ann_file=ds_cfg.get("ann_file"),
            transforms=transforms,
        )
    else:  # generic / manifest
        return GenericDetectionDataset(
            root=ds_cfg.get("root", "."),
            ann_file=ds_cfg["ann_file"],
            format=ds_cfg.get("format", "manifest" if ds_type == "manifest" else "coco"),
            rgb_dir=ds_cfg.get("rgb_dir"),
            thermal_dir=ds_cfg.get("thermal_dir"),
            meta_file=ds_cfg.get("meta_file"),
            transforms=transforms,
            modality=ds_cfg.get("modality", "pair"),
            small_box_area=ds_cfg.get("small_box_area", small_box_area),
            require_boxes=ds_cfg.get("require_boxes", False),
            require_labels=ds_cfg.get("require_labels"),
        )


def _dataset_sample_tags(dataset) -> list[set[str]]:
    if isinstance(dataset, ConcatDataset):
        tags: list[set[str]] = []
        for ds in dataset.datasets:
            tags.extend(_dataset_sample_tags(ds))
        return tags

    if hasattr(dataset, "samples"):
        return [set(sample.get("tags", [])) for sample in dataset.samples]

    return [set() for _ in range(len(dataset))]


def _dataset_sample_modalities(dataset) -> list[str]:
    if isinstance(dataset, ConcatDataset):
        modalities: list[str] = []
        for ds in dataset.datasets:
            modalities.extend(_dataset_sample_modalities(ds))
        return modalities

    if hasattr(dataset, "samples"):
        default_modality = getattr(dataset, "modality", "pair")
        return [
            str(sample.get("modality") or default_modality)
            for sample in dataset.samples
        ]

    return ["pair" for _ in range(len(dataset))]


def validate_allowed_modalities(dataset, phase_yaml: dict, split_name: str):
    allowed = {
        "rgb": bool(phase_yaml.get("allow_rgb_only", True)),
        "thermal": bool(phase_yaml.get("allow_thm_only", True)),
        "pair": bool(phase_yaml.get("allow_pairs", True)),
    }
    modalities = _dataset_sample_modalities(dataset)
    counts: dict[str, int] = {}
    for modality in modalities:
        counts[modality] = counts.get(modality, 0) + 1

    disallowed = {
        modality: count
        for modality, count in counts.items()
        if not allowed.get(modality, False)
    }
    if disallowed:
        allowed_names = [name for name, ok in allowed.items() if ok]
        raise ValueError(
            f"{split_name} dataset contains disallowed modalities: "
            f"{disallowed}. Allowed modalities: {allowed_names}"
        )


def build_hard_negative_weights(dataset, cfg: dict) -> torch.Tensor | None:
    if not cfg or not cfg.get("enabled", False):
        return None

    tag_weights = cfg.get("weights", {})
    base_weight = float(cfg.get("base_weight", 1.0))
    weights = []
    for tags in _dataset_sample_tags(dataset):
        weight = base_weight
        for tag in tags:
            weight = max(weight, float(tag_weights.get(tag, base_weight)))
        weights.append(weight)

    if not weights or max(weights) == min(weights):
        return None

    return torch.tensor(weights, dtype=torch.double)


class ModalityHomogeneousBatchSampler(Sampler[list[int]]):
    def __init__(
        self,
        modalities: list[str],
        batch_size: int,
        drop_last: bool,
        shuffle: bool = True,
        weights: torch.Tensor | None = None,
    ):
        self.batch_size = batch_size
        self.drop_last = drop_last
        self.shuffle = shuffle
        self.weights = weights
        self.groups: dict[str, list[int]] = {}
        for idx, modality in enumerate(modalities):
            self.groups.setdefault(modality, []).append(idx)

    def __iter__(self):
        batches: list[list[int]] = []
        for indices in self.groups.values():
            if not indices:
                continue
            sample_count = self._sample_count(indices)
            ordered = self._order_group(indices, sample_count)
            for start in range(0, len(ordered), self.batch_size):
                batch = ordered[start:start + self.batch_size]
                if len(batch) == self.batch_size or (batch and not self.drop_last):
                    batches.append(batch)

        if self.shuffle and batches:
            order = torch.randperm(len(batches)).tolist()
            batches = [batches[i] for i in order]

        yield from batches

    def _sample_count(self, indices: list[int]) -> int:
        if self.weights is None:
            return len(indices)
        total_weight = float(self.weights.sum().item())
        if total_weight <= 0:
            return len(indices)
        group_weight = float(self.weights[indices].sum().item())
        return max(1, round(len(self.weights) * group_weight / total_weight))

    def _order_group(self, indices: list[int], sample_count: int) -> list[int]:
        if self.weights is not None:
            group_weights = self.weights[indices]
            if group_weights.numel() > 0:
                sampled = torch.multinomial(
                    group_weights,
                    num_samples=sample_count,
                    replacement=True,
                ).tolist()
                return [indices[i] for i in sampled]

        if self.shuffle:
            order = torch.randperm(len(indices)).tolist()
            return [indices[i] for i in order]
        return list(indices)

    def __len__(self) -> int:
        total = 0
        for indices in self.groups.values():
            sample_count = self._sample_count(indices)
            n = sample_count // self.batch_size
            if not self.drop_last and sample_count % self.batch_size:
                n += 1
            total += n
        return total


def build_loaders(
    phase_yaml: dict,
    batch_size: int,
    num_workers: int,
    img_size: int,
) -> tuple[DataLoader, DataLoader | None]:
    """학습/검증 데이터로더 생성."""
    ds_cfgs = phase_yaml.get("datasets", [])
    val_ds_cfgs = phase_yaml.get("val_datasets", [])
    small_box_area = phase_yaml.get("hard_negative_sampling", {}).get(
        "small_box_area", 32 * 32
    )

    if not ds_cfgs:
        logger.warning("datasets 항목이 없습니다. 더미 데이터로 실행합니다.")
        return _dummy_loader(batch_size), None

    datasets = []
    for cfg in ds_cfgs:
        try:
            ds = build_dataset(cfg, "train", img_size, small_box_area)
            datasets.append(ds)
            logger.info(f"  Loaded {cfg['type']}: {len(ds)} samples")
        except Exception as e:
            logger.warning(f"  Dataset load failed ({cfg.get('root', '?')}): {e}")

    if not datasets:
        logger.error("로드된 데이터셋이 없습니다.")
        return _dummy_loader(batch_size), None

    train_ds = ConcatDataset(datasets) if len(datasets) > 1 else datasets[0]
    validate_allowed_modalities(train_ds, phase_yaml, "train")
    train_weights = build_hard_negative_weights(
        train_ds,
        phase_yaml.get("hard_negative_sampling", {}),
    )
    train_batch_sampler = ModalityHomogeneousBatchSampler(
        modalities=_dataset_sample_modalities(train_ds),
        batch_size=batch_size,
        drop_last=True,
        shuffle=True,
        weights=train_weights,
    )
    train_loader = DataLoader(
        train_ds,
        batch_sampler=train_batch_sampler,
        num_workers=num_workers,
        collate_fn=collate_fn,
        pin_memory=True,
    )

    val_loader = None
    if val_ds_cfgs:
        val_datasets = []
        for cfg in val_ds_cfgs:
            try:
                ds = build_dataset(cfg, "val", img_size, small_box_area)
                val_datasets.append(ds)
                logger.info(f"  Loaded val {cfg['type']}: {len(ds)} samples")
            except Exception as e:
                logger.warning(f"  Val dataset load failed ({cfg.get('root', '?')}): {e}")
        if val_datasets:
            val_ds = ConcatDataset(val_datasets) if len(val_datasets) > 1 else val_datasets[0]
            validate_allowed_modalities(val_ds, phase_yaml, "val")
            val_batch_sampler = ModalityHomogeneousBatchSampler(
                modalities=_dataset_sample_modalities(val_ds),
                batch_size=batch_size,
                drop_last=False,
                shuffle=False,
            )
            val_loader = DataLoader(
                val_ds,
                batch_sampler=val_batch_sampler,
                num_workers=num_workers,
                collate_fn=collate_fn,
                pin_memory=True,
            )
    return train_loader, val_loader


def build_phase_config(phase: int, phase_yaml: dict, epochs: int | None) -> PhaseConfig:
    """phases.yaml 값을 PHASE_DEFAULTS 위에 얹어 PhaseConfig 생성."""
    cfg = replace(PHASE_DEFAULTS[phase])
    for key, value in phase_yaml.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    if epochs:
        cfg.max_epochs = epochs
    return cfg


def _dummy_loader(batch_size: int) -> DataLoader:
    """데이터 없을 때 구조 확인용 더미 로더."""
    from torch.utils.data import TensorDataset

    class DummyDataset(torch.utils.data.Dataset):
        def __len__(self): return 32
        def __getitem__(self, _):
            return {
                "rgb":      torch.randn(3, 640, 640),
                "thermal":  torch.randn(1, 640, 640),
                "cond_vec": torch.tensor([0.0, 0.5, 1.0], dtype=torch.float32),
                "boxes":    torch.zeros(2, 4),
                "labels":   torch.zeros(2, dtype=torch.int64),
                "aux_label": torch.tensor(0, dtype=torch.int64),
            }

    return DataLoader(
        DummyDataset(), batch_size=batch_size,
        collate_fn=collate_fn, drop_last=True,
    )


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="DualYOLO Training")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--resume", type=str, default=None,
                        help="이전 페이즈 체크포인트 경로")
    parser.add_argument("--model-cfg", type=str,
                        default="configs/model.yaml")
    parser.add_argument("--phase-cfg", type=str,
                        default="configs/phases.yaml")
    parser.add_argument("--save-dir", type=str, default="checkpoints")
    parser.add_argument("--batch",    type=int, default=None)
    parser.add_argument("--epochs",   type=int, default=None)
    parser.add_argument("--img-size", type=int, default=640)
    parser.add_argument("--device",   type=str, default=None)
    parser.add_argument("--no-amp",   action="store_true")
    args = parser.parse_args()

    # ── 설정 로드 ──────────────────────────────────────────────────
    model_cfg   = load_yaml(args.model_cfg)
    phases_yaml = load_yaml(args.phase_cfg)
    phase_yaml  = phases_yaml[f"phase{args.phase}"]

    phase_cfg = build_phase_config(args.phase, phase_yaml, args.epochs)

    m_cfg = model_cfg["model"]
    t_cfg = model_cfg["training"]
    batch_size  = args.batch or t_cfg.get("batch_size", 8)
    grad_accum_steps = t_cfg.get("grad_accum_steps", 1)
    num_workers = t_cfg.get("num_workers", 4)
    img_size    = args.img_size

    logger.info(
        f"Phase {args.phase} | batch={batch_size} | "
        f"accum={grad_accum_steps} | epochs={phase_cfg.max_epochs} | img={img_size}"
    )

    # ── 모델 ───────────────────────────────────────────────────────
    model = DualYOLO(
        fusion_dim=m_cfg.get("fusion_dim", 256),
        fpn_dim=m_cfg.get("fpn_dim", 256),
        cond_dim=m_cfg.get("cond_dim", 3),
        backbone_cfg=m_cfg.get("backbone", {}),
    )
    logger.info(
        f"Model params: {sum(p.numel() for p in model.parameters()):,}"
    )

    # ── 데이터 ─────────────────────────────────────────────────────
    train_loader, val_loader = build_loaders(
        phase_yaml, batch_size, num_workers, img_size
    )
    logger.info(f"Train batches: {len(train_loader)}")
    if val_loader is not None:
        logger.info(f"Val batches: {len(val_loader)}")

    # ── Trainer ────────────────────────────────────────────────────
    trainer = Trainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        phase=args.phase,
        cfg=phase_cfg,
        save_dir=args.save_dir,
        device=args.device,
        amp=not args.no_amp,
        grad_accum_steps=grad_accum_steps,
    )

    if args.resume:
        trainer.load_checkpoint(args.resume)

    trainer.train()


if __name__ == "__main__":
    main()
