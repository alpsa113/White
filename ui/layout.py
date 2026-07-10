"""ui/layout.py — 사이드바 네비게이션(브랜드명/페이지 전환/계정 영역) 렌더링."""
import streamlit as st

from ui.styles import BUTTON_NOWRAP_CSS, BRAND_TITLE_STYLE

# 계정 영역을 사이드바 맨 아래로 고정하는 CSS
SIDEBAR_FOOTER_CSS = """
<style>
div[data-testid="stSidebarContent"],
div[data-testid="stSidebarUserContent"] {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    height: 100%;
}
div[class*="st-key-sidebar_footer"] {
    margin-top: auto;
    padding-top: 1.5rem;
}
</style>
"""


def _render_db_write_warning() -> None:
    """RDS/S3 기록 실패 경고가 있으면 배너로 표시합니다."""
    ss = st.session_state
    if ss.get("db_write_warning"):
        st.error(f"⚠️ {ss.pop('db_write_warning')}")


def _do_logout() -> None:
    """계정 관련 상태만 초기화합니다."""
    ss = st.session_state
    ss.authenticated = False
    ss.role = None
    ss.username = None
    st.rerun()


def _render_account_section() -> None:
    """계정 정보 + 로그아웃/설정 버튼."""
    ss = st.session_state
    role_label = "관리자" if ss.role == "admin" else "병사"
    st.caption(f"👤 {ss.get('username', '')} · {role_label}")

    col_logout, col_settings = st.columns(2)
    with col_logout:
        if st.button("로그아웃", use_container_width=True):
            _do_logout()
    with col_settings:
        if st.button("설정", use_container_width=True,
                     type="primary" if ss.current_page == "설정" else "secondary"):
            ss.current_page = "설정"
            st.rerun()


def render_sidebar() -> None:
    """사이드바 전체(브랜드명/페이지 전환/계정 영역)를 렌더링합니다."""
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")
    st.markdown(BUTTON_NOWRAP_CSS, unsafe_allow_html=True)
    st.markdown(SIDEBAR_FOOTER_CSS, unsafe_allow_html=True)

    with st.sidebar:
        st.markdown(
            f"<div style='{BRAND_TITLE_STYLE}'>GOP 통합 감시 시스템</div>",
            unsafe_allow_html=True,
        )

        if st.button("실시간 감시", use_container_width=True,
                     type="primary" if ss.current_page == "관제 대시보드" else "secondary"):
            ss.current_page = "관제 대시보드"
            st.rerun()
        if st.button("감지 기록", use_container_width=True,
                     type="primary" if ss.current_page == "감지 기록" else "secondary"):
            ss.current_page = "감지 기록"
            st.rerun()

        _render_db_write_warning()

        with st.container(key="sidebar_footer"):
            st.divider()
            _render_account_section()
