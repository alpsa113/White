"""routers/outposts.py — 초소(지도 마커) CRUD."""
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from services import outposts as outposts_service
from services import camera_registry
from services import video_analyzer

router = APIRouter(prefix="/api/outposts", tags=["outposts"])


def _public(o: dict) -> dict:
    return {
        "id": o["id"],
        "x_ratio": o["x_ratio"],
        "y_ratio": o["y_ratio"],
        "info": o.get("info", ""),
        "source": o.get("source", ""),
        "video_eo_name": o.get("video_eo_name", ""),
        "video_tir_name": o.get("video_tir_name", ""),
        "active_channel": o.get("active_channel", "eo"),
    }


class CreateOutpostRequest(BaseModel):
    x_ratio: float
    y_ratio: float


class UpdateOutpostRequest(BaseModel):
    info: str | None = None
    source: str | None = None


@router.get("")
def list_outposts():
    return [_public(o) for o in outposts_service.get_outposts()]


@router.post("")
def create_outpost(req: CreateOutpostRequest):
    marker = outposts_service.add_marker(req.x_ratio, req.y_ratio)
    _start_analysis_for_seeded_video(marker)
    return _public(marker)


def _start_analysis_for_seeded_video(marker: dict) -> None:
    """add_marker()가 config.DEMO_VIDEOS에서 영상을 자동 배정했다면(video_..._seeded) 사전 분석을
    미리 시작해둡니다. EO/TIR 둘 다 실제 영상이면(정적 이미지 제외) 두 채널을 서로의
    expected_channels로 알려줘서, 먼저 분석이 끝난 채널이 혼자 앞서 재생을 시작하지 않고
    형제 채널까지 준비될 때까지 기다렸다가 동시에 재생을 시작하도록 합니다."""
    if not (marker.get("video_eo_seeded") or marker.get("video_tir_seeded")):
        return
    cameras = camera_registry.get_active_cameras()
    cam = next((c for c in cameras if c["id"] == marker["id"]), {"id": marker["id"], "name": marker["id"]})
    expected = {
        channel
        for channel in ("eo", "tir")
        if marker.get(f"video_{channel}_seeded")
        and not video_analyzer.is_image_path(marker[f"video_{channel}_path"])
    }
    for channel in ("eo", "tir"):
        if not marker.get(f"video_{channel}_seeded"):
            continue
        path = marker[f"video_{channel}_path"]
        video_analyzer.start_analysis(
            cam, channel, path, marker.get(f"video_{channel}_name", ""), expected_channels=expected
        )


@router.put("/{outpost_id}")
def update_outpost(outpost_id: str, req: UpdateOutpostRequest):
    marker = outposts_service.update_marker(outpost_id, info=req.info, source=req.source)
    if marker is None:
        raise HTTPException(status_code=404, detail="초소를 찾을 수 없습니다.")
    return _public(marker)


@router.delete("/{outpost_id}", status_code=204)
def delete_outpost(outpost_id: str):
    outposts_service.remove_marker(outpost_id)
    return Response(status_code=204)


@router.get("/map-image")
def get_map_image():
    data, content_type = outposts_service.get_map_image()
    return Response(content=data, media_type=content_type)


@router.get("/map-image/version")
def get_map_image_version():
    return {"version": outposts_service.get_map_image_version()}


@router.post("/map-image")
async def upload_map_image(file: UploadFile):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드할 수 있습니다.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    outposts_service.set_map_image(data, file.content_type)
    return {"version": outposts_service.get_map_image_version()}
