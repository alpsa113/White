"""views/login.py — 페이지0: 로그인. ID/PW + 사용자 유형이 계정의 실제 role과 일치해야 인증됩니다."""
import base64
from pathlib import Path

import streamlit as st

from config import USERS, USER_TYPE_OPTIONS, DEFAULT_LANDING_PAGE
from ui.styles import LOGIN_BACKGROUND_CSS_TEMPLATE

_BG_IMAGE_PATH = Path(__file__).resolve().parent.parent / "assets" / "heimdall_top.png"


@st.cache_data(show_spinner=False)
def _bg_image_base64() -> str:
    """배경 이미지를 base64로 인코딩합니다(캐시되어 재렌더링마다 다시 읽지 않음)."""
    return base64.b64encode(_BG_IMAGE_PATH.read_bytes()).decode()


def _inject_background_css() -> None:
    """HEIMDALL 배경 이미지 + 로그인 패널 스타일을 주입합니다."""
    st.markdown(
        LOGIN_BACKGROUND_CSS_TEMPLATE.format(bg_b64=_bg_image_base64()),
        unsafe_allow_html=True,
    )


def render() -> None:
    """로그인 화면 전체를 렌더링합니다."""
    _inject_background_css()

    with st.container(key="login_panel"):
        username = st.text_input("ID", key="_login_id_widget")
        type_label = st.selectbox("사용자 유형", options=list(USER_TYPE_OPTIONS.keys()), key="_login_type_widget")
        password = st.text_input("PW", type="password", key="_login_pw_widget")

        if st.button("로그인", use_container_width=True, type="primary"):
            _try_login(username, password, USER_TYPE_OPTIONS[type_label])


def _try_login(username: str, password: str, selected_role: str) -> None:
    """config.USERS와 대조해 인증하고, 성공 시 세션 상태를 채웁니다."""
    ss = st.session_state
    user = USERS.get(username)

    if user is None or user["password"] != password or user["role"] != selected_role:
        st.error("ID, 비밀번호 또는 사용자 유형이 올바르지 않습니다.")
        return

    ss.authenticated = True
    ss.role = user["role"]
    ss.username = username
    ss.current_page = DEFAULT_LANDING_PAGE.get(user["role"], "관제 대시보드")
    st.rerun()
