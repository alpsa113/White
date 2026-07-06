"""
ui/camera/reorder.py — 카메라 순서 드래그 정렬 위젯

카메라 이름표를 드래그로 정렬해 그리드 표시 순서를 바꾸는 UI입니다.
실제 순서 적용/저장은 services/camera_registry.py가 담당하고, 이 파일은
정렬 위젯 자체와 결과 반환만 책임집니다.
"""
import streamlit as st
from streamlit_sortables import sort_items


def render_camera_reorder(cameras: list[dict]) -> list[str] | None:
    """카메라 이름 목록을 드래그로 정렬합니다. 순서를 바꾸면 새 순서의 id
    리스트를, 변경이 없으면 None을 반환합니다."""
    name_to_id = {c["name"]: c["id"] for c in cameras}
    current_names = [c["name"] for c in cameras]

    st.caption("이름표를 드래그해서 순서를 바꾸세요.")
    # 기본 빨간색 대신 시스템 톤(짙은 남색 계열)에 맞춘 이름표 색상
    _sortable_style = """
    .sortable-item {
        background-color: transparent;
        border: 1px solid var(--text-color);
        color: var(--text-color);
    }
    """
    # ⚠️ 영상 재생 중에는 화면이 자주 rerun되어 이 컴포넌트가 불안정할 수 있음 — 재생을 멈춘 후 사용 권장
    sorted_names = sort_items(current_names, direction="horizontal", custom_style=_sortable_style)

    if sorted_names != current_names:
        return [name_to_id[n] for n in sorted_names]
    return None
