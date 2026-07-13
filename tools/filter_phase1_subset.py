#!/usr/bin/env python3
"""phase1_raw에서 품질 필터를 통과한 축소 학습셋을 생성.

원본 데이터는 수정하지 않고, 선택된 이미지와 라벨만 새 디렉토리로 복사한다.
기본 목표 수량은 1차 본학습 비용 절감안에 맞춘다.
ForestPersons는 변환 스크립트에서 수량을 따로 지정하므로 여기서는 제외한다.

기본 출력 구조:
    data/phase1_raw_filtered/single/{class}/{rgb|tir}/img
    data/phase1_raw_filtered/single/{class}/{rgb|tir}/label
"""

from __future__ import annotations

import argparse
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class Sample:
    image: Path
    label: Path
    width: int
    height: int
    min_area_ratio: float
    max_area_ratio: float
    min_box_width_ratio: float
    min_box_height_ratio: float
    blur_score: float
    mean_brightness: float


@dataclass(frozen=True)
class SelectionPlan:
    name: str
    class_id: int
    modality: str
    target_count: int
    prefix: str
    include_prefixes: tuple[str, ...] = ()
    exclude_prefixes: tuple[str, ...] = ()


DEFAULT_PLANS = [
    SelectionPlan("person_rgb_raw", 0, "rgb", 7000, "p1_c0_rgb_raw", exclude_prefixes=("fp_",)),
    SelectionPlan("person_tir", 0, "tir", 11000, "p1_c0_tir"),
    SelectionPlan("boar_rgb", 1, "rgb", 5000, "p1_c1_rgb"),
    SelectionPlan("boar_tir", 1, "tir", 5000, "p1_c1_tir"),
    SelectionPlan("deer_rgb", 2, "rgb", 5000, "p1_c2_rgb"),
    SelectionPlan("deer_tir", 2, "tir", 5000, "p1_c2_tir"),
    SelectionPlan("non_target_rgb", 3, "rgb", 1000, "p1_c3_rgb"),
]


