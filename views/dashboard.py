"""
views/dashboard.py — 페이지1: 관제 대시보드

폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은 위치에
"pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을 별도 페이지로
등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립 실행용 페이지가 아니라
render() 함수만 노출하는 모듈이므로, 그 자동 동작과 충돌하지 않도록 폴더명을
"views"로 정했습니다. 반드시 app.py에서 import하여 호출하는 방식으로만 사용하세요.

카메라 목록 준비는 services/camera_registry.py, 헤더 위젯은
ui/camera/toolbar.py, 카드 배치는 ui/camera/grid.py, 팝업 처리는
ui/dialogs.py에 위임하고, 이 파일은 배치 순서만 조립합니다 (render()가
영상 재생 등으로 아주 자주 재실행되므로, 로직은 최대한 다른 모듈에 둡니다).
"""
import streamlit as st

from services.playback import run_playback_loop
from services.camera_registry import get_active_cameras, get_valid_area_options, compute_grid_columns
from ui.camera.toolbar import render_dashboard_header, consume_pending_camera_switch
from ui.camera.grid import render_camera_grid, render_camera_focus
from ui.alert_panel import render_alert_panel
from ui.dialogs import handle_pending_popup


def render() -> None:
    """관제 대시보드 페이지 전체를 렌더링합니다."""
    ss = st.session_state

    consume_pending_camera_switch()
    cameras = get_active_cameras()
    valid_options = get_valid_area_options(cameras)

    video_slots = {}

    # 좌측(카메라 영역) : 우측(경보 패널) = 6 : 1 비율로 화면을 분할
    left_col, right_col = st.columns([6, 1])

    with left_col:
        is_grid_mode = render_dashboard_header(cameras, valid_options)
        if is_grid_mode:
            # 정사각형에 가깝게 자동 계산된 열 수로 그리드 렌더링
            render_camera_grid(cameras, video_slots, cols_per_row=compute_grid_columns(len(cameras)))
        else:
            # 특정 카메라 1개만 전체 너비로 확대 표시
            render_camera_focus(cameras, ss["selected_cam"], video_slots)

    with right_col:
        render_alert_panel()

    handle_pending_popup()

    # 재생 중인 카메라가 있으면 여기서 반복문이 넘겨받아 계속 프레임을 갱신합니다.
    active_cams = [cam for cam in cameras if ss.get(f"playing_{cam['id']}")]
    if active_cams:
        run_playback_loop(active_cams, video_slots, {})