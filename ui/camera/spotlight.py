"""
ui/camera/spotlight.py — 특정 카메라를 크게, 나머지를 작은 썸네일로 보여주는
Zoom 회의 스타일 레이아웃 (사람 탐지 시 자동 전환되는 화면).
"""
import streamlit as st

from ui.camera.card import render_camera_card

SPOTLIGHT_HEIGHT_PX = 700

def render_camera_spotlight(cameras: list[dict], focused_name: str, video_slots: dict) -> None:
    """focused_name에 해당하는 카메라를 좌측에 크게, 나머지 카메라는 우측에
    고정 높이 스크롤 영역 안에 작은 미니 그리드로 나열합니다. focused_name을 찾지 못하면(그리드 축소 등으로 사라진
    경우) 좌측을 비워두고 나머지만 보여줍니다."""
    focused = next((c for c in cameras if c["name"] == focused_name), None)
    others = [c for c in cameras if c["name"] != focused_name]

    main_col, thumb_col = st.columns([3, 1])
    with main_col:
        if focused:
            render_camera_card(focused, video_slots)
    with thumb_col:
        # height를 지정하면 Streamlit이 이 영역을 고정 높이로 만들고, 내용이
        # 넘치면 자동으로 세로 스크롤바를 붙여줍니다 (별도 CSS 불필요).
        with st.container(height=SPOTLIGHT_HEIGHT_PX, border=False):
            for cam in others:
                render_camera_card(cam, video_slots)