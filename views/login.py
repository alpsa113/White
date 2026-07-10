"""views/login.py — 페이지0: 로그인. ID/PW + 사용자 유형이 계정의 실제 role과 일치해야 인증됩니다."""
import streamlit as st

from config import USERS, USER_TYPE_OPTIONS, DEFAULT_LANDING_PAGE


def render() -> None:
    """로그인 화면 전체를 렌더링합니다."""
    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        st.markdown(
            "<div style='text-align:center; font-size:1.6rem; font-weight:700; "
            "margin:4rem 0 2rem;'>GOP 통합 감시 시스템</div>",
            unsafe_allow_html=True,
        )

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
