"""ui/layout.py — 사이드바 네비게이션(HEIMDALL 다크 테마, 로고/야경 배경 + 아이콘 버튼) 렌더링."""
import base64
from pathlib import Path

import streamlit as st

from ui.styles import BUTTON_NOWRAP_CSS, GLOBAL_APP_BG_CSS, SIDEBAR_THEME_CSS_TEMPLATE

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
_SIDEBAR_LOGO_PATH = _ASSETS_DIR / "sidebar_logo.png"
_SIDEBAR_SCENE_PATH = _ASSETS_DIR / "sidebar_scene.png"


@st.cache_data(show_spinner=False)
def _image_base64(path: Path) -> str:
    """이미지를 base64로 인코딩합니다(캐시되어 재렌더링마다 다시 읽지 않음)."""
    return base64.b64encode(path.read_bytes()).decode()


def _inject_theme_css() -> None:
    """사이드바 배경(야경 이미지) + 전역 다크 배경 스타일을 주입합니다."""
    st.markdown(BUTTON_NOWRAP_CSS, unsafe_allow_html=True)
    st.markdown(GLOBAL_APP_BG_CSS, unsafe_allow_html=True)
    st.markdown(
        SIDEBAR_THEME_CSS_TEMPLATE.format(scene_b64=_image_base64(_SIDEBAR_SCENE_PATH)),
        unsafe_allow_html=True,
    )


def _render_logo() -> None:
    """로고를 실제 <img> 요소로 렌더링합니다(사이드바 폭에 관계없이 항상 정확한 비율)."""
    with st.container(key="sidebar_logo"):
        st.markdown(
            f'<img src="data:image/png;base64,{_image_base64(_SIDEBAR_LOGO_PATH)}">',
            unsafe_allow_html=True,
        )


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


def _nav_button(label: str, *, page: str, icon: str) -> None:
    """페이지 전환 버튼 1개. 현재 페이지면 강조(primary) 스타일로 표시됩니다."""
    ss = st.session_state
    if st.button(
        label, key=f"_nav_{page}", icon=icon, use_container_width=True,
        type="primary" if ss.current_page == page else "secondary",
    ):
        ss.current_page = page
        st.rerun()


def render_sidebar() -> None:
    """사이드바 전체(로고/야경 배경 + 실시간 감시·감지 기록·설정, 맨 아래 계정·로그아웃)를 렌더링합니다."""
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")
    _inject_theme_css()

    with st.sidebar:
        _render_logo()

        _nav_button("실시간 감시", page="관제 대시보드", icon=":material/videocam:")
        _nav_button("감지 기록", page="감지 기록", icon=":material/list_alt:")
        _nav_button("설정", page="설정", icon=":material/settings:")

        _render_db_write_warning()

        with st.container(key="sidebar_footer"):
            role_label = "관리자" if ss.role == "admin" else "병사"
            with st.container(key="sidebar_account"):
                st.caption(f"{ss.get('username', '')} · {role_label}")

            if st.button("로그아웃", icon=":material/logout:", use_container_width=True):
                _do_logout()
