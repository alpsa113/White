from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from api.schemas.inference import ImagePredictionResponse
from api.services.image_io import read_upload_rgb, read_upload_thermal
from api.services.predictor_service import predict_image_arrays

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post("/image", response_model=ImagePredictionResponse)
async def predict_image(
    rgb_file: UploadFile | None = File(default=None),
    thermal_file: UploadFile | None = File(default=None),
    conf: float = Query(default=0.25, ge=0.0, le=1.0),
    nms: float = Query(default=0.6, ge=0.0, le=1.0),
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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
