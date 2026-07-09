"""
views/dashboard.py — 페이지1: 관제 대시보드

폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은 위치에
"pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을 별도 페이지로
등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립 실행용 페이지가 아니라
render() 함수만 노출하는 모듈이므로, 그 자동 동작과 충돌하지 않도록 폴더명을
"views"로 정했습니다. 반드시 app.py에서 import하여 호출하는 방식으로만 사용하세요.

카메라 목록 준비는 services/camera_registry.py, 제어 위젯(구역 선택)은
ui/camera/toolbar.py가 사이드바에 렌더링하고, 카드 배치는 ui/camera/grid.py·
spotlight.py에 위임하고, 이 파일은 배치 순서만 조립합니다 (render()가 영상
재생 등으로 아주 자주 재실행되므로, 로직은 최대한 다른 모듈에 둡니다).

화면 구성 — 탭 2개입니다:
    "카메라 화면" 탭 → 그리드/스포트라이트 2가지 (기존과 동일)
        "전체 구역" 선택 시           → 그리드 (ui.camera.grid)
        특정 카메라 선택 시(자동/수동) → 스포트라이트, Zoom 발표자 화면처럼 큰 화면 +
                                       나머지 썸네일 (ui.camera.spotlight)
    "관제 지도" 탭 → 왼쪽에 카메라 화면 요약, 오른쪽에 설정 페이지에서 마킹한
                    초소 지도 (ui.outposts.viewer). 사람이 탐지된 카메라의
                    마커가 점멸합니다.
별도 페이지가 아니라 탭으로 추가한 이유: 이 시스템은 사이드바 페이지 3개
(실시간 감시/관리자 로그/설정)로 이미 구조가 고정되어 있고, "관제 지도"는
"실시간 감시"의 또 다른 보기 방식일 뿐 독립된 관리 대상이 아니므로, 페이지를
늘려 권한 분기를 새로 만들기보다 이 페이지 안에서 탭으로 흡수하는 편이
기존 설계 원칙에 더 맞습니다.

사람이 새로 탐지되면 services/playback.py가 _pending_selected_cam을 예약해
자동으로 그 카메라의 스포트라이트로 전환시킵니다 (consume_pending_camera_switch가 반영).
"""
import streamlit as st

from services.camera_registry import get_valid_area_options, compute_grid_columns
from ui.camera.toolbar import render_dashboard_header, consume_pending_camera_switch
from ui.camera.grid import render_camera_grid
from ui.camera.spotlight import render_camera_spotlight
from ui.outposts.viewer import render_outpost_map


def render(cameras: list[dict]) -> dict:
    """관제 대시보드 페이지 전체를 렌더링합니다.

    cameras는 app.py가 미리 계산해서 넘겨줍니다 — 카메라 목록/재생 상태는
    이 페이지가 화면에 보이든 안 보이든 항상 계산되어야, 다른 페이지를 보는
    동안에도 탐지가 계속 이루어질 수 있기 때문입니다. 이 함수는 카드를 그리며
    채운 video_slots를 반환하고, 실제 재생 루프 호출은 app.py가 담당합니다.

    video_slots는 "카메라 화면" 탭에서만 채워집니다 — "관제 지도" 탭은 읽기
    전용 요약(ui.outposts.viewer)만 보여주고 재생 루프에 직접 연결되지
    않으므로, 같은 카메라 카드를 두 탭에 중복으로 그려 위젯 key가 충돌하는
    문제를 피할 수 있습니다.
    """
    ss = st.session_state

    consume_pending_camera_switch()
    valid_options = get_valid_area_options(cameras)

    video_slots = {}

    is_grid_mode = render_dashboard_header(valid_options)

    tab_camera, tab_map = st.tabs(["카메라 화면", "관제 지도"])
    with tab_camera:
        if is_grid_mode:
            # 정사각형에 가깝게 자동 계산된 열 수로 그리드 렌더링
            render_camera_grid(cameras, video_slots, cols_per_row=compute_grid_columns(len(cameras)))
        else:
            # 선택된 카메라를 좌측에 크게, 나머지는 우측에 썸네일로 (Zoom 회의 발표자 화면 스타일)
            render_camera_spotlight(cameras, ss["selected_cam"], video_slots)

    with tab_map:
        render_outpost_map(cameras)

    return video_slots
