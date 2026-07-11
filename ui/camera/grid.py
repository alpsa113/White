"""ui/camera/grid.py — 카메라 카드를 그리드 열 수에 맞춰 배치합니다."""
import streamlit as st

from ui.camera.card import render_camera_card


def render_camera_grid(cameras: list[dict], video_slots: dict, cols_per_row: int, *, focused: bool = False) -> None:
    """cameras를 cols_per_row열 그리드로 렌더링합니다.

    focused=True면(지도 마커로 필터링된 경우) 각 카드가 일반 그리드 대신
    집중 보기와 같은 '전체 보기로 돌아가기' 컨트롤을 보여줍니다."""
    cols_per_row = max(1, min(cols_per_row, len(cameras)))
    for row_start in range(0, len(cameras), cols_per_row):
        row_cams = cameras[row_start: row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, cam in zip(cols, row_cams):
            with col:
                render_camera_card(cam, video_slots, is_focused=focused)
