"""routers/outposts.py — 초소(지도 마커) CRUD 및 EO/TIR 영상 업로드."""
from fastapi import APIRouter, HTTPException, UploadFile, File
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
    """add_marker()가 config.DEMO_VIDEOS에서 영상을 자동 배정했다면(video_..._seeded) 업로드 때와
    동일하게 사전 분석을 미리 시작해둡니다."""
    if not (marker.get("video_eo_seeded") or marker.get("video_tir_seeded")):
        return
    cameras = camera_registry.get_active_cameras()
    cam = next((c for c in cameras if c["id"] == marker["id"]), {"id": marker["id"], "name": marker["id"]})
    for channel in ("eo", "tir"):
        if not marker.get(f"video_{channel}_seeded"):
            continue
        path = marker[f"video_{channel}_path"]
        video_analyzer.start_analysis(cam, channel, path, marker.get(f"video_{channel}_name", ""))


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


@router.post("/{outpost_id}/video/{channel}")
async def upload_outpost_video(outpost_id: str, channel: str, file: UploadFile = File(...)):
    if channel not in ("eo", "tir"):
        raise HTTPException(status_code=400, detail="channel은 eo 또는 tir이어야 합니다.")
    data = await file.read()
    marker = outposts_service.set_marker_video(outpost_id, channel, data, file.filename)
    if marker is None:
        raise HTTPException(status_code=404, detail="초소를 찾을 수 없습니다.")

    cameras = camera_registry.get_active_cameras()
    cam = next((c for c in cameras if c["id"] == outpost_id), {"id": outpost_id, "name": outpost_id})
    path = marker.get(f"video_{channel}_path")
    video_analyzer.start_analysis(cam, channel, path, file.filename)

    return {"video_eo_name": marker.get("video_eo_name", ""), "video_tir_name": marker.get("video_tir_name", "")}


@router.get("/map-image")
def get_map_image():
    return Response(content=outposts_service.get_map_image_bytes(), media_type="image/png")
