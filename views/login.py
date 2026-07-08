"""
views/login.py — 페이지0: 로그인

현재 구현된 페이지들(관제 대시보드/탐지 데이터 로그/설정) 앞단에 위치하는
진입 화면입니다. 서비스명 + ID 입력 + PW 입력 + 로그인 버튼만 배치합니다.

인증 성공 시 session_state.authenticated/role/username을 채우고 rerun하여
이후 페이지로 넘어갑니다. app.py는 authenticated가 False인 동안 이 화면만
그리고 st.stop()으로 종료하므로, 사이드바(ui.layout.render_sidebar)나 카메라
재생 로직은 로그인 전에는 전혀 실행되지 않습니다.

계정 정보는 config.USERS에 평문으로 하드코딩되어 있습니다 (데모/내부망용).
"""
import streamlit as st

from config import USERS


def render() -> None:
    """로그인 화면 전체를 렌더링합니다."""
    ss = st.session_state

    # 화면 중앙에 좁은 폭으로 배치 — 좌우 여백은 빈 컬럼으로 확보
    _, center, _ = st.columns([1, 1.1, 1])
    with center:
        st.markdown(
            "<div style='text-align:center; font-size:1.6rem; font-weight:700; "
            "margin:4rem 0 2rem;'>GOP 통합 감시 시스템</div>",
            unsafe_allow_html=True,
        )

        username = st.text_input("ID", key="_login_id_widget")
        password = st.text_input("PW", type="password", key="_login_pw_widget")

        if st.button("로그인", use_container_width=True, type="primary"):
            _try_login(username, password)


def _try_login(username: str, password: str) -> None:
    """입력값을 config.USERS와 대조해 인증하고, 성공 시 세션 상태를 채웁니다."""
    ss = st.session_state
    user = USERS.get(username)

    if user is None or user["password"] != password:
        st.error("ID 또는 비밀번호가 올바르지 않습니다.")
        return

    ss.authenticated = True
    ss.role = user["role"]
    ss.username = username
    st.rerun()  # 로그인 직후 바로 다음 화면(사이드바 + 페이지)으로 전환
