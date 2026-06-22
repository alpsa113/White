from __future__ import annotations

from pathlib import Path

import cv2

from .predictor import DualYOLOPredictor
from .visualization import draw_detections_rgb


def _open_video(path: str | Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise FileNotFoundError(f"영상을 열지 못했습니다: {path}")
    return capture


def _make_writer(
    output_path: str | Path,
    fps: float,
    width: int,
    height: int,
) -> cv2.VideoWriter:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"출력 영상을 생성하지 못했습니다: {output_path}")
    return writer


def _frame_timestamp_ms(frame_index: int, fps: float) -> float:
    if fps <= 0:
        return 0.0
    return round((frame_index / fps) * 1000.0, 2)


def predict_video(
    predictor: DualYOLOPredictor,
    rgb_video_path: str | Path | None = None,
    thermal_video_path: str | Path | None = None,
    output_video_path: str | Path | None = None,
    frame_stride: int = 1,
    max_frames: int | None = None,
    cond_vec: list[float] | tuple[float, ...] | None = None,
) -> dict:
    """영상 프레임을 순회하며 기존 단일 이미지 추론기를 호출."""
    if rgb_video_path is None and thermal_video_path is None:
        raise ValueError("rgb_video_path 또는 thermal_video_path 중 하나는 필요합니다.")
    if frame_stride < 1:
        raise ValueError("frame_stride는 1 이상이어야 합니다.")
    if max_frames is not None and max_frames < 1:
        raise ValueError("max_frames는 1 이상이어야 합니다.")

    rgb_capture = _open_video(rgb_video_path) if rgb_video_path else None
    thermal_capture = _open_video(thermal_video_path) if thermal_video_path else None
    reference = rgb_capture or thermal_capture
    assert reference is not None

    fps = float(reference.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        fps = 30.0
    width = int(reference.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(reference.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    total_frames = int(reference.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    writer = None
    if output_video_path:
        writer = _make_writer(output_video_path, fps, width, height)

    frames: list[dict] = []
    frame_index = 0
    processed_frames = 0

    try:
        while True:
            rgb_ok, rgb_frame = (True, None)
            thermal_ok, thermal_frame = (True, None)

            if rgb_capture is not None:
                rgb_ok, rgb_frame = rgb_capture.read()
            if thermal_capture is not None:
                thermal_ok, thermal_frame = thermal_capture.read()

            if not rgb_ok or not thermal_ok:
                break

            should_process = frame_index % frame_stride == 0
            if should_process:
                rgb_image = None
                thermal_image = None
                display_image = None

                if rgb_frame is not None:
                    rgb_image = cv2.cvtColor(rgb_frame, cv2.COLOR_BGR2RGB)
                    display_image = rgb_image
                if thermal_frame is not None:
                    thermal_image = cv2.cvtColor(thermal_frame, cv2.COLOR_BGR2GRAY)
                    if display_image is None:
                        display_image = cv2.cvtColor(thermal_image, cv2.COLOR_GRAY2RGB)

                result = predictor.predict(
                    rgb_image=rgb_image,
                    thermal_image=thermal_image,
                    cond_vec=cond_vec,
                )
                result_dict = result.to_dict()
                frames.append(
                    {
                        "frame_index": frame_index,
                        "timestamp_ms": _frame_timestamp_ms(frame_index, fps),
                        **result_dict,
                    }
                )
                processed_frames += 1

                if writer is not None and display_image is not None:
                    writer.write(
                        draw_detections_rgb(display_image, result_dict["detections"])
                    )
            elif writer is not None:
                writer.write(rgb_frame if rgb_frame is not None else thermal_frame)

            frame_index += 1
            if max_frames is not None and processed_frames >= max_frames:
                break
    finally:
        if rgb_capture is not None:
            rgb_capture.release()
        if thermal_capture is not None:
            thermal_capture.release()
        if writer is not None:
            writer.release()

    return {
        "video": {
            "rgb_path": str(rgb_video_path) if rgb_video_path else None,
            "thermal_path": str(thermal_video_path) if thermal_video_path else None,
            "output_path": str(output_video_path) if output_video_path else None,
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "frame_stride": frame_stride,
            "processed_frames": processed_frames,
        },
        "frames": frames,
    }
