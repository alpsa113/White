from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from tempfile import TemporaryDirectory
from pathlib import Path

from api.schemas.inference import ImagePredictionResponse, VideoPredictionResponse
from api.services.image_io import read_upload_rgb, read_upload_thermal
from api.services.video_io import save_upload_video
from api.services.predictor_service import predict_image_arrays, predict_video_files

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post(
    "/image",
    response_model=ImagePredictionResponse,
    response_model_exclude_none=True,
)
async def predict_image(
    rgb_file: UploadFile | None = File(default=None),
    thermal_file: UploadFile | None = File(default=None),
    conf: float = Query(default=0.45, ge=0.0, le=1.0),
    nms: float = Query(default=0.4, ge=0.0, le=1.0),
):
    if rgb_file is None and thermal_file is None:
        raise HTTPException(
            status_code=400,
            detail="rgb_file 또는 thermal_file 중 하나는 필요합니다.",
        )

    try:
        rgb_image = await read_upload_rgb(rgb_file) if rgb_file is not None else None
        thermal_image = (
            await read_upload_thermal(thermal_file)
            if thermal_file is not None
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return predict_image_arrays(
            rgb_image=rgb_image,
            thermal_image=thermal_image,
            conf=conf,
            nms=nms,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="추론 모델 checkpoint가 준비되지 않았습니다.",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503,
            detail="추론 모델을 로드하거나 실행하지 못했습니다.",
        ) from exc
    
@router.post(
    "/video",
    response_model=VideoPredictionResponse,
)
async def predict_video_endpoint(
    rgb_video: UploadFile | None = File(default=None),
    thermal_video: UploadFile | None = File(default=None),
    conf: float = Query(default=0.45, ge=0.0, le=1.0),
    nms: float = Query(default=0.4, ge=0.0, le=1.0),
    frame_stride: int = Query(default=5, ge=1),
    max_frames: int | None = Query(default=None, ge=1),
    track: bool = Query(default=False),
    track_high_thresh: float = Query(default=0.45, ge=0.0, le=1.0),
    track_low_thresh: float = Query(default=0.20, ge=0.0, le=1.0),
    track_match_thresh: float = Query(default=0.35, ge=0.0, le=1.0),
    track_buffer: int = Query(default=8, ge=0),
    track_smooth_alpha: float = Query(default=0.7, ge=0.0, le=1.0),
    track_min_area_ratio: float = Query(default=0.4, ge=0.0),
    track_max_area_ratio: float = Query(default=2.5, ge=0.0),
    track_min_hits: int = Query(default=1, ge=1),
):
    if rgb_video is None and thermal_video is None:
        raise HTTPException(
            status_code=400,
            detail="rgb_video 또는 thermal_video 중 하나는 필요합니다.",
        )
    if track_low_thresh > track_high_thresh:
        raise HTTPException(
            status_code=400,
            detail="track_low_thresh는 track_high_thresh보다 작거나 같아야 합니다.",
        )
    if track_min_area_ratio > track_max_area_ratio:
        raise HTTPException(
            status_code=400,
            detail="track_min_area_ratio는 track_max_area_ratio보다 작거나 같아야 합니다.",
        )

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        rgb_path = None
        thermal_path = None

        try:
            if rgb_video is not None:
                rgb_path = await save_upload_video(
                    rgb_video,
                    tmp_path / "rgb_video.mp4",
                )

            if thermal_video is not None:
                thermal_path = await save_upload_video(
                    thermal_video,
                    tmp_path / "thermal_video.mp4",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            return predict_video_files(
                rgb_video_path=rgb_path,
                thermal_video_path=thermal_path,
                conf=conf,
                nms=nms,
                frame_stride=frame_stride,
                max_frames=max_frames,
                use_tracking=track,
                track_high_thresh=track_high_thresh,
                track_low_thresh=track_low_thresh,
                track_match_thresh=track_match_thresh,
                track_buffer=track_buffer,
                track_smooth_alpha=track_smooth_alpha,
                track_min_area_ratio=track_min_area_ratio,
                track_max_area_ratio=track_max_area_ratio,
                track_min_hits=track_min_hits,
            )
        except FileNotFoundError as exc:
            message = str(exc)
            if "영상을 열지 못했습니다" in message:
                raise HTTPException(
                    status_code=400,
                    detail="업로드한 파일을 영상으로 읽지 못했습니다.",
                ) from exc
            raise HTTPException(
                status_code=503,
                detail="추론 모델 checkpoint가 준비되지 않았습니다.",
            ) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=503,
                detail="추론 모델을 로드하거나 실행하지 못했습니다.",
            ) from exc
