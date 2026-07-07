"""학습 로그를 CSV와 그래프로 변환하는 도구.

기존 콘솔 로그에서 epoch별 학습 손실, 검증 손실, AP/mAP 지표를 파싱한다.
trainer가 metrics CSV를 직접 저장하기 전까지의 과거 로그 분석에도 사용한다.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

import matplotlib.pyplot as plt


TRAIN_RE = re.compile(
    r"(?P<phase>\d+)단계\s+\|\s+에폭\s+(?P<epoch>\d+)\s+\|\s+(?P<body>.+)"
)
METRIC_RE = re.compile(r"(?P<key>[A-Za-z0-9_]+)=(?P<value>-?\d+(?:\.\d+)?)")

DEFAULT_COLUMNS = [
    "phase",
    "epoch",
    "train_loss",
    "val_loss",
    "mAP50",
    "AP_person",
    "AP_boar",
    "AP_deer",
    "AP_non_target",
    "elapsed_sec",
]


def _parse_key_values(text: str) -> dict[str, float]:
    return {
        match.group("key"): float(match.group("value"))
        for match in METRIC_RE.finditer(text)
    }


def parse_training_log(log_path: Path) -> list[dict[str, float | int | str]]:
    """콘솔 로그에서 epoch별 학습/검증 지표를 추출."""
    rows_by_key: dict[tuple[int, int], dict[str, float | int | str]] = {}
    last_key: tuple[int, int] | None = None

    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        train_match = TRAIN_RE.search(line)
        if train_match:
            phase = int(train_match.group("phase"))
            epoch = int(train_match.group("epoch"))
            body = train_match.group("body")
            values = _parse_key_values(body)
            key = (phase, epoch)
            row = rows_by_key.setdefault(key, {"phase": phase, "epoch": epoch})
            if "total" in values:
                row["train_loss"] = values["total"]
            if body.rstrip().endswith("s"):
                elapsed_match = re.search(r"\|\s*(?P<elapsed>\d+(?:\.\d+)?)s\s*$", body)
                if elapsed_match:
                    row["elapsed_sec"] = float(elapsed_match.group("elapsed"))
            for name, value in values.items():
                if name != "total":
                    row[name] = value
            last_key = key
            continue

        if last_key is None:
            continue

        metric_values = _parse_key_values(line)
        if not metric_values or "mAP50" not in metric_values:
            continue
        rows_by_key[last_key].update(metric_values)

    return [
        rows_by_key[key]
        for key in sorted(rows_by_key, key=lambda item: (item[0], item[1]))
    ]


def _columns_for_rows(rows: list[dict[str, float | int | str]]) -> list[str]:
    columns = list(DEFAULT_COLUMNS)
    extra = sorted({key for row in rows for key in row} - set(columns))
    return columns + extra


def write_csv(rows: list[dict[str, float | int | str]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    columns = _columns_for_rows(rows)
    with output_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _valid_xy(
    rows: list[dict[str, float | int | str]],
    metric: str,
) -> tuple[list[int], list[float]]:
    xs: list[int] = []
    ys: list[float] = []
    for row in rows:
        value = row.get(metric)
        if value is None:
            continue
        value = float(value)
        if math.isnan(value):
            continue
        xs.append(int(row["epoch"]))
        ys.append(value)
    return xs, ys


def _plot_lines(
    rows: list[dict[str, float | int | str]],
    metrics: list[str],
    title: str,
    ylabel: str,
    output_path: Path,
) -> bool:
    plotted = False
    plt.figure(figsize=(9, 5))
    for metric in metrics:
        xs, ys = _valid_xy(rows, metric)
        if not xs:
            continue
        plt.plot(xs, ys, marker="o", linewidth=2, label=metric)
        plotted = True

    if not plotted:
        plt.close()
        return False

    plt.title(title)
    plt.xlabel("epoch")
    plt.ylabel(ylabel)
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=160)
    plt.close()
    return True


def plot_metrics(rows: list[dict[str, float | int | str]], output_dir: Path, prefix: str) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = [
        (
            ["train_loss", "val_loss"],
            "Loss Curve",
            "loss",
            f"{prefix}_loss_curve.png",
        ),
        (
            ["mAP50", "mAP50_95"],
            "mAP Curve",
            "mAP",
            f"{prefix}_map_curve.png",
        ),
        (
            ["AP_person", "AP_boar", "AP_deer", "AP_non_target"],
            "Class AP Curve",
            "AP",
            f"{prefix}_class_ap_curve.png",
        ),
        (
            ["Precision_person", "Recall_person", "F1_person"],
            "Person Precision/Recall/F1 Curve",
            "score",
            f"{prefix}_person_prf_curve.png",
        ),
    ]

    generated: list[Path] = []
    for metrics, title, ylabel, filename in specs:
        path = output_dir / filename
        if _plot_lines(rows, metrics, title, ylabel, path):
            generated.append(path)
    return generated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="학습 로그를 CSV/PNG 지표로 변환")
    parser.add_argument("--log", required=True, help="학습 콘솔 로그 파일")
    parser.add_argument("--output-dir", default="outputs/metrics", help="CSV/PNG 출력 디렉토리")
    parser.add_argument("--prefix", default=None, help="출력 파일 prefix. 기본값은 로그 파일명")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    log_path = Path(args.log)
    output_dir = Path(args.output_dir)
    prefix = args.prefix or log_path.stem

    rows = parse_training_log(log_path)
    if not rows:
        raise SystemExit(f"파싱 가능한 epoch 지표를 찾지 못했습니다: {log_path}")

    output_csv = output_dir / f"{prefix}_metrics.csv"
    write_csv(rows, output_csv)
    generated = plot_metrics(rows, output_dir, prefix)

    print(f"CSV 저장: {output_csv}")
    for path in generated:
        print(f"그래프 저장: {path}")


if __name__ == "__main__":
    main()
