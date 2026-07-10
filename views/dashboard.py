"""views/dashboard.py — 페이지1: 관제 대시보드 ('실시간 감시'). 헤더 시계 + 카메라 그리드/스포트라이트 + 우측 미니맵/탐지 이력 패널을 조립합니다."""
import streamlit as st

from services.camera_registry import get_valid_area_options, compute_grid_columns
from ui.camera.toolbar import render_header_clock, consume_pending_camera_switch
from ui.camera.grid import render_camera_grid
from ui.camera.spotlight import render_camera_spotlight
from ui.camera.detection_panel import render_detection_panel
from ui.outposts.marker_overlay import selected_ids
from ui.outposts.viewer import render_map


def render(cameras: list[dict]) -> dict:
    """관제 대시보드 페이지 전체를 렌더링하고, 채운 video_slots를 반환합니다(재생 루프는 app.py가 호출)."""
    consume_pending_camera_switch()
    get_valid_area_options(cameras)

    video_slots = {}

    render_header_clock()

    main_col, panel_col = st.columns([4, 1.1])

    with main_col:
        map_selected = selected_ids()
        if map_selected:
            filtered = [c for c in cameras if c["id"] in map_selected] or cameras
            render_camera_grid(filtered, video_slots, cols_per_row=compute_grid_columns(len(filtered)))
        elif st.session_state["selected_cam"] == "전체 구역":
            render_camera_grid(cameras, video_slots, cols_per_row=compute_grid_columns(len(cameras)))
        else:
            render_camera_spotlight(cameras, st.session_state["selected_cam"], video_slots)

    with panel_col:
        with st.container(key="minimap_section"):
            st.markdown(
                '<style>div[class*="st-key-minimap_section"] '
                'div[data-testid="stVerticalBlock"] { gap: 0.15rem !important; }</style>',
                unsafe_allow_html=True,
            )
            st.markdown("**초소 위치**")
            render_map(cameras)
        render_detection_panel()

    return video_slots
