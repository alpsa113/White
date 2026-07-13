"""services/alerts.py — 탐지 이벤트 로그 생성/갱신 및 DB 동기화. S3 사본이 있으면 메모리 스냅샷은 비웁니다."""
import io
from datetime import datetime

from PIL import Image

import db_rds as db
import s3_storage as s3
import state_store as store
from config import FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH, CLIP_STORAGE_MAX_WIDTH


def _shrink_for_memory(img: Image.Image) -> Image.Image:
    """S3 미보관 시 메모리에 계속 남는 스냅샷 원본을 CLIP_STORAGE_MAX_WIDTH 이하로 축소합니다.
    S3 업로드는 이 함수 호출 전 원본 해상도로 이미 끝난 뒤라 화질에는 영향이 없습니다."""
    if img.width <= CLIP_STORAGE_MAX_WIDTH:
        return img
    new_height = int(img.height * CLIP_STORAGE_MAX_WIDTH / img.width)
    return img.resize((CLIP_STORAGE_MAX_WIDTH, new_height))


def create_detection_alert(cam_name: str, class_name: str, conf: float, frames: int,
                           source: str, snapshot: Image.Image | None, show_on_dash: bool = True,
                           box: dict | None = None,
                           timestamp_ms: float = 0.0, latency_ms: float = 0.0,
                           conf_thresh: float = FALLBACK_CONF_THRESH,
                           nms_thresh: float = FALLBACK_NMS_THRESH) -> int:
    """새 탐지 로그 레코드를 생성해 DB에 기록합니다. 반환값은 로그 ID(DB PK 또는 로컬 카운터)."""
    now = datetime.now()
    initial_status = "대기" if show_on_dash else "동물탐지"

    image_key = ""
    if store.status.get("s3_enabled") and snapshot is not None:
        image_key = s3.upload_snapshot(snapshot, cam_name) or ""
        if not image_key:
            store.status["s3_write_warning"] = s3.get_last_warning()

    content_type = "image/jpeg"
    file_size = 0
    if snapshot is not None:
        _buf = io.BytesIO()
        snapshot.save(_buf, format="JPEG")
        file_size = _buf.tell()

    _box = box or {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0}
    record = {
        "class_name": class_name,
        "camera": cam_name,
        "confidence": conf,
        "hit_frames": frames,
        "source": source,
        "input_type": 'video' if source == '영상' else 'image',
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "status": initial_status,
        "remarks": "",
        "image_path": image_key,
        "content_type": content_type,
        "file_size":    file_size,
        "box": _box,
        "x1": _box["x1"],
        "y1": _box["y1"],
        "x2": _box["x2"],
        "y2": _box["y2"],
        "image_width":  snapshot.width  if snapshot is not None else 1920,
        "image_height": snapshot.height if snapshot is not None else 1080,
        "timestamp_ms":  timestamp_ms,
        "latency_ms":    latency_ms,
        "conf_thresh":   conf_thresh,
        "nms_thresh":  nms_thresh,
    }

    aid = None
    if store.status.get("db_enabled"):
        try:
            aid = db.insert_log(record)
        except Exception as e:
            store.status["db_write_warning"] = f"RDS 기록 실패(메모리로 대체): {e}"
    if aid is None:
        aid = store.next_id()

    record["id"] = aid
    record["job_id"] = None
    # S3 업로드 성공 시 메모리 스냅샷은 보관하지 않음(중복 방지). 미보관 시에도 원본 대신 축소본만 듭니다.
    record["snapshot"] = None if image_key else (_shrink_for_memory(snapshot) if snapshot is not None else None)
    store.detection_logs.insert(0, record)
    return aid


def update_detection_alert(aid: int, conf: float, frames: int, snapshot: Image.Image | None) -> None:
    """추적 중인 동일 객체의 신뢰도/프레임 수만 조용히 갱신합니다(신규 알람 생성 없음)."""
    s3_enabled = bool(store.status.get("s3_enabled"))
    for a in store.detection_logs:
        if a["id"] == aid:
            a["confidence"] = max(a["confidence"], conf)
            a["hit_frames"] = frames
            if snapshot is not None:
                has_persisted_copy = s3_enabled and bool(a.get("image_path") or a.get("uri"))
                a["snapshot"] = None if has_persisted_copy else _shrink_for_memory(snapshot)
            break
