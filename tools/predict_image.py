#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference import DualYOLOPredictor
from inference.preprocessing import load_rgb_image, load_thermal_image
from inference.visualization import draw_detections_rgb


def _parse_cond_vec(value: str | None) -> list[float] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 3:
        raise ValueError("--cond-vec는 'weather,temp_c,illuminance' 형식이어야 합니다.")
    return [float(part) for part in parts]


def _load_display_image(rgb_path: str | None, thermal_path: str | None):
    if rgb_path:
        return load_rgb_image(rgb_path)
    if thermal_path:
        thermal = load_thermal_image(thermal_path)
        return cv2.cvtColor(thermal, cv2.COLOR_GRAY2RGB)
    raise ValueError("시각화하려면 --rgb 또는 --thermal 중 하나가 필요합니다.")


def main():
    parser = argparse.ArgumentParser(description="DualYOLO 단일 이미지 추론")
    parser.add_argument("--checkpoint", required=True, help="학습 checkpoint 경로")
    parser.add_argument("--model-cfg", default="configs/model.yaml")
    parser.add_argument("--rgb", default=None, help="RGB 이미지 경로")
    parser.add_argument("--thermal", default=None, help="열화상 이미지 경로")
    parser.add_argument("--cond-vec", default=None, help="'weather,temp_c,illuminance'")
    parser.add_argument("--output", default=None, help="bbox 시각화 이미지 저장 경로")
    parser.add_argument("--json", default=None, help="추론 결과 JSON 저장 경로")
    parser.add_argument("--device", default=None)
    parser.add_argument("--conf", type=float, default=0.50)
    parser.add_argument("--nms", type=float, default=0.4)
    args = parser.parse_args()

    if not args.rgb and not args.thermal:
        parser.error("--rgb 또는 --thermal 중 하나는 필요합니다.")

    predictor = DualYOLOPredictor(
        checkpoint_path=args.checkpoint,
        model_cfg_path=args.model_cfg,
        device=args.device,
        conf_thresh=args.conf,
        nms_thresh=args.nms,
    )
    result = predictor.predict(
        rgb_path=args.rgb,
        thermal_path=args.thermal,
        cond_vec=_parse_cond_vec(args.cond_vec),
    )
    result_dict = result.to_dict()
    print(json.dumps(result_dict, ensure_ascii=False, indent=2))

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(result_dict, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        display = _load_display_image(args.rgb, args.thermal)
        drawn = draw_detections_rgb(display, result_dict["detections"])
        ok = cv2.imwrite(str(output_path), drawn)
        if not ok:
            raise RuntimeError(f"결과 이미지를 저장하지 못했습니다: {output_path}")


if __name__ == "__main__":
    main()
