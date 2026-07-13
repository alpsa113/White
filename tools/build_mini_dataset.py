#!/usr/bin/env python3
"""기존 raw 데이터에서 미니 성능 테스트용 subset을 구성."""

from __future__ import annotations

import argparse
import random
import shutil
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class CopyPlan:
    name: str
    source: Path
    target: Path
    count: int
    requires_label: bool
    prefix: str


MINI_COPY_PLAN = [
    CopyPlan("phase1_person_rgb", Path("data/phase1_raw/single/0/rgb"), Path("data/mini_test/phase1_raw/single/0/rgb"), 1500, True, "raw_p1_c0_rgb"),
    CopyPlan("phase1_person_tir", Path("data/phase1_raw/single/0/tir"), Path("data/mini_test/phase1_raw/single/0/tir"), 2000, True, "raw_p1_c0_tir"),
    CopyPlan("phase1_boar_rgb", Path("data/phase1_raw/single/1/rgb"), Path("data/mini_test/phase1_raw/single/1/rgb"), 3000, True, "raw_p1_c1_rgb"),
    CopyPlan("phase1_boar_tir", Path("data/phase1_raw/single/1/tir"), Path("data/mini_test/phase1_raw/single/1/tir"), 2000, True, "raw_p1_c1_tir"),
    CopyPlan("phase1_deer_rgb", Path("data/phase1_raw/single/2/rgb"), Path("data/mini_test/phase1_raw/single/2/rgb"), 3000, True, "raw_p1_c2_rgb"),
    CopyPlan("phase1_deer_tir", Path("data/phase1_raw/single/2/tir"), Path("data/mini_test/phase1_raw/single/2/tir"), 1500, True, "raw_p1_c2_tir"),
    CopyPlan("phase1_non_target_rgb", Path("data/phase1_raw/single/3/rgb"), Path("data/mini_test/phase1_raw/single/3/rgb"), 1500, True, "raw_p1_c3_rgb"),
    CopyPlan("phase3_boar_rgb", Path("data/gop_raw/single/1/rgb"), Path("data/mini_test/gop_raw/single/1/rgb"), 800, True, "raw_p3_c1_rgb"),
    CopyPlan("phase3_boar_tir", Path("data/gop_raw/single/1/tir"), Path("data/mini_test/gop_raw/single/1/tir"), 1500, True, "raw_p3_c1_tir"),
    CopyPlan("phase3_deer_tir", Path("data/gop_raw/single/2/tir"), Path("data/mini_test/gop_raw/single/2/tir"), 800, True, "raw_p3_c2_tir"),
    CopyPlan("phase3_non_target_rgb", Path("data/gop_raw/single/3/rgb"), Path("data/mini_test/gop_raw/single/3/rgb"), 600, True, "raw_p3_c3_rgb"),
    CopyPlan("phase3_empty_rgb", Path("data/gop_raw/empty/rgb"), Path("data/mini_test/gop_raw/empty/rgb"), 1000, False, "raw_p3_empty_rgb"),
    CopyPlan("phase3_empty_tir", Path("data/gop_raw/empty/tir"), Path("data/mini_test/gop_raw/empty/tir"), 1000, False, "raw_p3_empty_tir"),
]


@dataclass(frozen=True)
class Sample:
    image: Path
    label: Path | None


def _iter_images(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(directory.glob(f"*{ext}"))
        images.extend(directory.glob(f"*{ext.upper()}"))
    return sorted(set(images))


def _collect_samples(plan: CopyPlan) -> list[Sample]:
    img_dir = plan.source / "img"
    label_dir = plan.source / "label"
    images = _iter_images(img_dir)

    samples = []
    for image in images:
        label = label_dir / f"{image.stem}.txt"
        if plan.requires_label and not label.exists():
            continue
        samples.append(Sample(image=image, label=label if plan.requires_label else None))
    return samples


def _copy_sample(sample: Sample, plan: CopyPlan, index: int, overwrite: bool) -> None:
    img_dir = plan.target / "img"
    img_dir.mkdir(parents=True, exist_ok=True)

    stem = f"{plan.prefix}_{index:06d}"
    dst_image = img_dir / f"{stem}{sample.image.suffix.lower()}"
    if dst_image.exists() and not overwrite:
        raise FileExistsError(f"출력 이미지가 이미 있습니다: {dst_image}")
    shutil.copy2(sample.image, dst_image)

    if sample.label is None:
        return

    label_dir = plan.target / "label"
    label_dir.mkdir(parents=True, exist_ok=True)
    dst_label = label_dir / f"{stem}.txt"
    if dst_label.exists() and not overwrite:
        raise FileExistsError(f"출력 라벨이 이미 있습니다: {dst_label}")
    shutil.copy2(sample.label, dst_label)


def _run_plan(plan: CopyPlan, rng: random.Random, overwrite: bool, dry_run: bool) -> tuple[int, int]:
    samples = _collect_samples(plan)
    selected_count = min(plan.count, len(samples))
    selected = rng.sample(samples, selected_count) if selected_count else []

    if not dry_run:
        for index, sample in enumerate(sorted(selected, key=lambda item: item.image.name)):
            _copy_sample(sample, plan, index, overwrite)

    return len(samples), selected_count


def build_mini_dataset(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    print(f"mini_test 구성 dry_run={args.dry_run}, seed={args.seed}")

    for plan in MINI_COPY_PLAN:
        available, selected = _run_plan(plan, rng, args.overwrite, args.dry_run)
        shortage = max(0, plan.count - available)
        shortage_text = f", 부족={shortage}" if shortage else ""
        print(
            f"{plan.name}: 사용 가능={available}, 선택={selected}, 목표={plan.count}"
            f"{shortage_text} -> {plan.target}"
        )

    if args.dry_run:
        print("dry-run 모드라 실제 파일은 복사하지 않았습니다.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="기존 raw 데이터에서 mini_test subset 구성")
    parser.add_argument("--seed", type=int, default=42, help="샘플링 seed")
    parser.add_argument("--dry-run", action="store_true", help="실제 복사 없이 가능 개수만 확인")
    parser.add_argument("--overwrite", action="store_true", help="기존 mini_test 파일 덮어쓰기")
    return parser.parse_args()


def main() -> None:
    build_mini_dataset(parse_args())


if __name__ == "__main__":
    main()
