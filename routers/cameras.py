"""routers/cameras.py — 카메라 목록/채널 전환, 원본 영상 파일 서빙(Range 지원), 사전 분석 상태/타임라인."""
import mimetypes
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import state_store as store
from services import camera_registry, video_analyzer
from services.outposts import get_marker_video

router = APIRouter(prefix="/api", tags=["cameras"])

CHUNK_SIZE = 1024 * 1024


def _find_camera(camera_id: str) -> dict:
    for cam in camera_registry.get_active_cameras():
        if cam["id"] == camera_id:
            return cam
    raise HTTPException(status_code=404, detail="카메라를 찾을 수 없습니다.")


@router.get("/cameras")
def list_cameras():
    return camera_registry.get_active_cameras()


class ChannelRequest(BaseModel):
    channel: str


@router.post("/cameras/{camera_id}/channel")
def switch_channel(camera_id: str, req: ChannelRequest):
    if req.channel not in ("eo", "tir"):
        raise HTTPException(status_code=400, detail="channel은 eo 또는 tir이어야 합니다.")
    _find_camera(camera_id)

    for o in store.outposts:
        if o["id"] == camera_id:
            o["active_channel"] = req.channel
            break

    return {"channel": req.channel}


@router.get("/cameras/{camera_id}/analysis-status")
def analysis_status(camera_id: str, channel: str = "eo"):
    return video_analyzer.get_status(f"{camera_id}_{channel}")


@router.get("/cameras/{camera_id}/pacer-position")
def pacer_position(camera_id: str, channel: str = "eo"):
    """실시간 알림 페이서가 지금 타임라인의 몇 ms 지점을 흘려보내고 있는지 반환합니다.
    프론트가 <video>를 이 위치로 seek해서 "알림이 뜬 순간"과 "화면 장면"을 맞춥니다."""
    elapsed_ms = video_analyzer.get_pacer_position(f"{camera_id}_{channel}")
    if elapsed_ms is None:
        raise HTTPException(status_code=404, detail="재생 위치를 알 수 없습니다.")
    return {"elapsed_ms": elapsed_ms}


@router.get("/cameras/{camera_id}/detections-timeline")
def detections_timeline(camera_id: str, channel: str = "eo"):
    """미리 계산해둔 {t(ms), dets} 목록. 프론트가 video.currentTime에 맞춰 이 중 가장 가까운
    항목을 찾아 캔버스에 박스를 그립니다."""
    video = get_marker_video(camera_id, channel)
    if not video:
        return []
    path, _ = video
    return video_analyzer.get_timeline(path) or []


@router.get("/cameras/{camera_id}/video")
def get_video_file(camera_id: str, request: Request, channel: str = "eo"):
    """원본 영상 파일을 그대로 서빙합니다(HTTP Range 지원 — <video> 태그의 탐색/시킹에 필요)."""
    video = get_marker_video(camera_id, channel)
    if not video:
        raise HTTPException(status_code=404, detail="영상을 찾을 수 없습니다.")
    path, _ = video
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="영상 파일이 존재하지 않습니다.")

    file_size = os.path.getsize(path)
    # 배경만 있는 정적 이미지 카메라(video_analyzer.is_image_path)는 image/*로 정확히 내려줘야
    # <img> 태그가 디코딩합니다. 그 외(영상)는 기존처럼 항상 video/mp4로 내립니다 — .mov처럼
    # 실제 MIME과 다르게 표기해도 브라우저가 재생해온 파일들이라, mimetypes로 바꾸면 오히려
    # (예: video/quicktime 등으로 잘못 짐작돼) 재생이 막힐 수 있습니다.
    if video_analyzer.is_image_path(path):
        media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    else:
        media_type = "video/mp4"
    range_header = request.headers.get("range")

    if range_header:
        try:
            range_val = range_header.strip().split("=", 1)[1]
            start_str, end_str = range_val.split("-", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else file_size - 1
            end = min(end, file_size - 1)
        except (IndexError, ValueError):
            start, end = 0, file_size - 1
        chunk_size = end - start + 1

        def iterfile():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = chunk_size
                while remaining > 0:
                    data = f.read(min(CHUNK_SIZE, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
        }
        return StreamingResponse(iterfile(), status_code=206, media_type=media_type, headers=headers)

    def iterfull():
        with open(path, "rb") as f:
            while True:
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                yield data

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(file_size)}
    return StreamingResponse(iterfull(), media_type=media_type, headers=headers)
