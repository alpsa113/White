"""
ui/camera/toolbar.py — 대시보드 카메라 제어 위젯 모음 (사이드바 렌더링)

제목, 구역 선택 드롭다운, 카메라 개수 스텝퍼를 사이드바에 순서대로 조립합니다.
CCTV 화면이 메인 영역 최상단에 붙을 수 있도록 메인 영역에는 아무것도 그리지
않습니다. views/dashboard.py는 render_dashboard_header() 하나만 호출하면
됩니다 (대시보드 페이지가 활성화되어 있을 때만 사이드바에 이 위젯들이 나타남).
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
    st.sidebar.number_input(
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
    """대시보드 사이드바 컨트롤(제목 + 구역 선택 + 카메라 개수)을 렌더링하고,
    현재 '전체 구역'(그리드) 모드인지 여부를 반환합니다.
    (기존에는 메인 영역 상단 3분할 헤더였으나, CCTV 화면을 최상단에 붙이기
    위해 사이드바로 이동 — 함수명/시그니처/반환값은 그대로 유지합니다.)

    권한별 노출 범위: 구역 선택은 admin/user 공통, 카메라 개수는 admin 전용입니다."""
    ss = st.session_state
    is_grid_mode = ss["selected_cam"] == "전체 구역"

    st.sidebar.markdown("**라이브 카메라 피드**")

    current = ss.get("selected_cam", "전체 구역")
    st.sidebar.selectbox(
        "구역 선택",
        options=valid_options,
        index=valid_options.index(current) if current in valid_options else 0,
        key="_selected_cam_widget",
        on_change=_sync_selected_cam,
        label_visibility="visible",
    )
    if ss.get("role") == "admin":
        _render_camera_count_selector()

    return is_grid_mode
