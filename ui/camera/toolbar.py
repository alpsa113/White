"""
ui/camera/toolbar.py — 대시보드 카메라 제어 위젯 모음 (사이드바 렌더링)

제목과 구역 선택 드롭다운을 사이드바에 순서대로 조립합니다. CCTV 화면이
메인 영역 최상단에 붙을 수 있도록 메인 영역에는 아무것도 그리지 않습니다.
views/dashboard.py는 render_dashboard_header() 하나만 호출하면 됩니다
(대시보드 페이지가 활성화되어 있을 때만 사이드바에 이 위젯들이 나타남).

과거에는 "카메라 개수" +/- 스텝퍼가 여기 있었지만, 이제 카메라 개수는 설정
페이지에서 지도에 마킹한 초소 개수로 자동 결정되므로(services/outposts.py)
제거되었습니다.
"""
import streamlit as st


def consume_pending_camera_switch() -> None:
    """예약된 구역 전환 요청을 드롭다운 위젯이 그려지기 전에 반영합니다."""
    ss = st.session_state
    pending = ss.pop("_pending_selected_cam", None)
    if pending is not None:
        ss["selected_cam"] = pending
        ss["_selected_cam_widget"] = pending  # 위젯이 이미 그려진 뒤엔 index/value가 무시되므로 key값을 직접 맞춰둠


def _sync_selected_cam() -> None:
    """드롭다운의 변경값을 실제 상태 키(selected_cam)로 복사.
    카메라 제목 버튼(ui/camera/card.py)도 이 실제 키를 직접 읽고 씁니다."""
    st.session_state["selected_cam"] = st.session_state["_selected_cam_widget"]


def render_dashboard_header(valid_options: list[str]) -> bool:
    """대시보드 사이드바 컨트롤(제목 + 구역 선택)을 렌더링하고, 현재 '전체 구역'
    (그리드) 모드인지 여부를 반환합니다.
    (기존에는 메인 영역 상단 3분할 헤더였으나, CCTV 화면을 최상단에 붙이기
    위해 사이드바로 이동 — 함수명/시그니처/반환값은 그대로 유지합니다.)

    권한별 노출 범위: 구역 선택은 admin/user 공통입니다. 카메라 개수는 더 이상
    이 화면에서 조절하지 않고, 설정 페이지의 초소 마킹 개수로 자동 결정됩니다."""
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

    return is_grid_mode