def _iter_images(img_dir: Path) -> list[Path]:
    if not img_dir.exists():
        return []
    return sorted(
        path
        for path in img_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def _read_yolo_label(label_path: Path) -> list[tuple[int, float, float, float, float]]:
    rows = []
    for line in label_path.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        cls, cx, cy, w, h = parts[:5]
        try:
            rows.append((int(float(cls)), float(cx), float(cy), float(w), float(h)))
        except ValueError:
            continue
    return rows


def _is_prefix_match(stem: str, prefixes: tuple[str, ...]) -> bool:
    return bool(prefixes) and any(stem.startswith(prefix) for prefix in prefixes)


def _image_stats(image_path: Path, modality: str) -> tuple[int, int, float, float] | None:
    if cv2 is None:
        raise RuntimeError("opencv-python이 필요합니다. requirements.txt 설치를 확인하세요.")
    flag = cv2.IMREAD_GRAYSCALE if modality == "tir" else cv2.IMREAD_COLOR
    image = cv2.imread(str(image_path), flag)
    if image is None:
        return None
    height, width = image.shape[:2]
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_brightness = float(gray.mean())
    return width, height, blur_score, mean_brightness


def _passes_label_filter(
    labels: list[tuple[int, float, float, float, float]],
    class_id: int,
    min_area_ratio: float,
    max_area_ratio: float,
    min_width_ratio: float,
    min_height_ratio: float,
) -> tuple[bool, dict[str, float]]:
    if not labels:
        return False, {}

    class_rows = [row for row in labels if row[0] == class_id]
    if not class_rows:
        return False, {}

    area_ratios = []
    width_ratios = []
    height_ratios = []
    for _, cx, cy, w, h in class_rows:
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            return False, {}
        if w <= 0.0 or h <= 0.0 or w > 1.0 or h > 1.0:
            return False, {}
        area = w * h
        area_ratios.append(area)
        width_ratios.append(w)
        height_ratios.append(h)

    if max(area_ratios) < min_area_ratio:
        return False, {}
    if min(area_ratios) > max_area_ratio:
        return False, {}
    if max(width_ratios) < min_width_ratio:
        return False, {}
    if max(height_ratios) < min_height_ratio:
        return False, {}

    return True, {
        "min_area_ratio": min(area_ratios),
        "max_area_ratio": max(area_ratios),
        "min_box_width_ratio": min(width_ratios),
        "min_box_height_ratio": min(height_ratios),
    }


def _collect_candidates(plan: SelectionPlan, args: argparse.Namespace) -> tuple[list[Sample], dict[str, int]]:
    src_base = Path(args.source_root) / "single" / str(plan.class_id) / plan.modality
    img_dir = src_base / "img"
    label_dir = src_base / "label"

    stats = {
        "images": 0,
        "missing_label": 0,
        "prefix_filtered": 0,
        "bad_label": 0,
        "unreadable": 0,
        "small_resolution": 0,
        "dark_or_bright": 0,
        "blurred": 0,
        "kept": 0,
    }
    kept: list[Sample] = []

    for image_path in _iter_images(img_dir):
        stats["images"] += 1
        stem = image_path.stem
        if plan.include_prefixes and not _is_prefix_match(stem, plan.include_prefixes):
            stats["prefix_filtered"] += 1
            continue
        if _is_prefix_match(stem, plan.exclude_prefixes):
            stats["prefix_filtered"] += 1
            continue

        label_path = label_dir / f"{stem}.txt"
        if not label_path.exists():
            stats["missing_label"] += 1
            continue

        labels = _read_yolo_label(label_path)
        ok, label_stats = _passes_label_filter(
            labels=labels,
            class_id=plan.class_id,
            min_area_ratio=args.min_area_ratio,
            max_area_ratio=args.max_area_ratio,
            min_width_ratio=args.min_width_ratio,
            min_height_ratio=args.min_height_ratio,
        )
        if not ok:
            stats["bad_label"] += 1
            continue

        if args.skip_image_quality:
            width = height = 0
            blur_score = mean_brightness = 0.0
        else:
            image_stats = _image_stats(image_path, plan.modality)
            if image_stats is None:
                stats["unreadable"] += 1
                continue
            width, height, blur_score, mean_brightness = image_stats
            if width < args.min_width or height < args.min_height:
                stats["small_resolution"] += 1
                continue
            if mean_brightness < args.min_brightness or mean_brightness > args.max_brightness:
                stats["dark_or_bright"] += 1
                continue
            if blur_score < args.min_blur:
                stats["blurred"] += 1
                continue

        kept.append(
            Sample(
                image=image_path,
                label=label_path,
                width=width,
                height=height,
                min_area_ratio=label_stats["min_area_ratio"],
                max_area_ratio=label_stats["max_area_ratio"],
                min_box_width_ratio=label_stats["min_box_width_ratio"],
                min_box_height_ratio=label_stats["min_box_height_ratio"],
                blur_score=blur_score,
                mean_brightness=mean_brightness,
            )
        )

    stats["kept"] = len(kept)
    return kept, stats


def _quality_key(sample: Sample) -> tuple[float, float, float]:
    # phase1은 객체 특징 학습이 목적이므로 너무 작은 객체보다 중간 크기 객체를 우선한다.
    target_area = 0.08
    area_score = -abs(sample.max_area_ratio - target_area)
    blur_score = min(sample.blur_score, 500.0)
    resolution_score = min(sample.width * sample.height, 1920 * 1080)
    return area_score, blur_score, float(resolution_score)


def _select_samples(samples: list[Sample], count: int, rng: random.Random) -> list[Sample]:
    if count >= len(samples):
        return list(samples)

    ranked = sorted(samples, key=_quality_key, reverse=True)
    top_pool_size = min(len(ranked), max(count * 2, count))
    top_pool = ranked[:top_pool_size]
    selected = rng.sample(top_pool, count)
    return sorted(selected, key=lambda sample: sample.image.name)


def _copy_samples(
    samples: list[Sample],
    plan: SelectionPlan,
    target_root: Path,
    overwrite: bool,
) -> None:
    dst_base = target_root / "single" / str(plan.class_id) / plan.modality
    dst_img_dir = dst_base / "img"
    dst_label_dir = dst_base / "label"
    dst_img_dir.mkdir(parents=True, exist_ok=True)
    dst_label_dir.mkdir(parents=True, exist_ok=True)

    for index, sample in enumerate(samples):
        stem = f"{plan.prefix}_{index:06d}"
        dst_image = dst_img_dir / f"{stem}{sample.image.suffix.lower()}"
        dst_label = dst_label_dir / f"{stem}.txt"
        if not overwrite and (dst_image.exists() or dst_label.exists()):
            raise FileExistsError(f"출력 파일이 이미 있습니다: {dst_image}")
        shutil.copy2(sample.image, dst_image)
        shutil.copy2(sample.label, dst_label)


def _print_plan_result(plan: SelectionPlan, stats: dict[str, int], selected_count: int) -> None:
    shortage = max(0, plan.target_count - selected_count)
    shortage_text = f", 부족={shortage}" if shortage else ""
    print(
        f"{plan.name}: 원본={stats['images']}, 후보={stats['kept']}, "
        f"선택={selected_count}, 목표={plan.target_count}{shortage_text}"
    )
    print(
        "  제외: "
        f"prefix={stats['prefix_filtered']}, label없음={stats['missing_label']}, "
        f"label필터={stats['bad_label']}, 읽기실패={stats['unreadable']}, "
        f"저해상도={stats['small_resolution']}, 밝기={stats['dark_or_bright']}, "
        f"blur={stats['blurred']}"
    )


def build_phase1_subset(args: argparse.Namespace) -> None:
    rng = random.Random(args.seed)
    target_root = Path(args.target_root)
    print(f"phase1 subset 생성: {args.source_root} -> {target_root}")
    print(f"dry_run={args.dry_run}, seed={args.seed}")

    total_selected = 0
    for plan in DEFAULT_PLANS:
        candidates, stats = _collect_candidates(plan, args)
        selected = _select_samples(candidates, plan.target_count, rng)
        total_selected += len(selected)
        _print_plan_result(plan, stats, len(selected))
        if not args.dry_run:
            _copy_samples(selected, plan, target_root, args.overwrite)

    print(f"\n총 선택 샘플: {total_selected}")
    if args.dry_run:
        print("dry-run 모드라 실제 파일은 복사하지 않았습니다.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="phase1_raw 품질 필터링 subset 생성")
    parser.add_argument("--source-root", default="data/phase1_raw", help="원본 phase1_raw 루트")
    parser.add_argument("--target-root", default="data/phase1_raw_filtered", help="출력 phase1_raw 루트")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="복사 없이 후보 수량만 확인")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력 파일 덮어쓰기")
    parser.add_argument(
        "--skip-image-quality",
        action="store_true",
        help="이미지를 읽지 않고 라벨/bbox 기준만으로 빠르게 필터링",
    )

    parser.add_argument("--min-area-ratio", type=float, default=0.002, help="최소 bbox 면적 비율")
    parser.add_argument("--max-area-ratio", type=float, default=0.65, help="최대 bbox 면적 비율")
    parser.add_argument("--min-width-ratio", type=float, default=0.01, help="최소 bbox 너비 비율")
    parser.add_argument("--min-height-ratio", type=float, default=0.03, help="최소 bbox 높이 비율")

    parser.add_argument("--min-width", type=int, default=160, help="최소 이미지 너비")
    parser.add_argument("--min-height", type=int, default=160, help="최소 이미지 높이")
    parser.add_argument("--min-blur", type=float, default=8.0, help="Laplacian blur score 하한")
    parser.add_argument("--min-brightness", type=float, default=3.0, help="평균 밝기 하한")
    parser.add_argument("--max-brightness", type=float, default=252.0, help="평균 밝기 상한")
    return parser.parse_args()


def main() -> None:
    build_phase1_subset(parse_args())


if __name__ == "__main__":
    main()
