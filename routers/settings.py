"""routers/settings.py — 시스템 상태(RDS·S3 연결)."""
from fastapi import APIRouter

import db_rds as db
import s3_storage as s3
import state_store as store

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/system-status")
def system_status():
    db_ok = db.init_db()
    store.status["db_enabled"] = db_ok
    store.status["s3_enabled"] = s3.is_enabled()
    return {
        "rds": "ok" if db_ok else "error",
        "s3": "ok" if store.status["s3_enabled"] else "error",
        "rds_error": db.get_last_init_error() if not db_ok else None,
        "s3_warning": s3.get_last_warning(),
    }
