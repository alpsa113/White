"""ui/camera/spotlight.py — 포커스된 카메라 1개를 크게 보여주는 집중 보기 레이아웃."""
import streamlit as st

from ui.camera.card import render_camera_card


def render_camera_spotlight(cameras: list[dict], focused_name: str, video_slots: dict) -> None:
    """focused_name 카메라를 크게 보여줍니다. 못 찾으면 안내 메시지만 표시합니다."""
    focused = next((c for c in cameras if c["name"] == focused_name), None)

    if focused:
        render_camera_card(focused, video_slots)
    else:
        st.info("선택된 카메라를 찾을 수 없습니다.")
