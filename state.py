"""
state.py — Streamlit session_state 초기화 전담

앱 실행(재실행 포함) 시마다 호출되며, 필요한 모든 session_state 키의 기본값을
설정합니다. setdefault를 사용하므로 이미 값이 있는 키는 덮어쓰지 않습니다.
이후 다른 모듈에서는 st.session_state를 통해 자유롭게 읽고 씁니다.
"""
import streamlit as st

import db_rds as db
import s3_storage as s3


def init_session_state() -> None:
    """앱 진입 시 필요한 모든 session_state 키를 기본값으로 초기화합니다."""
    ss = st.session_state

    # 주요 데이터 컨테이너
    ss.setdefault("detection_logs", [])   # 전체 탐지 이력 (로그 페이지용 · RDS 이력 포함)
    ss.setdefault("dashboard_alerts", []) # 이번 세션 경보 패널 전용 (재시작 시 초기화 · RDS 미로드)
    ss.setdefault("next_alert_id", 1)     # 메모리 모드 작동 시 새로운 로그에 부여할 로컬 ID 카운터
    ss.setdefault("popup_id", None)       # 화면 중앙에 크게 띄울 특정 로그의 ID를 지정하는 트리거 변수

    # 데모 및 시뮬레이션 설정                                                # ← 데모 모드 전용 (제거 시 이 두 줄도 삭제)
    ss.setdefault("simulate", True)       # 백엔드 연동 없이 가짜 데이터를 생성할지 여부
    ss.setdefault("person_ratio", 0.5)    # 시뮬레이션 시 탐지 객체가 '사람'으로 나올 확률

    # UI 및 알람 제어 상태
    ss.setdefault("auto_popup", True)     # 사람 발견 시 팝업창을 자동으로 띄울지 여부
    ss.setdefault("current_page", "관제 대시보드")
    ss.setdefault("last_auto_popup_time", 0)
    ss.setdefault("selected_cam", "전체 구역")  # "전체 구역" → 2×2 그리드 / 카메라명 → 집중 보기

    _sync_db_and_s3()


def _sync_db_and_s3() -> None:
    """DB/S3 연결 가능 여부를 확인하고, 최초 1회만 과거 로그를 메모리로 적재합니다."""
    ss = st.session_state

    # 앱 시작 시 DB 연결 가능 여부를 확인하고, 과거 로그 데이터를 메모리로 적재합니다.
    ss["DB_ENABLED"] = db.init_db()
    ss["S3_ENABLED"] = s3.is_enabled()   # secrets.toml에 [s3] 설정이 있으면 True
    ss.setdefault("db_loaded", False)

    if ss["DB_ENABLED"] and not ss.db_loaded:
        try:
            ss.detection_logs = db.fetch_all_logs()
            # 기존 DB에 저장된 가장 큰 ID를 기반으로 로컬 카운터를 동기화합니다.
            if ss.detection_logs:
                ss.next_alert_id = max(a["id"] for a in ss.detection_logs) + 1
            ss.db_loaded = True
        except Exception as e:
            ss["db_write_warning"] = f"RDS 로그 불러오기 실패: {e}"
