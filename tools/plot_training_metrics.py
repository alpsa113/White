"""학습 metrics CSV를 그래프로 변환하는 도구.

trainer가 저장한 checkpoints/phase*/metrics.csv를 읽어 보고서용 그래프를 만든다.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path

# matplotlib/fontconfig는 그래프 저장 시 폰트 캐시를 만든다.
# Colab, 서버, Codex 샌드박스처럼 홈 디렉토리 캐시 권한이 제한된 환경에서도
# 경고 없이 동작하도록 쓰기 가능한 임시 디렉토리를 기본값으로 사용한다.
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

import matplotlib.pyplot as plt


COLAB_ARTIFACT_ROOT = Path("/content/drive/MyDrive/dual_yolo")


def default_output_dir() -> str:
    """Colab Drive가 마운트되어 있으면 Drive metrics 경로를 기본값으로 사용."""
    if COLAB_ARTIFACT_ROOT.exists():
        return str(COLAB_ARTIFACT_ROOT / "metrics")
    return "outputs/metrics"


def load_metrics_csv(metrics_path: Path) -> list[dict[str, float | int | str]]:
    """trainer가 저장한 metrics.csv를 읽어 epoch 순서로 반환."""
    with metrics_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return []
    return sorted(rows, key=lambda row: int(row["epoch"]))


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
    parser = argparse.ArgumentParser(description="학습 metrics CSV를 PNG 그래프로 변환")
    parser.add_argument("--metrics", required=True, help="trainer가 저장한 metrics.csv 경로")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="PNG 출력 디렉토리. Colab Drive가 있으면 기본값은 /content/drive/MyDrive/dual_yolo/metrics",
    )
    parser.add_argument("--prefix", default=None, help="출력 파일 prefix. 기본값은 metrics 파일의 부모 디렉토리명")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    metrics_path = Path(args.metrics)
    output_dir = Path(args.output_dir or default_output_dir())
    prefix = args.prefix or metrics_path.parent.name

    rows = load_metrics_csv(metrics_path)
    if not rows:
        raise SystemExit(f"metrics CSV에 epoch 지표가 없습니다: {metrics_path}")

    generated = plot_metrics(rows, output_dir, prefix)

    for path in generated:
        print(f"그래프 저장: {path}")


if __name__ == "__main__":
    main()
