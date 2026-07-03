"""
services/alerts.py — 탐지 이벤트(알람) 등록/갱신 및 DB 동기화

새로운 객체 탐지 시 로그 레코드 생성(create_detection_alert), 영상 추적 중
기존 레코드의 신뢰도/프레임 수만 조용히 갱신(update_detection_alert),
비고란 저장 콜백(update_remark), 단일 로그 DB 동기화(persist_log)를 담당합니다.
"""
import io
import time
from datetime import datetime

import streamlit as st
from PIL import Image

import db_rds as db
import s3_storage as s3
from config import FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH, AUTO_POPUP_COOLDOWN


def persist_log(alert: dict) -> None:
    """단일 로그 객체의 변경 사항(상태, 비고란 등)을 데이터베이스에 즉시 동기화합니다."""
    if not st.session_state.get("DB_ENABLED"):
        return
    try:
        db.update_log(alert["id"], alert)
    except Exception as e:
        st.session_state["db_write_warning"] = f"RDS 갱신 실패: {e}"


def create_detection_alert(cam_name: str, class_name: str, conf: float, frames: int,
                           source: str, snapshot: Image.Image | None, show_on_dash: bool = True,
                           box: dict | None = None,
                           timestamp_ms: float = 0.0, latency_ms: float = 0.0,
                           conf_thresh: float = FALLBACK_CONF_THRESH,
                           nms_thresh: float = FALLBACK_NMS_THRESH) -> int:
    """
    화면에 새로운 객체가 등장했을 때 호출되며, 새로운 탐지 로그 레코드를 생성하고 DB에 기록합니다.
    사람인 경우 대시보드 패널에 띄우고 조건부로 팝업을 발생시킵니다.
    """
    ss = st.session_state
    now = datetime.now()
    initial_status = "대기" if show_on_dash else "동물탐지"

    # 스냅샷을 S3에 업로드하고 객체 키를 image_path에 저장.
    # S3 미설정/실패 시 빈 문자열로 두어 기존 동작(메모리 스냅샷)을 유지한다.
    image_key = ""
    if ss.get("S3_ENABLED") and snapshot is not None:
        image_key = s3.upload_snapshot(snapshot, cam_name) or ""

    content_type = "image/jpeg"   # 스냅샷은 항상 JPEG
    file_size = 0
    if snapshot is not None:
        _buf = io.BytesIO()
        snapshot.save(_buf, format="JPEG")
        file_size = _buf.tell()   # 직렬화된 byte 수

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
        "box": _box,               # DB insert_log용 (nested)
        "x1": _box["x1"],          # 화면 표시용 flat key (DB 로드 구조와 통일)
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

    # DB에 저장하여 고유 식별자(PK)를 획득. 실패 시 로컬 카운터 활용.
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
    record["snapshot"] = snapshot  # 무거운 스냅샷 객체는 메모리에만 보존합니다.
    ss.detection_logs.append(record)
    # 경보 패널은 이번 세션 탐지만 표시 — RDS 과거 이력과 분리
    if record.get("show_on_dashboard"):
        ss.dashboard_alerts.append(record)

    # 쿨다운 시간을 체크하여 빈번한 팝업 호출을 방지합니다.
    if show_on_dash and ss.get("auto_popup", True):
        current_time = time.time()
        last_popup = ss.get("last_auto_popup_time", 0)

        if current_time - last_popup > AUTO_POPUP_COOLDOWN:
            ss["popup_id"] = aid
            ss["last_auto_popup_time"] = current_time

    return aid


def update_detection_alert(aid: int, conf: float, frames: int, snapshot: Image.Image | None):
    """
    영상에서 지속적으로 추적 중인 객체의 '최대 신뢰도'와 '누적 추적 프레임' 값만 조용히 갱신합니다.
    신규 알람을 추가 생성하지 않음으로써 시스템 로그 도배를 막습니다.
    """
    ss = st.session_state
    for a in ss.detection_logs:
        if a["id"] == aid:
            a["confidence"] = max(a["confidence"], conf)
            a["hit_frames"] = frames
            a["show_on_dashboard"] = True
            # 경보 패널 컨테이너에도 동일 객체가 없으면 추가
            if not any(d["id"] == aid for d in ss.dashboard_alerts):
                ss.dashboard_alerts.append(a)
            if snapshot is not None:
                a["snapshot"] = snapshot
            break


def update_remark(aid: int):
    """우측 패널의 비고 입력값이 변경되었을 때 트리거되는 콜백 함수로 변경 데이터를 DB에 동기화합니다."""
    ss = st.session_state
    val = ss[f"remark_input_{aid}"]
    for a in ss.detection_logs:
        if a["id"] == aid:
            a["remarks"] = val
            persist_log(a)
            break
