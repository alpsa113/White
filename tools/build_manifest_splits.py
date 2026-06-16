#!/usr/bin/env python3
import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.manifest_loaders import LOADERS


def _write_manifest(path: Path, samples: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"samples": samples}, f, indent=2)


def _print_counter(title: str, counter: dict, denominator: int):
    print(f"  {title}:")
    if not counter:
        print("    (없음)")
        return
    for key, value in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        pct = value / max(denominator, 1) * 100.0
        print(f"    {key}: {value} ({pct:.1f}%)")


def _summarize_manifest(name: str, samples: list[dict]):
    class_names = {0: "person", 1: "boar", 2: "deer", 3: "non_target"}
    by_source = defaultdict(int)
    by_modality = defaultdict(int)
    by_class = defaultdict(int)
    by_tag = defaultdict(int)
    empty_images = 0

    for item in samples:
        by_source[item.get("source", "unknown")] += 1
        by_modality[item.get("modality", "unknown")] += 1

        labels = item.get("labels", [])
        boxes = item.get("boxes", [])
        if not labels or not boxes:
            empty_images += 1
        for label in labels:
            label = int(label)
            by_class[class_names.get(label, str(label))] += 1

        for tag in item.get("tags", []):
            by_tag[tag] += 1

    total_boxes = sum(by_class.values())
    print(f"\n{name}: 전체 이미지 수={len(samples)}")
    _print_counter("source별 분포", by_source, len(samples))
    _print_counter("모달리티별 분포", by_modality, len(samples))
    _print_counter("클래스별 box 분포", by_class, max(total_boxes, 1))
    empty_pct = empty_images / max(len(samples), 1) * 100.0
    print(f"  빈 라벨 이미지: {empty_images} ({empty_pct:.1f}%)")
    _print_counter("tag별 분포", by_tag, len(samples))


def _primary_key(item: dict) -> str:
    labels = sorted({int(label) for label in item.get("labels", [])})
    if labels:
        return "+".join(map(str, labels))
    return "empty"


def _split_items(items: list[dict], val_ratio: float, seed: int) -> tuple[list[dict], list[dict]]:
    groups = defaultdict(list)
    for item in items:
        groups[item["split_group"]].append(item)

    buckets = defaultdict(list)
    for group_items in groups.values():
        buckets[_primary_key(group_items[0])].append(group_items)

    rng = random.Random(seed)
    train, val = [], []
    for bucket_groups in buckets.values():
        rng.shuffle(bucket_groups)
        if len(bucket_groups) <= 1:
            val_count = 0
        else:
            val_count = max(1, round(len(bucket_groups) * val_ratio))
        val_groups = bucket_groups[:val_count]
        train_groups = bucket_groups[val_count:]
        for group in train_groups:
            train.extend(group)
        for group in val_groups:
            val.extend(group)
    return train, val


def build_splits(config: dict, phase_filter: str | None = None):
    output_dir = Path(config.get("output_dir", "data/manifests"))
    seed = int(config.get("seed", 42))
    default_val_ratio = float(config.get("val_ratio", 0.2))

    for phase_name, phase_cfg in config["phases"].items():
        if phase_filter and phase_name != phase_filter:
            continue
        train_all, val_all = [], []
        val_ratio = float(phase_cfg.get("val_ratio", default_val_ratio))
        for src in phase_cfg.get("sources", []):
            if not src.get("enabled", True):
                print(f"{phase_name}: 비활성 source 건너뜀 - {src.get('name', 'unknown')}")
                continue
            loader_key = src.get("format", src.get("type", "manifest"))
            loader = LOADERS[loader_key]
            items = loader(src)
            train_items, val_items = _split_items(items, val_ratio, seed)
            train_all.extend(train_items)
            val_all.extend(val_items)

        _write_manifest(output_dir / f"{phase_name}_train.json", train_all)
        _write_manifest(output_dir / f"{phase_name}_val.json", val_all)
        print(f"{phase_name}: 학습={len(train_all)} 검증={len(val_all)}")
        _summarize_manifest(f"{phase_name} train", train_all)
        _summarize_manifest(f"{phase_name} val", val_all)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/splits/manifest_splits.yaml")
    parser.add_argument("--phase", choices=["phase1", "phase2", "phase3"], default=None)
    args = parser.parse_args()

    with open(args.config) as f:
        config = yaml.safe_load(f)
    build_splits(config, args.phase)


if __name__ == "__main__":
    main()
