"""routers/tracking.py — 최근 탐지 이력(탐지 이력 패널용)/토스트 폴링 엔드포인트."""
from fastapi import APIRouter

import db_rds as db
import state_store as store
from services.detection import is_person

router = APIRouter(prefix="/api", tags=["tracking"])


@router.get("/detections/recent")
def recent_detections(limit: int = 50):
    """영상 사전 분석(services/video_analyzer.py) 중 발견된 알림도 RDS에 곧바로 기록되므로,
    RDS가 켜져 있으면 항상 RDS에서 직접 조회합니다."""
    if store.status.get("db_enabled"):
        try:
            logs = db.fetch_all_logs()[:limit]
            return [
                {
                    "id": row["id"],
                    "camera": row["camera"],
                    "class_name": row["class_name"],
                    "score": row["score"],
                    "created_at": row["created_at"],
                    "uri": row["uri"],
                    "content_type": row.get("content_type", "image/jpeg"),
                    "is_person": is_person(row["class_name"]),
                }
                for row in logs
            ]
        except Exception:
            pass  # RDS 조회 실패 시 메모리 캐시로 폴백

    logs = store.detection_logs[:limit]
    return [
        {
            "id": a.get("id"),
            "camera": a.get("camera", ""),
            "class_name": a.get("class_name", ""),
            "score": a.get("confidence", a.get("score", 0.0)),
            "created_at": f"{a.get('date', '')} {a.get('time', '')}".strip() or a.get("created_at", ""),
            "uri": a.get("uri", a.get("image_path", "")),
            "content_type": a.get("content_type", "image/jpeg"),
            "is_person": is_person(a.get("class_name", "")),
        }
        for a in logs
    ]


@router.get("/toasts/recent")
def recent_toasts(limit: int = 20):
    """동물 탐지 시 우상단에 잠깐 떴다 사라지는 토스트 이벤트 목록(쿨다운은 services/tracking.py에서 처리됨)."""
    return store.toast_events[-limit:]
