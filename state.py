"""
state.py — Streamlit session_state 초기화 전담

앱이 실행되거나 재실행될 때마다(페이지 이동, 버튼 클릭 등 모든 상호작용마다)
가장 먼저 호출되어, 필요한 모든 session_state 키의 기본값을 채워 넣습니다.
setdefault()를 사용하므로 이미 값이 존재하는 키는 절대 덮어쓰지 않습니다.
이후 다른 모듈들은 st.session_state를 통해 이 값들을 자유롭게 읽고 씁니다.
"""
import streamlit as st

import db_rds as db
import s3_storage as s3


def init_session_state() -> None:
    """앱 진입 시 필요한 모든 session_state 키를 기본값으로 초기화합니다."""
    ss = st.session_state

    # ── 주요 데이터 컨테이너 ──
    ss.setdefault("detection_logs", [])   # 전체 탐지 이력 (로그 페이지에서 사용 · RDS 연결 시 과거 이력까지 포함)
    ss.setdefault("next_alert_id", 1)     # 메모리 모드(DB 미연결)일 때 새 로그에 부여할 로컬 ID 카운터

    # ── 데모 및 시뮬레이션 설정 ──
    ss.setdefault("simulate", True)       # True면 backend.py 호출 없이 무작위 탐지 데이터를 생성
    ss.setdefault("person_ratio", 0.03)    # 데모 모드에서 탐지 객체가 '사람'으로 나올 확률 (0.0~1.0)

    # ── UI 및 알람 제어 상태 ──
    ss.setdefault("current_page", "관제 대시보드")  # 현재 선택된 페이지 (상단 네비게이션 버튼으로 전환)
    ss.setdefault("selected_cam", "전체 구역")  # "전체 구역" → 그리드 보기 / 특정 카메라명 → 집중 보기
    ss.setdefault("grid_count", 4)              # '전체 구역' 그리드에 표시할 총 카메라 개수 (대시보드에서 +/- 조절)

    _sync_db_and_s3()


def _sync_db_and_s3() -> None:
    """DB/S3 연결 가능 여부를 확인하고, 최초 1회만 과거 로그를 메모리로 적재합니다."""
    ss = st.session_state

    # 앱이 리런될 때마다 연결 가능 여부를 다시 확인하여 상단 상태뱃지가 항상 최신 상태를 반영하도록 함
    ss["DB_ENABLED"] = db.init_db()
    ss["S3_ENABLED"] = s3.is_enabled()   # secrets.toml에 [s3] 설정이 채워져 있으면 True
    ss.setdefault("db_loaded", False)    # 과거 로그를 이미 한 번 불러왔는지 여부 (중복 로딩 방지)

    if ss["DB_ENABLED"] and not ss.db_loaded:
        try:
            ss.detection_logs = db.fetch_all_logs()
            # 기존 DB에 저장된 가장 큰 ID를 기준으로 로컬 카운터를 동기화 (메모리 모드로 전환되어도 ID가 겹치지 않도록)
            if ss.detection_logs:
                ss.next_alert_id = max(a["id"] for a in ss.detection_logs) + 1
            ss.db_loaded = True
        except Exception as e:
            ss["db_write_warning"] = f"RDS 로그 불러오기 실패: {e}"
