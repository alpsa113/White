"""views/logs.py — 페이지2: 감지 기록 관리. 조회/편집 탭을 조립합니다(편집은 admin 전용)."""
import streamlit as st

from ui.log_tabs import render_view_tab, render_manage_tab
from ui.styles import PAGE_PADDING_CSS


def render() -> None:
    """감지 기록 페이지 전체를 렌더링합니다."""
    ss = st.session_state

    st.markdown(PAGE_PADDING_CSS, unsafe_allow_html=True)

    if not ss.detection_logs:
        st.info("현재 기록된 탐지 데이터가 없습니다.")
        return

    sorted_logs = sorted(
        ss.detection_logs,
        key=lambda a: (
            a.get("created_at") or f"{a.get('date', '')} {a.get('time', '')}",
            a.get("id", 0)
        ),
        reverse=True,
    )

    if ss.role == "admin":
        tab_view, tab_manage = st.tabs(["로그 및 클립 조회", "로그 편집 및 삭제"])
        with tab_manage:
            render_manage_tab(sorted_logs)
    else:
        (tab_view,) = st.tabs(["로그 및 클립 조회"])

    with tab_view:
        render_view_tab(sorted_logs)
