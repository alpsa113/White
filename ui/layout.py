"""
ui/layout.py — 사이드바, 상단 네비게이션, 실시간 시계 렌더링

모든 페이지에 공통으로 나타나는 헤더 영역을 담당합니다.
"""
from datetime import datetime

import streamlit as st


def render_sidebar() -> None:
    """좌측 사이드바 — 데모 모드 설정 및 DB 연결 상태 표시."""
    ss = st.session_state
    with st.sidebar:
        st.header("설정")
        # ↓↓↓ 데모 모드 전용 UI (제거 시 이 체크박스/슬라이더 블록 삭제) ↓↓↓
        ss["simulate"] = st.checkbox("데모 모드 (무작위 탐지)", value=ss.get("simulate", True))

        ss["person_ratio"] = st.slider(
            "사람 등장 비율",
            0.00, 1.00,
            value=ss.get("person_ratio", 0.50),
            step=0.01,
            disabled=not ss["simulate"]
        )
        # ↑↑↑ 데모 모드 전용 UI 끝 ↑↑↑

        st.divider()

        if ss.get("DB_ENABLED"):
            st.caption("🟢 RDS 연결됨 — 로그가 영구 저장됩니다.")
        else:
            st.caption("🟡 메모리 모드 — RDS 미연결 (로그는 재시작 시 사라짐).")
            if ss.get("_db_init_error"):
                with st.expander("RDS 연결 오류 보기"):
                    st.code(ss["_db_init_error"])

        if ss.get("db_write_warning"):
            st.warning(ss.pop("db_write_warning"))


@st.fragment(run_every=1)
def _render_clock() -> None:
    """1초마다 독립적으로 재실행되는 실시간 시계 (전체 페이지 rerun 없음)."""
    now = datetime.now()
    st.markdown(
        f"<div style='text-align:right; line-height:2.2'>"
        f"현재 시각<br>"
        f"{'오전' if now.hour < 12 else '오후'} "
        f"{now.strftime('%I:%M:%S')}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_topnav() -> None:
    """상단 중앙 네비게이션 — 페이지 전환 버튼 및 실시간 시계.

    선택된 페이지는 session_state에 저장되어 rerun 후에도 유지됩니다.
    """
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")

    nav_left, nav_center, nav_right = st.columns([3, 2, 3])
    with nav_left:
        st.subheader("GOP 통합 감시 시스템")
    with nav_center:
        tab1, tab2 = st.columns(2)
        with tab1:
            if st.button(
                "📡 실시간 감시",
                use_container_width=True,
                type="primary" if ss.current_page == "관제 대시보드" else "secondary",
            ):
                ss.current_page = "관제 대시보드"
                st.rerun()
        with tab2:
            if st.button(
                "🗂️ 관리자 로그",
                use_container_width=True,
                type="primary" if ss.current_page == "탐지 데이터 로그" else "secondary",
            ):
                ss.current_page = "탐지 데이터 로그"
                st.rerun()
    with nav_right:
        _render_clock()

    st.divider()
