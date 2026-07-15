#!/usr/bin/env python3
"""TIR person 후보 데이터를 bbox 크기 구간별로 phase3 raw 구조에 복사."""

from __future__ import annotations

import argparse
import random
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
PERSON_CLASS_ID = 0


@dataclass
class Candidate:
    image_path: Path
    label_path: Path
    bucket: str
    max_area: float
    box_count: int


def _find_image(img_dir: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        path = img_dir / f"{stem}{ext}"
        if path.exists():
            return path
    return None


def _bucket_name(area: float) -> str:
    if area < 0.0005:
        return "lt_0_05"
    if area < 0.0025:
        return "0_05_0_25"
    if area < 0.01:
        return "0_25_1"
    if area < 0.05:
        return "1_5"
    if area < 0.15:
        return "5_15"
    if area < 0.25:
        return "15_25"
    return "gt_25"


def _read_candidate(label_path: Path, image_path: Path) -> Candidate | None:
    max_area = 0.0
    box_count = 0
    for line in label_path.read_text(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cls_id = int(float(parts[0]))
            box_w = float(parts[3])
            box_h = float(parts[4])
        except ValueError:
            continue
        if cls_id != PERSON_CLASS_ID:
            continue
        area = box_w * box_h
        if area <= 0:
            continue
        max_area = max(max_area, area)
        box_count += 1

    if box_count == 0:
        return None

    return Candidate(
        image_path=image_path,
        label_path=label_path,
        bucket=_bucket_name(max_area),
        max_area=max_area,
        box_count=box_count,
    )


def _load_candidates(source: Path) -> list[Candidate]:
    img_dir = source / "img"
    label_dir = source / "label"
    if not img_dir.exists():
        raise FileNotFoundError(f"이미지 디렉토리가 없습니다: {img_dir}")
    if not label_dir.exists():
        raise FileNotFoundError(f"라벨 디렉토리가 없습니다: {label_dir}")

    candidates = []
    missing_images = 0
    for label_path in sorted(label_dir.glob("*.txt")):
        image_path = _find_image(img_dir, label_path.stem)
        if image_path is None:
            missing_images += 1
            continue
        candidate = _read_candidate(label_path, image_path)
        if candidate is not None:
            candidates.append(candidate)

    if missing_images:
        print(f"이미지가 없어 제외된 라벨: {missing_images}개")
    return candidates


def _sample_bucket(
    candidates: list[Candidate],
    bucket: str,
    count: int,
    rng: random.Random,
) -> list[Candidate]:
    if count <= 0:
        return []
    pool = [candidate for candidate in candidates if candidate.bucket == bucket]
    rng.shuffle(pool)
    return pool[: min(count, len(pool))]


def _copy_selected(
    selected: list[Candidate],
    target: Path,
    prefix: str,
    overwrite: bool,
    dry_run: bool,
) -> None:
    img_dir = target / "img"
    label_dir = target / "label"
    if not dry_run:
        img_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)

    for idx, candidate in enumerate(selected):
        image_suffix = candidate.image_path.suffix.lower()
        out_stem = f"{prefix}_{idx:06d}"
        dst_image = img_dir / f"{out_stem}{image_suffix}"
        dst_label = label_dir / f"{out_stem}.txt"

        if dry_run:
            continue

        if not overwrite and (dst_image.exists() or dst_label.exists()):
            raise FileExistsError(f"출력 파일이 이미 있습니다: {dst_image}")

        shutil.copy2(candidate.image_path, dst_image)
        shutil.copy2(candidate.label_path, dst_label)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TIR person 후보를 bbox 크기 구간별로 복사")
    parser.add_argument("--source", type=Path, required=True, help="img/label을 포함한 후보 루트")
    parser.add_argument("--target", type=Path, required=True, help="복사 대상 modality 루트")
    parser.add_argument("--prefix", default="tir_add_p3_person", help="출력 파일 prefix")
    parser.add_argument("--count-0-25-1", type=int, default=0, help="0.25~1% 구간 복사 수")
    parser.add_argument("--count-1-5", type=int, default=1200, help="1~5% 구간 복사 수")
    parser.add_argument("--count-5-15", type=int, default=1300, help="5~15% 구간 복사 수")
    parser.add_argument("--count-15-25", type=int, default=300, help="15~25% 구간 복사 수")
    parser.add_argument("--count-gt-25", type=int, default=0, help="25% 초과 구간 복사 수")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="파일 복사 없이 후보/선택 분포만 출력")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력 파일 덮어쓰기")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    candidates = _load_candidates(args.source)

    requested = {
        "0_25_1": args.count_0_25_1,
        "1_5": args.count_1_5,
        "5_15": args.count_5_15,
        "15_25": args.count_15_25,
        "gt_25": args.count_gt_25,
    }

    selected = []
    for bucket, count in requested.items():
        selected.extend(_sample_bucket(candidates, bucket, count, rng))

    candidate_counts = Counter(candidate.bucket for candidate in candidates)
    selected_counts = Counter(candidate.bucket for candidate in selected)

    print(f"후보 전체: {len(candidates)}개")
    print("후보 분포:")
    for bucket in ["lt_0_05", "0_05_0_25", "0_25_1", "1_5", "5_15", "15_25", "gt_25"]:
        print(f"  {bucket}: {candidate_counts[bucket]}")

    print(f"\n선택 전체: {len(selected)}개")
    print("선택 분포:")
    for bucket in ["0_25_1", "1_5", "5_15", "15_25", "gt_25"]:
        print(f"  {bucket}: {selected_counts[bucket]} / 요청 {requested.get(bucket, 0)}")

    if args.dry_run:
        print("\ndry-run 모드라 실제 파일은 복사하지 않았습니다.")
        return

    _copy_selected(
        selected=selected,
        target=args.target,
        prefix=args.prefix,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    print(f"\n복사 완료: {len(selected)}개")
    print(f"대상: {args.target}")


if __name__ == "__main__":
    main()
