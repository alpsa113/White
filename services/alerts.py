"""
services/alerts.py — 탐지 이벤트(알람) 등록/갱신 및 DB 동기화

새로운 객체 탐지 시 로그 레코드 생성(create_detection_alert), 영상 추적 중
기존 레코드의 신뢰도/프레임 수만 조용히 갱신(update_detection_alert),
경보 패널 비고란 저장 콜백(update_remark), 단일 로그 DB 동기화(persist_log)를
담당합니다. RDS/S3 연동 실패는 예외로 앱을 죽이지 않고 경고 배너로만 알립니다.
"""
import io
from datetime import datetime

import streamlit as st
from PIL import Image

import db_rds as db
import s3_storage as s3
from config import FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH


def persist_log(alert: dict) -> None:
    """단일 로그 객체의 변경 사항(상태, 비고란 등)을 데이터베이스에 즉시 동기화합니다.
    DB_ENABLED가 False(메모리 모드)면 아무 작업도 하지 않습니다."""
    if not st.session_state.get("DB_ENABLED"):
        return
    try:
        db.update_log(alert["id"], alert)
    except Exception as e:
        # 실패해도 화면 흐름은 끊지 않고, 상단 경고 배너로만 알림
        st.session_state["db_write_warning"] = f"RDS 갱신 실패: {e}"


def create_detection_alert(cam_name: str, class_name: str, conf: float, frames: int,
                           source: str, snapshot: Image.Image | None, show_on_dash: bool = True,
                           box: dict | None = None,
                           timestamp_ms: float = 0.0, latency_ms: float = 0.0,
                           conf_thresh: float = FALLBACK_CONF_THRESH,
                           nms_thresh: float = FALLBACK_NMS_THRESH) -> int:
    """화면에 새로운 객체가 등장했을 때 호출되며, 새로운 탐지 로그 레코드를 생성하고 DB에 기록합니다.
    사람(show_on_dash=True)인 경우 경보 패널에 띄우고, 쿨다운이 지났으면 팝업도 함께 트리거합니다.
    동물(show_on_dash=False)인 경우 로그에는 남기되 경보 패널에는 표시하지 않습니다.

    Returns:
        int: 이 탐지 이벤트에 부여된 로그 ID (DB 성공 시 PK, 실패 시 로컬 카운터)
    """
    ss = st.session_state
    now = datetime.now()
    initial_status = "대기" if show_on_dash else "동물탐지"

    # 스냅샷을 S3에 업로드하고 객체 키를 image_path에 저장 (S3 미설정/실패 시 빈 문자열로 남겨 메모리 스냅샷만 사용)
    image_key = ""
    if ss.get("S3_ENABLED") and snapshot is not None:
        image_key = s3.upload_snapshot(snapshot, cam_name) or ""

    content_type = "image/jpeg"   # 스냅샷은 항상 JPEG로 저장
    file_size = 0
    if snapshot is not None:
        _buf = io.BytesIO()
        snapshot.save(_buf, format="JPEG")
        file_size = _buf.tell()   # 직렬화된 바이트 수 (DB storage_objects.file_size에 기록)

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
        "image_path": image_key,   # S3 객체 키 (없으면 빈 문자열)
        "content_type": content_type,
        "file_size":    file_size,
        "show_on_dashboard": show_on_dash,
        "box": _box,               # db_rds.insert_log()가 그대로 사용
        "x1": _box["x1"],          # 화면 표시용 flat key (DB에서 불러온 로그와 필드 구조 통일)
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

    # DB에 저장하여 고유 식별자(PK)를 획득 — 실패 시 로컬 카운터로 대체하여 메모리 모드로 계속 동작
    aid = None
    if ss.get("DB_ENABLED"):
        try:
            aid = db.insert_log(record)
        except Exception as e:
            ss["db_write_warning"] = f"RDS 기록 실패(메모리로 대체): {e}"
    if aid is None:
        aid = ss.next_alert_id
        ss.next_alert_id += 1

    record["id"] = aid
    record["snapshot"] = snapshot  # 무거운 스냅샷 객체는 DB가 아니라 메모리(session_state)에만 보존
    ss.detection_logs.append(record)
    # 경보 패널은 이번 세션에서 탐지된 사람만 표시 — RDS 과거 이력과는 별개로 관리
    if record.get("show_on_dashboard"):
        ss.dashboard_alerts.append(record)
        
    return aid


def update_detection_alert(aid: int, conf: float, frames: int, snapshot: Image.Image | None):
    """영상에서 지속적으로 추적 중인 동일 객체의 '최대 신뢰도'와 '누적 추적 프레임' 값만
    조용히 갱신합니다. 신규 알람을 추가 생성하지 않아 같은 사람이 계속 화면에 있어도
    로그가 도배되지 않습니다. show_on_dashboard 여부는 생성 시점에 이미 확정된 값을
    그대로 유지하며, 이 함수가 임의로 바꾸지 않습니다 (사람/동물 모두 이 함수를
    공유하므로, 여기서 값을 바꾸면 동물이 경보 패널에 잘못 노출될 수 있습니다)."""
    ss = st.session_state
    for a in ss.detection_logs:
        if a["id"] == aid:
            a["confidence"] = max(a["confidence"], conf)
            a["hit_frames"] = frames
            # 사람(show_on_dashboard=True)인 경우에만 경보 패널에 추가/유지
            if a.get("show_on_dashboard") and not any(d["id"] == aid for d in ss.dashboard_alerts):
                ss.dashboard_alerts.append(a)
            if snapshot is not None:
                a["snapshot"] = snapshot  # 더 선명한/최신 프레임으로 스냅샷 교체
            break


def update_remark(aid: int):
    """경보 패널의 비고 입력창(text_input)에서 on_change 콜백으로 호출되어,
    입력된 값을 메모리 로그에 반영하고 즉시 DB에도 동기화합니다."""
    ss = st.session_state
    val = ss[f"remark_input_{aid}"]
    for a in ss.detection_logs:
        if a["id"] == aid:
            a["remarks"] = val
            persist_log(a)
            break
