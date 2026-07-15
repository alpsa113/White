"""state_store.py — FastAPI 프로세스 전역 인메모리 상태(단일 프로세스 기준, 재시작 시 초기화)."""
import threading
import time

_lock = threading.RLock()

# ---- 초소(카메라) 관리 ----
outposts: list[dict] = []
_outpost_id_counter = 0

# ---- 초소 지도 이미지(업로드로 교체 시 프리셋 파일 대신 이 값을 사용, 재시작 시 초기화) ----
map_image_override: dict | None = None  # {"data": bytes, "content_type": str}
map_image_version = 0

# ---- 탐지 로그(메모리 캐시, RDS 미러 — RDS 미사용 시 유일한 저장소) ----
detection_logs: list[dict] = []
next_alert_id = 1

# ---- 동물 탐지 토스트 이벤트(쿨다운 적용, 프론트 우상단 알림용) ----
toast_events: list[dict] = []  # {"id", "camera", "class_name", "ts"}
_next_toast_id = 1
_MAX_TOAST_EVENTS = 200

# ---- 연결/경고 상태 ----
status = {
    "db_enabled": False,
    "s3_enabled": False,
    "db_write_warning": None,
    "s3_write_warning": None,
}


def next_id() -> int:
    """메모리 카운터 기반 로그 ID를 1개 발급합니다(RDS insert가 실패했을 때의 폴백)."""
    global next_alert_id
    with _lock:
        aid = next_alert_id
        next_alert_id += 1
        return aid


def bump_next_id(min_value: int) -> None:
    """RDS에서 불러온 기존 로그의 최대 ID 이후부터 카운터를 이어가도록 조정합니다."""
    global next_alert_id
    with _lock:
        next_alert_id = max(next_alert_id, min_value + 1)


def next_outpost_id() -> str:
    global _outpost_id_counter
    with _lock:
        _outpost_id_counter += 1
        return f"cam{_outpost_id_counter}"


def add_toast_event(camera: str, class_name: str) -> None:
    """동물 탐지 토스트 1건을 큐에 남깁니다(services/tracking.py의 쿨다운 로직을 통과한 것만)."""
    global _next_toast_id
    with _lock:
        toast_events.append({
            "id": _next_toast_id,
            "camera": camera,
            "class_name": class_name,
            "ts": time.time(),
        })
        _next_toast_id += 1
        del toast_events[:-_MAX_TOAST_EVENTS]
