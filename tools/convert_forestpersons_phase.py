#!/usr/bin/env python3
"""ForestPersons 데이터를 phase1/phase3 raw single 구조로 변환.

ForestPersons 원본은 보존하고, 선택된 person RGB 샘플만 우리 프로젝트의
YOLO label 구조로 복사한다.

출력 구조:
    data/phase1_raw/single/0/rgb/img/
    data/phase1_raw/single/0/rgb/label/
    data/gop_raw/single/0/rgb/img/
    data/gop_raw/single/0/rgb/label/

ForestPersons는 person 데이터로 사용하므로 class id는 항상 0이다.
pose/visible_ratio/season/place metadata는 학습 label로 쓰지 않고,
phase별 샘플링과 변환 기록에만 사용한다.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path


PERSON_CLASS_ID = 0
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

PHASE1_SEASON_TARGETS = {"summer": 0.40, "winter": 0.40, "fall": 0.20}
PHASE3_SEASON_TARGETS = {"summer": 0.40, "winter": 0.40, "fall": 0.20}

PHASE1_PLACE_TARGETS = {"forest": 0.80, "valley": 0.20, "road": 0.00}
PHASE3_PLACE_TARGETS = {"forest": 0.75, "valley": 0.25, "road": 0.00}

PHASE1_POSE_TARGETS = {"standing": 0.55, "sitting": 0.30, "lying": 0.15}
PHASE3_POSE_TARGETS = {"standing": 0.40, "sitting": 0.35, "lying": 0.25}

PHASE1_VIS_TARGETS = {100: 0.50, 70: 0.25, 40: 0.15, 20: 0.10}
PHASE3_VIS_TARGETS = {100: 0.30, 70: 0.30, 40: 0.25, 20: 0.15}

PHASE1_SIZE_TARGETS = {"small": 0.30, "medium": 0.50, "large": 0.20}
PHASE3_SIZE_TARGETS = {"small": 0.50, "medium": 0.40, "large": 0.10}


@dataclass
class BoxRecord:
    x: float
    y: float
    w: float
    h: float
    pose: str
    visible_ratio: float
    bbox_area_ratio: float

    @property
    def aspect_ratio(self) -> float:
        return self.w / self.h if self.h > 0 else 0.0


@dataclass
class ImageRecord:
    file_name: str
    split: str
    width: int
    height: int
    image_id: str
    season: str
    place: str
    weather: str
    boxes: list[BoxRecord] = field(default_factory=list)

    @property
    def path_key(self) -> str:
        return self.file_name

    @property
    def dominant_pose(self) -> str:
        poses = [box.pose for box in self.boxes if box.pose]
        if not poses:
            return "unknown"
        return Counter(poses).most_common(1)[0][0]

    @property
    def min_visible(self) -> float:
        values = [box.visible_ratio for box in self.boxes if box.visible_ratio >= 0]
        return min(values) if values else 100.0

    @property
    def mean_visible(self) -> float:
        values = [box.visible_ratio for box in self.boxes if box.visible_ratio >= 0]
        return sum(values) / len(values) if values else 100.0

    @property
    def min_bbox_area_ratio(self) -> float:
        values = [box.bbox_area_ratio for box in self.boxes if box.bbox_area_ratio > 0]
        return min(values) if values else 0.0

    @property
    def mean_bbox_area_ratio(self) -> float:
        values = [box.bbox_area_ratio for box in self.boxes if box.bbox_area_ratio > 0]
        return sum(values) / len(values) if values else 0.0


def _safe_float(value: str | None, default: float = -1.0) -> float:
    if value is None or str(value).strip() == "":
        return default
    return float(value)


def _safe_int(value: str | None, default: int = 0) -> int:
    if value is None or str(value).strip() == "":
        return default
    return int(float(value))


def _norm_text(value: str | None, default: str = "unknown") -> str:
    if value is None:
        return default
    value = value.strip().lower()
    return value if value else default


def _read_csv_files(root: Path, split_files: list[str]) -> list[ImageRecord]:
    records: dict[str, ImageRecord] = {}

    for split_file in split_files:
        csv_path = root / split_file
        if not csv_path.exists():
            raise FileNotFoundError(f"ForestPersons CSV 파일이 없습니다: {csv_path}")

        with csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_name = row["file_name"]
                width = _safe_int(row.get("width"))
                height = _safe_int(row.get("height"))
                if width <= 0 or height <= 0:
                    continue

                record = records.get(file_name)
                if record is None:
                    record = ImageRecord(
                        file_name=file_name,
                        split=_norm_text(row.get("split"), Path(split_file).stem),
                        width=width,
                        height=height,
                        image_id=str(row.get("image_id", "")),
                        season=_norm_text(row.get("season")),
                        place=_norm_text(row.get("place")),
                        weather=_norm_text(row.get("weather")),
                    )
                    records[file_name] = record

                x = _safe_float(row.get("bbox_x"), 0.0)
                y = _safe_float(row.get("bbox_y"), 0.0)
                w = _safe_float(row.get("bbox_w"), 0.0)
                h = _safe_float(row.get("bbox_h"), 0.0)
                if w <= 0 or h <= 0:
                    continue

                bbox_area = _safe_float(row.get("bbox_area"), w * h)
                bbox_area_ratio = bbox_area / float(width * height)
                record.boxes.append(
                    BoxRecord(
                        x=x,
                        y=y,
                        w=w,
                        h=h,
                        pose=_norm_text(row.get("pose")),
                        visible_ratio=_safe_float(row.get("visible_ratio"), 100.0),
                        bbox_area_ratio=bbox_area_ratio,
                    )
                )

    return [record for record in records.values() if record.boxes]


def _filter_existing_images(root: Path, records: list[ImageRecord]) -> list[ImageRecord]:
    kept = []
    missing = 0
    for record in records:
        image_path = root / record.file_name
        if image_path.exists() and image_path.suffix.lower() in IMAGE_EXTENSIONS:
            kept.append(record)
        else:
            missing += 1
    if missing:
        print(f"이미지 파일이 없어 제외된 ForestPersons 샘플: {missing}개")
    return kept


def _parse_csv_values(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def _filter_phase1_strict_candidates(
    records: list[ImageRecord],
    min_area_ratio: float,
    max_area_ratio: float,
    min_aspect: float,
    max_aspect: float,
    poses: set[str],
    min_visible_ratio: float,
) -> list[ImageRecord]:
    """phase1 사람 특징 학습에 적합한 bbox가 하나 이상 있는 이미지만 남긴다."""

    filtered = []
    for record in records:
        for box in record.boxes:
            if not (min_area_ratio <= box.bbox_area_ratio <= max_area_ratio):
                continue
            if not (min_aspect <= box.aspect_ratio <= max_aspect):
                continue
            if poses and box.pose not in poses:
                continue
            if box.visible_ratio < min_visible_ratio:
                continue
            filtered.append(record)
            break
    return filtered


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * q)))
    return values[idx]


def _assign_size_buckets(records: list[ImageRecord]) -> dict[str, str]:
    values = [record.min_bbox_area_ratio for record in records]
    q1 = _quantile(values, 0.33)
    q2 = _quantile(values, 0.66)
    buckets = {}
    for record in records:
        ratio = record.min_bbox_area_ratio
        if ratio <= q1:
            bucket = "small"
        elif ratio <= q2:
            bucket = "medium"
        else:
            bucket = "large"
        buckets[record.path_key] = bucket
    return buckets


def _nearest_visible_bucket(value: float) -> int:
    return min((20, 40, 70, 100), key=lambda item: abs(item - value))


def _ratio_weight(value: str, targets: dict[str, float]) -> float:
    return max(0.02, targets.get(value, 0.02))


def _visible_weight(value: float, targets: dict[int, float]) -> float:
    bucket = _nearest_visible_bucket(value)
    return max(0.02, targets.get(bucket, 0.02))


def _score_record(
    record: ImageRecord,
    size_bucket: str,
    pose_targets: dict[str, float],
    visible_targets: dict[int, float],
    size_targets: dict[str, float],
) -> float:
    pose_score = _ratio_weight(record.dominant_pose, pose_targets)
    visible_score = _visible_weight(record.min_visible, visible_targets)
    size_score = _ratio_weight(size_bucket, size_targets)
    return pose_score * visible_score * size_score


def _weighted_choice_without_replacement(
    records: list[ImageRecord],
    scores: dict[str, float],
    count: int,
    rng: random.Random,
) -> list[ImageRecord]:
    if count <= 0 or not records:
        return []

    ranked = []
    for record in records:
        weight = max(scores.get(record.path_key, 0.001), 0.001)
        key = rng.random() ** (1.0 / weight)
        ranked.append((key, record))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [record for _, record in ranked[:count]]


def _allocate_group_counts(
    groups: dict[tuple[str, str], list[ImageRecord]],
    total: int,
    season_targets: dict[str, float],
    place_targets: dict[str, float],
) -> dict[tuple[str, str], int]:
    if total <= 0:
        return {}

    raw_weights = {}
    for key, records in groups.items():
        season, place = key
        target_weight = season_targets.get(season, 0.02) * place_targets.get(place, 0.02)
        raw_weights[key] = target_weight if records else 0.0

    weight_sum = sum(raw_weights.values())
    if weight_sum <= 0:
        raw_weights = {key: len(records) for key, records in groups.items()}
        weight_sum = sum(raw_weights.values())

    allocations = {}
    remainders = []
    assigned = 0
    for key, records in groups.items():
        exact = total * raw_weights[key] / weight_sum if weight_sum else 0.0
        base = min(len(records), int(math.floor(exact)))
        allocations[key] = base
        assigned += base
        remainders.append((exact - base, key))

    remaining = total - assigned
    remainders.sort(reverse=True)
    while remaining > 0:
        progressed = False
        for _, key in remainders:
            if remaining <= 0:
                break
            if allocations[key] < len(groups[key]):
                allocations[key] += 1
                remaining -= 1
                progressed = True
        if not progressed:
            break

    return allocations


def _sample_phase_records(
    records: list[ImageRecord],
    count: int,
    rng: random.Random,
    size_buckets: dict[str, str],
    season_targets: dict[str, float],
    place_targets: dict[str, float],
    pose_targets: dict[str, float],
    visible_targets: dict[int, float],
    size_targets: dict[str, float],
) -> list[ImageRecord]:
    groups: dict[tuple[str, str], list[ImageRecord]] = defaultdict(list)
    for record in records:
        groups[(record.season, record.place)].append(record)

    allocations = _allocate_group_counts(groups, min(count, len(records)), season_targets, place_targets)
    selected = []
    selected_keys = set()
    scores = {
        record.path_key: _score_record(
            record,
            size_buckets[record.path_key],
            pose_targets,
            visible_targets,
            size_targets,
        )
        for record in records
    }

    for key, group_records in groups.items():
        group_count = allocations.get(key, 0)
        chosen = _weighted_choice_without_replacement(group_records, scores, group_count, rng)
        selected.extend(chosen)
        selected_keys.update(record.path_key for record in chosen)

    if len(selected) < count:
        remaining = [record for record in records if record.path_key not in selected_keys]
        selected.extend(
            _weighted_choice_without_replacement(
                remaining,
                scores,
                min(count - len(selected), len(remaining)),
                rng,
            )
        )

    return selected[:count]


def _clip_box(box: BoxRecord, width: int, height: int) -> tuple[float, float, float, float] | None:
    x1 = max(0.0, min(float(width), box.x))
    y1 = max(0.0, min(float(height), box.y))
    x2 = max(0.0, min(float(width), box.x + box.w))
    y2 = max(0.0, min(float(height), box.y + box.h))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _to_yolo_line(xyxy: tuple[float, float, float, float], width: int, height: int) -> str:
    x1, y1, x2, y2 = xyxy
    cx = ((x1 + x2) / 2.0) / width
    cy = ((y1 + y2) / 2.0) / height
    bw = (x2 - x1) / width
    bh = (y2 - y1) / height
    return f"{PERSON_CLASS_ID} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}"


def _prepare_output_dirs(output_root: Path, modality: str) -> tuple[Path, Path]:
    base = output_root / str(PERSON_CLASS_ID) / modality
    img_dir = base / "img"
    label_dir = base / "label"
    img_dir.mkdir(parents=True, exist_ok=True)
    label_dir.mkdir(parents=True, exist_ok=True)
    return img_dir, label_dir


def _write_records(
    records: list[ImageRecord],
    root: Path,
    output_root: Path,
    prefix: str,
    modality: str,
    overwrite: bool,
    dry_run: bool,
) -> list[dict[str, str]]:
    img_dir, label_dir = _prepare_output_dirs(output_root, modality)
    metadata_rows = []

    for idx, record in enumerate(records):
        src_image = root / record.file_name
        suffix = src_image.suffix.lower()
        out_stem = f"{prefix}_{idx:06d}"
        dst_image = img_dir / f"{out_stem}{suffix}"
        dst_label = label_dir / f"{out_stem}.txt"

        yolo_lines = []
        for box in record.boxes:
            clipped = _clip_box(box, record.width, record.height)
            if clipped is not None:
                yolo_lines.append(_to_yolo_line(clipped, record.width, record.height))
        if not yolo_lines:
            continue

        if not dry_run:
            if not overwrite and (dst_image.exists() or dst_label.exists()):
                raise FileExistsError(
                    f"출력 파일이 이미 있습니다. --overwrite 사용 또는 prefix 변경 필요: {dst_image}"
                )
            shutil.copy2(src_image, dst_image)
            dst_label.write_text("\n".join(yolo_lines) + "\n")

        metadata_rows.append(
            {
                "output_stem": out_stem,
                "output_image": str(dst_image),
                "output_label": str(dst_label),
                "source_image": str(src_image),
                "source_file_name": record.file_name,
                "source_split": record.split,
                "source_image_id": record.image_id,
                "season": record.season,
                "place": record.place,
                "weather": record.weather,
                "dominant_pose": record.dominant_pose,
                "min_visible": f"{record.min_visible:.3f}",
                "mean_visible": f"{record.mean_visible:.3f}",
                "bbox_count": str(len(yolo_lines)),
                "min_bbox_area_ratio": f"{record.min_bbox_area_ratio:.8f}",
                "mean_bbox_area_ratio": f"{record.mean_bbox_area_ratio:.8f}",
            }
        )

    return metadata_rows


def _print_distribution(title: str, records: list[ImageRecord], size_buckets: dict[str, str]) -> None:
    print(f"\n[{title}] {len(records)}개 이미지")
    counters = {
        "season": Counter(record.season for record in records),
        "place": Counter(record.place for record in records),
        "pose": Counter(record.dominant_pose for record in records),
        "visible": Counter(_nearest_visible_bucket(record.min_visible) for record in records),
        "bbox_size": Counter(size_buckets[record.path_key] for record in records),
    }
    for name, counter in counters.items():
        total = sum(counter.values()) or 1
        items = ", ".join(f"{key}={value}({value / total:.1%})" for key, value in sorted(counter.items()))
        print(f"  {name}: {items}")


def _write_metadata(path: Path, rows: list[dict[str, str]], dry_run: bool) -> None:
    if dry_run or not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def convert(args: argparse.Namespace) -> None:
    root = Path(args.root)
    if not root.exists():
        raise FileNotFoundError(f"ForestPersons 루트가 없습니다: {root}")

    split_files = [item.strip() for item in args.csv_files.split(",") if item.strip()]
    rng = random.Random(args.seed)

    records = _read_csv_files(root, split_files)
    records = _filter_existing_images(root, records)
    phase1_pool = records
    if args.phase1_strict:
        phase1_pool = _filter_phase1_strict_candidates(
            records,
            min_area_ratio=args.phase1_strict_min_area,
            max_area_ratio=args.phase1_strict_max_area,
            min_aspect=args.phase1_strict_min_aspect,
            max_aspect=args.phase1_strict_max_aspect,
            poses=_parse_csv_values(args.phase1_strict_poses),
            min_visible_ratio=args.phase1_strict_min_visible,
        )
        print(
            "phase1 strict 후보: "
            f"{len(phase1_pool)}개 / 전체 {len(records)}개 "
            f"(area={args.phase1_strict_min_area:.3f}~{args.phase1_strict_max_area:.3f}, "
            f"aspect={args.phase1_strict_min_aspect:.2f}~{args.phase1_strict_max_aspect:.2f}, "
            f"pose={args.phase1_strict_poses}, visible>={args.phase1_strict_min_visible:g})"
        )
    size_buckets = _assign_size_buckets(records)

    phase1_records = _sample_phase_records(
        records=phase1_pool,
        count=args.phase1_count,
        rng=rng,
        size_buckets=size_buckets,
        season_targets=PHASE1_SEASON_TARGETS,
        place_targets=PHASE1_PLACE_TARGETS,
        pose_targets=PHASE1_POSE_TARGETS,
        visible_targets=PHASE1_VIS_TARGETS,
        size_targets=PHASE1_SIZE_TARGETS,
    )
    phase1_keys = {record.path_key for record in phase1_records}
    phase3_pool = [record for record in records if record.path_key not in phase1_keys]
    phase3_records = _sample_phase_records(
        records=phase3_pool,
        count=args.phase3_count,
        rng=rng,
        size_buckets=size_buckets,
        season_targets=PHASE3_SEASON_TARGETS,
        place_targets=PHASE3_PLACE_TARGETS,
        pose_targets=PHASE3_POSE_TARGETS,
        visible_targets=PHASE3_VIS_TARGETS,
        size_targets=PHASE3_SIZE_TARGETS,
    )

    _print_distribution("phase1 ForestPersons 선택", phase1_records, size_buckets)
    _print_distribution("phase3 ForestPersons 선택", phase3_records, size_buckets)

    print(f"\ndry_run={args.dry_run}")
    print(f"phase1 출력: {args.phase1_output}")
    print(f"phase3 출력: {args.phase3_output}")

    phase1_rows = _write_records(
        records=phase1_records,
        root=root,
        output_root=Path(args.phase1_output),
        prefix=args.phase1_prefix,
        modality=args.modality,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    phase3_rows = _write_records(
        records=phase3_records,
        root=root,
        output_root=Path(args.phase3_output),
        prefix=args.phase3_prefix,
        modality=args.modality,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )

    for row in phase1_rows:
        row["target_phase"] = "phase1"
    for row in phase3_rows:
        row["target_phase"] = "phase3"
    metadata_rows = phase1_rows + phase3_rows
    _write_metadata(Path(args.metadata_output), metadata_rows, args.dry_run)

    print(f"\nForestPersons 변환 대상: phase1={len(phase1_rows)}개, phase3={len(phase3_rows)}개")
    if args.dry_run:
        print("dry-run 모드라 실제 파일은 생성하지 않았습니다.")
    else:
        print(f"metadata 저장: {args.metadata_output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ForestPersons를 phase1/phase3 raw 구조로 변환")
    parser.add_argument("--root", default="data/ForestPersons", help="ForestPersons 원본 루트")
    parser.add_argument(
        "--csv-files",
        default="train.csv,val.csv,test.csv",
        help="사용할 CSV 파일 목록. 쉼표로 구분",
    )
    parser.add_argument("--phase1-output", default="data/phase1_raw/single", help="phase1 single 출력 루트")
    parser.add_argument("--phase3-output", default="data/gop_raw/single", help="phase3 single 출력 루트")
    parser.add_argument("--phase1-count", type=int, default=4000, help="phase1로 변환할 이미지 수")
    parser.add_argument("--phase3-count", type=int, default=2000, help="phase3로 변환할 이미지 수")
    parser.add_argument(
        "--phase1-strict",
        action="store_true",
        help="phase1 후보를 standing/visible/bbox 기준으로 엄격하게 필터링",
    )
    parser.add_argument("--phase1-strict-min-area", type=float, default=0.02)
    parser.add_argument("--phase1-strict-max-area", type=float, default=0.15)
    parser.add_argument("--phase1-strict-min-aspect", type=float, default=0.25)
    parser.add_argument("--phase1-strict-max-aspect", type=float, default=0.75)
    parser.add_argument("--phase1-strict-poses", default="standing")
    parser.add_argument("--phase1-strict-min-visible", type=float, default=70.0)
    parser.add_argument("--phase1-prefix", default="fp_p1", help="phase1 출력 파일 prefix")
    parser.add_argument("--phase3-prefix", default="fp_p3", help="phase3 출력 파일 prefix")
    parser.add_argument("--modality", choices=["rgb", "tir"], default="rgb", help="출력 modality")
    parser.add_argument("--metadata-output", default="data/forestpersons_conversion_metadata.csv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="실제 복사 없이 분포만 확인")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력 파일 덮어쓰기")
    return parser.parse_args()


def main() -> None:
    convert(parse_args())


if __name__ == "__main__":
    main()
