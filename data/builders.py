import logging

import torch
from torch.utils.data import ConcatDataset, DataLoader

from .dataset import ManifestDetectionDataset, collate_fn
from .legacy_detection import LegacyDetectionDataset
from .samplers import (
    ModalityHomogeneousBatchSampler,
    build_hard_negative_weights,
    dataset_sample_modalities,
    validate_allowed_modalities,
)
from .transforms import build_transforms

logger = logging.getLogger(__name__)


def build_dataset(
    ds_cfg: dict,
    mode: str,
    img_size: int,
    small_box_area: float = 32 * 32,
):
    """phases.yaml의 데이터셋 항목을 Dataset 객체로 변환."""
    transforms = build_transforms(mode, img_size)
    ds_type = ds_cfg["type"]

    if ds_type == "manifest" or ds_cfg.get("format") == "manifest":
        return ManifestDetectionDataset(
            root=ds_cfg.get("root", "."),
            ann_file=ds_cfg["ann_file"],
            rgb_dir=ds_cfg.get("rgb_dir"),
            thermal_dir=ds_cfg.get("thermal_dir"),
            meta_file=ds_cfg.get("meta_file"),
            transforms=transforms,
            modality=ds_cfg.get("modality", "pair"),
            small_box_area=ds_cfg.get("small_box_area", small_box_area),
            require_boxes=ds_cfg.get("require_boxes", False),
            require_labels=ds_cfg.get("require_labels"),
        )

    return LegacyDetectionDataset(
        root=ds_cfg.get("root", "."),
        ann_file=ds_cfg["ann_file"],
        format=ds_cfg.get("format", "coco"),
        rgb_dir=ds_cfg.get("rgb_dir"),
        thermal_dir=ds_cfg.get("thermal_dir"),
        meta_file=ds_cfg.get("meta_file"),
        transforms=transforms,
        modality=ds_cfg.get("modality", "pair"),
        small_box_area=ds_cfg.get("small_box_area", small_box_area),
        require_boxes=ds_cfg.get("require_boxes", False),
        require_labels=ds_cfg.get("require_labels"),
    )


def _dummy_loader(batch_size: int) -> DataLoader:
    """명시적으로 요청된 구조 확인용 더미 로더."""

    class DummyDataset(torch.utils.data.Dataset):
        def __len__(self):
            return 32

        def __getitem__(self, _):
            return {
                "rgb": torch.randn(3, 640, 640),
                "thermal": torch.randn(1, 640, 640),
                "cond_vec": torch.tensor([0.0, 0.5, 1.0], dtype=torch.float32),
                "boxes": torch.zeros(2, 4),
                "labels": torch.zeros(2, dtype=torch.int64),
                "aux_label": torch.tensor(0, dtype=torch.int64),
            }

    return DataLoader(
        DummyDataset(),
        batch_size=batch_size,
        collate_fn=collate_fn,
        drop_last=True,
    )


def _load_dataset_group(
    ds_cfgs: list[dict],
    mode: str,
    img_size: int,
    small_box_area: float,
    log_prefix: str,
):
    datasets = []
    errors = []
    for cfg in ds_cfgs:
        try:
            ds = build_dataset(cfg, mode, img_size, small_box_area)
            datasets.append(ds)
            logger.info(f"  {log_prefix}{cfg['type']} 로드 완료: {len(ds)}개 샘플")
        except Exception as e:
            source = cfg.get("ann_file") or cfg.get("root", "?")
            errors.append(f"{source}: {e}")
            logger.error(f"  {log_prefix}데이터셋 로드 실패({source}): {e}")
    if errors:
        details = "\n".join(f"- {error}" for error in errors)
        raise RuntimeError(f"{log_prefix}데이터셋 로드 중 오류가 발생했습니다.\n{details}")
    return ConcatDataset(datasets) if len(datasets) > 1 else datasets[0]


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
    allow_dummy = phase_yaml.get("allow_dummy_data", False)

    if not ds_cfgs:
        if allow_dummy:
            logger.warning("데이터셋 항목이 없습니다. 더미 데이터로 실행합니다.")
            return _dummy_loader(batch_size), None
        raise ValueError(
            "학습 데이터셋 항목이 없습니다. 테스트용 더미 데이터가 필요하면 "
            "phase 설정에 allow_dummy_data: true를 명시하세요."
        )

    train_ds = _load_dataset_group(ds_cfgs, "train", img_size, small_box_area, "")

    validate_allowed_modalities(train_ds, phase_yaml, "train")
    train_weights = build_hard_negative_weights(
        train_ds,
        phase_yaml.get("hard_negative_sampling", {}),
    )
    train_batch_sampler = ModalityHomogeneousBatchSampler(
        modalities=dataset_sample_modalities(train_ds),
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
        pin_memory=torch.cuda.is_available(),
    )

    val_loader = None
    if val_ds_cfgs:
        val_ds = _load_dataset_group(
            val_ds_cfgs,
            "val",
            img_size,
            small_box_area,
            "검증 ",
        )
        validate_allowed_modalities(val_ds, phase_yaml, "val")
        val_batch_sampler = ModalityHomogeneousBatchSampler(
            modalities=dataset_sample_modalities(val_ds),
            batch_size=batch_size,
            drop_last=False,
            shuffle=False,
        )
        val_loader = DataLoader(
            val_ds,
            batch_sampler=val_batch_sampler,
            num_workers=num_workers,
            collate_fn=collate_fn,
            pin_memory=torch.cuda.is_available(),
        )
    return train_loader, val_loader
