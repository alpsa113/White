"""routers/logs.py — 탐지 로그 조회/편집/삭제, 스냅샷·클립 조회."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel

import db_rds as db
import s3_storage as s3
import state_store as store
from services.log_management import save_log_edits

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _public(a: dict) -> dict:
    box = a.get("box") or {"x1": a.get("x1", 0.0), "y1": a.get("y1", 0.0), "x2": a.get("x2", 0.0), "y2": a.get("y2", 0.0)}
    return {
        "id": a.get("id"),
        "job_id": a.get("job_id"),
        "camera": a.get("camera", ""),
        "status": a.get("status", "대기"),
        "remarks": a.get("remarks", ""),
        "frame_index": a.get("hit_frames", 0),
        "created_at": f"{a.get('date', '')} {a.get('time', '')}".strip() or a.get("created_at", ""),
        "input_type": a.get("input_type", "image"),
        "class_name": a.get("class_name", ""),
        "score": a.get("confidence", a.get("score", 0.0)),
        "x1": box.get("x1", 0.0), "y1": box.get("y1", 0.0),
        "x2": box.get("x2", 0.0), "y2": box.get("y2", 0.0),
        "uri": a.get("uri", a.get("image_path", "")),
        "content_type": a.get("content_type", "image/jpeg"),
    }


@router.get("")
def list_logs():
    """카메라 워커가 별도 프로세스로 RDS에 직접 기록하므로, RDS가 켜져 있으면 항상 RDS에서
    직접 조회합니다(메인 프로세스의 메모리 리스트는 프로세스 분리 이후로는 신뢰할 수 없습니다)."""
    if store.status.get("db_enabled"):
        try:
            return db.fetch_all_logs()  # 이미 응답 스키마와 필드명이 일치합니다.
        except Exception:
            pass
    return [_public(a) for a in store.detection_logs]


class LogUpdate(BaseModel):
    id: int
    class_name: str | None = None
    score: float | None = None
    camera: str | None = None
    status: str | None = None
    remarks: str | None = None


class SaveLogsRequest(BaseModel):
    updates: list[LogUpdate] = []
    deletes: list[int] = []


@router.put("")
def save_logs(req: SaveLogsRequest):
    result = save_log_edits(
        [u.model_dump(exclude_none=True) for u in req.updates],
        req.deletes,
    )
    return result


@router.get("/{log_id}/snapshot")
def get_snapshot(log_id: int):
    key = None
    content_type = "image/jpeg"

    if store.status.get("db_enabled"):
        try:
            row = next((r for r in db.fetch_all_logs() if r["id"] == log_id), None)
            if row:
                key = row.get("uri")
                content_type = row.get("content_type", "image/jpeg")
        except Exception:
            pass

    entry = next((a for a in store.detection_logs if a.get("id") == log_id), None)
    if key is None and entry is not None:
        key = entry.get("uri") or entry.get("image_path")
        content_type = entry.get("content_type", content_type)

    if key and store.status.get("s3_enabled"):
        url = s3.get_presigned_url(key)
        if url:
            return RedirectResponse(url)

    snapshot = entry.get("snapshot") if entry is not None else None
    if snapshot is not None:
        import io
        buf = io.BytesIO()
        snapshot.save(buf, format="JPEG")
        return Response(content=buf.getvalue(), media_type="image/jpeg")

    raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없습니다.")
