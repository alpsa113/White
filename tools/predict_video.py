#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from inference import DualYOLOPredictor
from inference.video import predict_video


def _parse_cond_vec(value: str | None) -> list[float] | None:
    if value is None:
        return None
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 3:
        raise ValueError("--cond-vec는 'weather,temp_c,illuminance' 형식이어야 합니다.")
    return [float(part) for part in parts]


def main():
    parser = argparse.ArgumentParser(description="DualYOLO 영상 추론")
    parser.add_argument("--checkpoint", required=True, help="학습 checkpoint 경로")
    parser.add_argument("--model-cfg", default="configs/model.yaml")
    parser.add_argument("--video", default=None, help="RGB 영상 경로(--rgb-video 별칭)")
    parser.add_argument("--rgb-video", default=None, help="RGB 영상 경로")
    parser.add_argument("--thermal-video", default=None, help="열화상 영상 경로")
    parser.add_argument("--cond-vec", default=None, help="'weather,temp_c,illuminance'")
    parser.add_argument("--output", default=None, help="bbox 시각화 영상 저장 경로")
    parser.add_argument("--json", default=None, help="프레임별 추론 결과 JSON 저장 경로")
    parser.add_argument("--device", default=None)
    parser.add_argument("--conf", type=float, default=0.50)
    parser.add_argument("--nms", type=float, default=0.4)
    parser.add_argument("--frame-stride", type=int, default=1)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--track", action="store_true", help="영상 프레임 간 bbox tracking 적용")
    parser.add_argument("--track-high-thresh", type=float, default=0.50)
    parser.add_argument("--track-low-thresh", type=float, default=0.20)
    parser.add_argument("--track-match-thresh", type=float, default=0.35)
    parser.add_argument("--track-buffer", type=int, default=8)
    parser.add_argument("--track-smooth-alpha", type=float, default=0.7)
    parser.add_argument("--track-min-area-ratio", type=float, default=0.4)
    parser.add_argument("--track-max-area-ratio", type=float, default=2.5)
    parser.add_argument("--track-min-hits", type=int, default=1)
    args = parser.parse_args()

    rgb_video = args.rgb_video or args.video
    if not rgb_video and not args.thermal_video:
        parser.error("--video, --rgb-video, --thermal-video 중 하나는 필요합니다.")

    predictor = DualYOLOPredictor(
        checkpoint_path=args.checkpoint,
        model_cfg_path=args.model_cfg,
        device=args.device,
        conf_thresh=args.conf,
        nms_thresh=args.nms,
    )
    result = predict_video(
        predictor=predictor,
        rgb_video_path=rgb_video,
        thermal_video_path=args.thermal_video,
        output_video_path=args.output,
        frame_stride=args.frame_stride,
        max_frames=args.max_frames,
        cond_vec=_parse_cond_vec(args.cond_vec),
        use_tracking=args.track,
        track_high_thresh=args.track_high_thresh,
        track_low_thresh=args.track_low_thresh,
        track_match_thresh=args.track_match_thresh,
        track_buffer=args.track_buffer,
        track_smooth_alpha=args.track_smooth_alpha,
        track_min_area_ratio=args.track_min_area_ratio,
        track_max_area_ratio=args.track_max_area_ratio,
        track_min_hits=args.track_min_hits,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
