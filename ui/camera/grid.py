"""
ui/camera/grid.py — 카메라 카드를 그리드 또는 집중 보기로 배치

카드 자체(render_camera_card)는 ui/camera/card.py에 있고, 이 파일은
"몇 개를 어떤 열 수로, 혹은 1개만 크게 배치할지"만 결정합니다.
"""
import streamlit as st

from ui.camera.card import render_camera_card


def render_camera_grid(cameras: list[dict], video_slots: dict, cols_per_row: int) -> None:
    """cameras 목록을 cols_per_row(한 줄당 카메라 수)에 맞춰 그리드 형태로 렌더링합니다.
    카메라 개수가 cols_per_row로 나누어 떨어지지 않아도 마지막 줄은 남은 개수만큼만 채웁니다."""
    cols_per_row = max(1, min(cols_per_row, len(cameras)))  # 카메라 수보다 열이 많아지는 경우를 방지
    for row_start in range(0, len(cameras), cols_per_row):
        row_cams = cameras[row_start: row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, cam in zip(cols, row_cams):
            with col:
                render_camera_card(cam, video_slots)
