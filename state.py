"""state.py — Streamlit session_state 초기화. 매 재실행마다 가장 먼저 호출되어 기본값을 채웁니다(setdefault라 덮어쓰지 않음)."""
import streamlit as st

import db_rds as db
import s3_storage as s3


def init_session_state() -> None:
    """앱 진입 시 필요한 모든 session_state 키를 기본값으로 초기화합니다."""
    ss = st.session_state

    ss.setdefault("detection_logs", [])
    ss.setdefault("next_alert_id", 1)
    ss.setdefault("_session_start_max_id", 0)  # 이 값보다 큰 id만 '탐지 이력' 패널에 표시

    ss.setdefault("simulate", True)
    ss.setdefault("person_ratio", 0.03)

    ss.setdefault("authenticated", False)
    ss.setdefault("role", None)
    ss.setdefault("username", None)

    ss.setdefault("current_page", "관제 대시보드")
    ss.setdefault("selected_cam", "전체 구역")

    ss.setdefault("outposts", [])
    ss.setdefault("_outpost_id_counter", 0)
    ss.setdefault("_outpost_map_image_bytes", None)
    ss.setdefault("_map_selected_cam_ids", [])

    _sync_db_and_s3()


def _sync_db_and_s3() -> None:
    """DB/S3 연결 여부를 확인하고, 최초 1회만 과거 로그를 메모리로 적재합니다."""
    ss = st.session_state

    ss["DB_ENABLED"] = db.init_db()
    ss["S3_ENABLED"] = s3.is_enabled()
    ss.setdefault("db_loaded", False)

    if ss["DB_ENABLED"] and not ss.db_loaded:
        try:
            ss.detection_logs = db.fetch_all_logs()
            if ss.detection_logs:
                max_id = max(a["id"] for a in ss.detection_logs)
                ss.next_alert_id = max_id + 1
                ss._session_start_max_id = max_id
            ss.db_loaded = True
        except Exception as e:
            ss["db_write_warning"] = f"RDS 로그 불러오기 실패: {e}"
