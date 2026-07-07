"""
views/dashboard.py — 페이지1: 관제 대시보드

폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은 위치에
"pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을 별도 페이지로
등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립 실행용 페이지가 아니라
render() 함수만 노출하는 모듈이므로, 그 자동 동작과 충돌하지 않도록 폴더명을
"views"로 정했습니다. 반드시 app.py에서 import하여 호출하는 방식으로만 사용하세요.

카메라 목록 준비는 services/camera_registry.py, 헤더 위젯은
ui/camera/toolbar.py, 카드 배치는 ui/camera/grid.py·spotlight.py에 위임하고,
이 파일은 배치 순서만 조립합니다 (render()가 영상 재생 등으로 아주 자주
재실행되므로, 로직은 최대한 다른 모듈에 둡니다).

화면 구성 — 그리드/스포트라이트 2가지뿐입니다:
    "전체 구역" 선택 시           → 그리드 (ui.camera.grid)
    특정 카메라 선택 시(자동/수동) → 스포트라이트, Zoom 발표자 화면처럼 큰 화면 +
                                   나머지 썸네일 (ui.camera.spotlight)
사람이 새로 탐지되면 services/playback.py가 _pending_selected_cam을 예약해
자동으로 그 카메라의 스포트라이트로 전환시킵니다 (consume_pending_camera_switch가 반영).
"""
import streamlit as st

from services.camera_registry import get_valid_area_options, compute_grid_columns
from ui.camera.toolbar import render_dashboard_header, consume_pending_camera_switch
from ui.camera.grid import render_camera_grid
from ui.camera.spotlight import render_camera_spotlight


def render(cameras: list[dict]) -> dict:
    """관제 대시보드 페이지 전체를 렌더링합니다.

    cameras는 app.py가 미리 계산해서 넘겨줍니다 — 카메라 목록/재생 상태는
    이 페이지가 화면에 보이든 안 보이든 항상 계산되어야, 다른 페이지를 보는
    동안에도 탐지가 계속 이루어질 수 있기 때문입니다. 이 함수는 카드를 그리며
    채운 video_slots를 반환하고, 실제 재생 루프 호출은 app.py가 담당합니다.
    """
    ss = st.session_state

    consume_pending_camera_switch()
    valid_options = get_valid_area_options(cameras)

    video_slots = {}

    is_grid_mode = render_dashboard_header(valid_options)
    if is_grid_mode:
        # 정사각형에 가깝게 자동 계산된 열 수로 그리드 렌더링
        render_camera_grid(cameras, video_slots, cols_per_row=compute_grid_columns(len(cameras)))
    else:
        # 선택된 카메라를 좌측에 크게, 나머지는 우측에 썸네일로 (Zoom 발표자 화면 스타일)
        render_camera_spotlight(cameras, ss["selected_cam"], video_slots)
        
    return video_slots
