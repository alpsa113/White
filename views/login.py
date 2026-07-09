"""
views/login.py — 페이지0: 로그인

현재 구현된 페이지들(관제 대시보드/탐지 데이터 로그/설정) 앞단에 위치하는
진입 화면입니다. 서비스명 + ID 입력 + 사용자 유형 선택 + PW 입력 + 로그인
버튼을 배치합니다.

"사용자 유형" 드롭다운은 단순 표시용이 아니라 실제 인증 조건의 일부입니다 —
ID/PW가 일치하더라도 여기서 고른 유형이 계정의 실제 role과 다르면 로그인이
거부됩니다 (예: user 계정으로 "관리자"를 선택하고 로그인 시도). 이는 관리자와
사용자가 물리적으로 같은 로그인 화면을 공유하는 관제 환경에서, 실수로 잘못된
권한으로 로그인하는 것을 화면 단에서부터 한 번 더 방지하기 위함입니다.

인증 성공 시 session_state.authenticated/role/username을 채우고, role에 맞는
기본 페이지(config.DEFAULT_LANDING_PAGE)로 current_page를 지정한 뒤 rerun하여
다음 화면으로 넘어갑니다. app.py는 authenticated가 False인 동안 이 화면만
그리고 st.stop()으로 종료하므로, 사이드바(ui.layout.render_sidebar)나 카메라
재생 로직은 로그인 전에는 전혀 실행되지 않습니다.

계정 정보는 config.USERS에 평문으로 하드코딩되어 있습니다 (데모/내부망용).
"""
import streamlit as st

from config import USERS, USER_TYPE_OPTIONS, DEFAULT_LANDING_PAGE


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
        type_label = st.selectbox("사용자 유형", options=list(USER_TYPE_OPTIONS.keys()), key="_login_type_widget")
        password = st.text_input("PW", type="password", key="_login_pw_widget")

        if st.button("로그인", use_container_width=True, type="primary"):
            _try_login(username, password, USER_TYPE_OPTIONS[type_label])


def _try_login(username: str, password: str, selected_role: str) -> None:
    """입력값을 config.USERS와 대조해 인증하고, 성공 시 세션 상태를 채웁니다.
    ID/PW가 맞아도 selected_role(사용자 유형 드롭다운)이 계정의 실제 role과
    다르면 인증을 거부합니다."""
    ss = st.session_state
    user = USERS.get(username)

    if user is None or user["password"] != password or user["role"] != selected_role:
        st.error("ID, 비밀번호 또는 사용자 유형이 올바르지 않습니다.")
        return

    ss.authenticated = True
    ss.role = user["role"]
    ss.username = username
    # role별 기본 랜딩 페이지로 진입 — 관리자는 초소/카메라 설정을 먼저 확인.
    ss.current_page = DEFAULT_LANDING_PAGE.get(user["role"], "관제 대시보드")
    st.rerun()  # 로그인 직후 바로 다음 화면(사이드바 + 페이지)으로 전환
