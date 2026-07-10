"""
app.py — GOP 통합 감시 시스템 메인 엔트리포인트

역할: 페이지 설정, session_state 초기화, 로그인 게이트, 사이드바(브랜드명/
페이지 전환/계정 영역) 렌더링, 페이지 라우팅만 담당합니다.
실제 화면 구성과 로직은 ui/, services/, views/ 모듈에 위임되어 있어 이
파일은 항상 가볍게 유지됩니다.

session_state.authenticated가 False인 동안은 views/login.py만 렌더링되고
그 외 모든 로직(사이드바, 카메라, 재생 루프)은 실행되지 않습니다. 로그인
성공 후에는 role("admin"|"user")에 따라 일부 화면의 노출 범위가 달라집니다.
"관제 대시보드"·"감지 기록"·"설정" 세 페이지 모두 두 role이 접근할 수
있지만, "설정" 페이지 안의 초소 마커 추가/영상 매핑/선택/삭제와 데모 모드는
admin만 가능하고 user는 조회만 할 수 있습니다(views/settings.py, ui/outposts/
editor.py가 role을 보고 위젯을 읽기 전용으로 바꿉니다). "감지 기록"
안의 편집 탭도 마찬가지로 admin에게만 보입니다(views/logs.py 참고).

실행 방법:
    streamlit run app.py
"""
import streamlit as st

from state import init_session_state
from ui.layout import render_sidebar
from views import login, dashboard, logs, settings
from services.camera_registry import get_active_cameras
from services.playback import run_playback_loop

# wide 레이아웃 사용 — 카메라 그리드와 로그 표가 넓은 화면을 최대한 활용하도록 설정
# initial_sidebar_state="expanded" — 페이지 전환 버튼이 사이드바로 이동했으므로
# 첫 로딩부터 항상 펼쳐진 상태로 시작합니다.
st.set_page_config(page_title="GOP 통합 감시 시스템", layout="wide", initial_sidebar_state="expanded")

# session_state 기본값 채우기 + RDS/S3 연결 확인 (스크립트가 재실행될 때마다 매번 실행됨)
init_session_state()

ss = st.session_state

# 로그인 전: 로그인 화면만 그리고 즉시 종료합니다. 사이드바(페이지 전환/상태뱃지/
# 로그아웃 등)는 인증된 사용자에게만 의미가 있으므로 여기서는 아예 호출하지 않고,
# 카메라 목록 계산·재생 루프도 실행하지 않습니다.
if not ss.authenticated:
    login.render()
    st.stop()

# 브랜드명 + 페이지 전환 버튼(role에 따라 노출 범위가 다름) + 계정 영역(하단 고정,
# 로그아웃/설정) → 로그인 이후 어떤 페이지를 보고 있든 항상 동일하게 사이드바에 표시됩니다.
render_sidebar()

# "설정" 페이지는 이제 user 권한도 접근할 수 있습니다 (조회 전용 — 초소
# 마커 추가/영상 매핑/선택/삭제와 데모 모드는 admin만 가능하고, user는
# 초소 정보·시스템 상태를 조회만 할 수 있습니다. views/settings.py,
# ui/outposts/editor.py가 role을 보고 위젯을 읽기 전용으로 바꿉니다).
page_selection = ss.current_page

# 카메라 목록/재생 상태는 현재 보고 있는 페이지와 무관하게 항상 계산합니다.
# 관제 시스템 특성상, 로그/설정 페이지에 있어도 탐지는 끊기지 않아야 합니다.
cameras = get_active_cameras()
eo_video_slots = {}
tir_video_slots = {}

# 현재 선택된 페이지의 render()만 호출 — 나머지 페이지 코드는 실행되지 않음
if page_selection == "관제 대시보드":
    eo_video_slots, tir_video_slots = dashboard.render(cameras)
elif page_selection == "감지 기록":
    logs.render()
elif page_selection == "설정":
    settings.render()

# 대시보드가 아닌 페이지에 있으면 두 slots 딕셔너리가 비어있어 화면 갱신만
# 건너뛰고, 탐지·로그 생성·알림(토스트/소리)은 그대로 계속됩니다. EO/TIR
# 두 채널 모두 항상 독립적으로 재생·탐지되므로(services/playback.py 모듈
# docstring 참고), 채널당 한 번씩 재생 루프를 돌립니다.
eo_active_cams = [cam for cam in cameras if ss.get(f"playing_{cam['id']}_eo")]
tir_active_cams = [cam for cam in cameras if ss.get(f"playing_{cam['id']}_tir")]

# run_playback_loop는 더 이상 자체적으로 무조건 st.rerun()을 하지 않으므로
# (services/playback.py 모듈 docstring 참고), EO/TIR 루프를 모두 실행한
# 뒤 여기서 한 번만 rerun합니다 — 그래야 한쪽 루프의 rerun이 다른 쪽 루프
# 호출을 가로채 실행되지 못하게 막는 일이 없습니다.
ran_loop = False
if eo_active_cams:
    run_playback_loop(eo_active_cams, eo_video_slots, state_suffix="_eo", detect=True)
    ran_loop = True
if tir_active_cams:
    run_playback_loop(tir_active_cams, tir_video_slots, state_suffix="_tir", detect=True)
    ran_loop = True
if ran_loop:
    st.rerun()