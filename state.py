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
    ss.setdefault("detection_logs", [])   # 전체 탐지 이력 ('감지 기록' 페이지가 그대로 사용 · RDS 연결 시 과거 이력까지 포함)
    ss.setdefault("next_alert_id", 1)     # 메모리 모드(DB 미연결)일 때 새 로그에 부여할 로컬 ID 카운터
    ss.setdefault("_session_start_max_id", 0)  # 이 값보다 큰 id만 "이번 실행 중 새 탐지"로 간주 (ui/camera/detection_panel.py가 '탐지 이력' 패널 필터링에 사용 — _sync_db_and_s3 참고)

    # ── 데모 및 시뮬레이션 설정 ──
    ss.setdefault("simulate", True)       # True면 backend.py 호출 없이 무작위 탐지 데이터를 생성
    ss.setdefault("person_ratio", 0.03)    # 데모 모드에서 탐지 객체가 '사람'으로 나올 확률 (0.0~1.0)

    # ── 인증 상태 ──
    # authenticated가 True가 되기 전까지 app.py는 views/login.py만 렌더링합니다.
    # role은 "admin" | "user" — 사이드바 페이지 버튼/설정 노출 범위를 가릅니다.
    ss.setdefault("authenticated", False)
    ss.setdefault("role", None)
    ss.setdefault("username", None)

    # ── UI 및 알람 제어 상태 ──
    ss.setdefault("current_page", "관제 대시보드")  # 현재 선택된 페이지 (로그인 시 role에 따라 재설정됨 — views/login.py)
    ss.setdefault("selected_cam", "전체 구역")  # "전체 구역" → 그리드 보기 / 특정 카메라명 → 집중 보기

    # ── 초소(지도 마커) 설정 ──
    # 지도 "이미지"는 config.PRESET_MAP_IMAGE_PATH에 고정되어 있지만, 그 위의
    # 초소(마커) "위치"는 관리자가 설정 페이지에서 직접 클릭해 찍고 지울 수
    # 있습니다 — 상세 스키마/CRUD는 services/outposts.py 참고.
    ss.setdefault("outposts", [])                     # [{"id","info","source","x_ratio","y_ratio","video_eo_bytes","video_eo_name","video_tir_bytes","video_tir_name"}, ...]
    ss.setdefault("_outpost_id_counter", 0)            # 마커 삭제 후에도 id가 재사용되지 않도록 하는 증가 카운터
    ss.setdefault("_outpost_map_image_bytes", None)    # 프리셋 지도 이미지 바이트 (디스크에서 최초 1회만 읽어 캐시)
    ss.setdefault("_map_selected_cam_ids", [])         # "CCTV 화면 보기"로 선택된 초소 id 목록 — 설정 페이지 지도·관제 지도 탭·카메라 화면 탭이 공유

    _sync_db_and_s3()


def _sync_db_and_s3() -> None:
    """DB/S3 연결 가능 여부를 확인하고, 최초 1회만 과거 로그를 메모리로 적재합니다.

    '감지 기록' 페이지(views/logs.py)는 detection_logs를 그대로 보여주므로
    RDS에 쌓인 과거 이력이 계속 조회/편집 가능해야 합니다 — 그래서 과거 이력
    적재 자체는 유지합니다. 다만 '실시간 감시' 페이지의 '탐지 이력' 패널
    (ui/camera/detection_panel.py)은 매 실행마다 오래된 이력까지 다시
    보여주면 "방금 무슨 일이 있었는지"를 파악하기 어려우므로, 적재 시점의
    최대 id를 _session_start_max_id에 기록해두고 그 값을 워터마크 삼아
    "이번 실행 중 새로 생긴 탐지"만 그 패널에 걸러 보여줍니다."""
    ss = st.session_state

    # 앱이 리런될 때마다 연결 가능 여부를 다시 확인 — DB_ENABLED/S3_ENABLED는
    # 사이드바에 뱃지로 표시되진 않지만, 로그 저장/클립 업로드 등에서 메모리
    # 폴백 여부를 판단하는 데 여전히 쓰입니다.
    ss["DB_ENABLED"] = db.init_db()
    ss["S3_ENABLED"] = s3.is_enabled()   # secrets.toml에 [s3] 설정이 채워져 있으면 True
    ss.setdefault("db_loaded", False)    # 과거 로그를 이미 한 번 불러왔는지 여부 (중복 로딩 방지)

    if ss["DB_ENABLED"] and not ss.db_loaded:
        try:
            ss.detection_logs = db.fetch_all_logs()
            # 기존 DB에 저장된 가장 큰 ID를 기준으로 로컬 카운터를 동기화 (메모리 모드로 전환되어도 ID가 겹치지 않도록)
            if ss.detection_logs:
                max_id = max(a["id"] for a in ss.detection_logs)
                ss.next_alert_id = max_id + 1
                ss._session_start_max_id = max_id  # 이 워터마크보다 큰 id만 '탐지 이력' 패널에 새로 나타남
            ss.db_loaded = True
        except Exception as e:
            ss["db_write_warning"] = f"RDS 로그 불러오기 실패: {e}"
