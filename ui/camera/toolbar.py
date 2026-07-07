"""
ui/camera/toolbar.py — 대시보드 헤더의 카메라 제어 위젯 모음

제목, 구역 선택 드롭다운, 카메라 개수 스텝퍼를 한 줄에 조립합니다.
views/dashboard.py는 render_dashboard_header() 하나만 호출하면 됩니다.
"""
import streamlit as st

from config import MAX_CAMERAS

def consume_pending_camera_switch() -> None:
    """예약된 구역 전환 요청을 드롭다운 위젯이 그려지기 전에 반영합니다."""
    ss = st.session_state
    pending = ss.pop("_pending_selected_cam", None)
    if pending is not None:
        ss["selected_cam"] = pending
        ss["_selected_cam_widget"] = pending  # 위젯이 이미 그려진 뒤엔 index/value가 무시되므로 key값을 직접 맞춰둠


def _sync_grid_count() -> None:
    """number_input(+/- 스텝퍼)의 변경값을 실제 상태 키(grid_count)로 복사하는 콜백."""
    # 위젯 key(_grid_count_widget)와 실제 상태 key(grid_count)를 분리한 이유:
    # 이 위젯은 '전체 구역'일 때만 그려지는데, Streamlit은 그려지지 않는 위젯의 key를 지우기 때문
    st.session_state["grid_count"] = st.session_state["_grid_count_widget"]


def _render_camera_count_selector() -> None:
    """총 카메라 개수 선택 UI (+/- 스텝퍼). 그리드/스포트라이트 모드 모두에서
    노출됩니다 — 스포트라이트에서도 이 값이 전체 카메라 목록(썸네일 포함)
    크기를 결정하기 때문입니다."""
    ss = st.session_state
    # step=1을 주면 Streamlit이 입력창 옆에 -/+ 버튼을 자동으로 붙여줍니다.
    st.number_input(
        "카메라 개수", min_value=1, max_value=MAX_CAMERAS, step=1,
        value=ss.get("grid_count", 4),
        key="_grid_count_widget", on_change=_sync_grid_count,
        label_visibility="visible",
    )


def _sync_selected_cam() -> None:
    """드롭다운의 변경값을 실제 상태 키(selected_cam)로 복사.
    카메라 제목 버튼(ui/camera/card.py)도 이 실제 키를 직접 읽고 씁니다."""
    st.session_state["selected_cam"] = st.session_state["_selected_cam_widget"]


def render_dashboard_header(valid_options: list[str]) -> bool:
    """대시보드 상단 헤더(제목 + 구역 선택 + 카메라 개수)를 렌더링하고,
    현재 '전체 구역'(그리드) 모드인지 여부를 반환합니다."""
    ss = st.session_state
    is_grid_mode = ss["selected_cam"] == "전체 구역"

    h1, h2, h3 = st.columns([2.8, 1.2, 1.5])

    with h1:
        st.markdown("**라이브 카메라 피드**")
    with h2:
        current = ss.get("selected_cam", "전체 구역")
        st.selectbox(
            "구역 선택",
            options=valid_options,
            index=valid_options.index(current) if current in valid_options else 0,
            key="_selected_cam_widget",
            on_change=_sync_selected_cam,
            label_visibility="visible",
        )
    with h3:
        _render_camera_count_selector()

    return is_grid_mode
