"""
ui/layout.py — 사이드바 네비게이션(브랜드명/페이지 전환/계정 영역) 렌더링

모든 페이지에 공통으로 나타나는 영역을 담당합니다. 이 파일은 render_sidebar()
하나만 외부(app.py)에 노출하며, 나머지 함수는 그 안에서만 쓰이는 내부 헬퍼입니다.
CCTV 화면이 메인 영역 최상단에 붙을 수 있도록, 페이지 전환/계정 영역은 모두
st.sidebar에 그립니다.

RDS/S3 연결 상태뱃지와 실시간 시계는 더 이상 이 사이드바에 없습니다 — 상태뱃지는
완전히 제거되었고, 시계는 '실시간 감시' 페이지 상단(카메라 화면 헤더 행)으로
옮겨졌습니다 (ui/camera/toolbar.py 참고).
"""
import streamlit as st

from utils.formatters import fmt_dt
from ui.styles import BUTTON_NOWRAP_CSS, BRAND_TITLE_STYLE

# 계정 영역(하단 고정)을 사이드바 맨 아래로 밀어내는 CSS — 사이드바 콘텐츠
# 영역을 세로 flex로 만들고, 계정 영역 컨테이너에 margin-top:auto를 줘서
# "실시간 감시"/"감지 기록" 버튼과는 항상 간격을 두고 하단에 붙게 합니다.
# stSidebarContent(바깥)와 stSidebarUserContent(안쪽, 우리 위젯이 실제로
# 그려지는 곳) 양쪽 모두에 flex+최소높이를 줘야 어느 쪽이 실제 스크롤
# 컨테이너 역할을 하든 안정적으로 맨 아래까지 밀립니다.
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


def _render_recent_alerts() -> None:
    """최근 사람 탐지 중 가장 마지막 건을 라벨로 보여주고, 클릭해서 펼치면
    최근 목록 전체를 보여줍니다. 탐지 일시 등은 detection_logs에서 그대로
    가져와 표시할 뿐, 별도로 시각을 다시 계산하지 않습니다."""
    ss = st.session_state
    recent_ids = list(ss.get("recent_person_alert_ids", []))
    if not recent_ids:
        return

    logs_by_id = {a["id"]: a for a in ss.detection_logs}
    recent_logs = [logs_by_id[aid] for aid in reversed(recent_ids) if aid in logs_by_id]
    if not recent_logs:
        return

    latest = recent_logs[0]
    label = f"최근 탐지: {latest['camera']} · {latest['class_name']} · {fmt_dt(latest)[-8:]}"

    with st.expander(label, expanded=False):
        for a in recent_logs:
            st.caption(f"{fmt_dt(a)} · {a['camera']} · {a['class_name']}")


def _render_db_write_warning() -> None:
    """RDS/S3 기록 실패 시에만(services/alerts.py, clip_recorder.py, state.py가
    남겨둔 경고) 배너로 보여줍니다. 상시 노출되던 연결 상태 뱃지(🟢/🟡)는
    제거되었지만, 실제 쓰기 실패는 놓치면 안 되는 정보라 그대로 유지합니다."""
    ss = st.session_state
    if ss.get("db_write_warning"):
        st.error(f"⚠️ {ss.pop('db_write_warning')}")


def _do_logout() -> None:
    """계정 관련 상태만 초기화 — detection_logs 등 나머지 세션 데이터는 그대로 둡니다."""
    ss = st.session_state
    ss.authenticated = False
    ss.role = None
    ss.username = None
    st.rerun()


def _render_account_section() -> None:
    """계정 정보(아이디·권한) + 로그아웃/설정 버튼. 사이드바 맨 아래 고정 영역에
    노출됩니다. "설정" 페이지는 이제 admin/user 모두 접근 가능해서(조회 전용
    으로 제한되는 항목은 views/settings.py·ui/outposts/editor.py가 처리),
    로그아웃/설정 버튼은 두 role 모두 한 행에 반반씩 보여줍니다."""
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
    """사이드바 전체를 렌더링합니다 — 브랜드명, 페이지 전환 버튼(role에 따라
    노출 범위가 다름), 최근 탐지 배너, 계정 정보/로그아웃/설정을 이 함수
    하나에서 조립합니다.

    이 함수는 반드시 session_state.authenticated가 True일 때만 호출되어야
    합니다 (app.py가 로그인 게이트에서 이를 보장합니다).

    현재 선택된 페이지는 session_state.current_page에 저장되어 rerun 후에도 유지됩니다.
    """
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")
    st.markdown(BUTTON_NOWRAP_CSS, unsafe_allow_html=True)
    st.markdown(SIDEBAR_FOOTER_CSS, unsafe_allow_html=True)

    with st.sidebar:
        # 브랜드명 — 사이드바 최상단에 항상 고정 노출.
        st.markdown(
            f"<div style='{BRAND_TITLE_STYLE}'>GOP 통합 감시 시스템</div>",
            unsafe_allow_html=True,
        )

        # 페이지 전환 버튼 — "설정"은 이 목록에서 빠지고 계정 영역(하단)으로
        # 옮겨졌습니다 (로그아웃과 한 행에 반반씩 배치, admin/user 공통).
        #
        # 권한별 노출 범위:
        #   "실시간 감시" / "감지 기록" / "설정" 모두 admin·user 공통으로 접근
        #   가능합니다. 다만 "감지 기록" 안의 편집 탭(views/logs.py)과 "설정"
        #   안의 초소 마커 추가/영상 매핑/선택/삭제·데모 모드(ui/outposts/editor.py,
        #   views/settings.py)는 admin에게만 보이고, user는 조회만 할 수 있습니다.
        if st.button("실시간 감시", use_container_width=True,
                     type="primary" if ss.current_page == "관제 대시보드" else "secondary"):
            ss.current_page = "관제 대시보드"
            st.rerun()  # 클릭 즉시 페이지 전환이 반영되도록 강제 재실행
        if st.button("감지 기록", use_container_width=True,
                     type="primary" if ss.current_page == "감지 기록" else "secondary"):
            ss.current_page = "감지 기록"
            st.rerun()

        _render_recent_alerts()
        _render_db_write_warning()

        # 계정 정보 + 로그아웃/설정 — SIDEBAR_FOOTER_CSS가 이 컨테이너를
        # 사이드바 맨 아래로 밀어내 위 나머지 페이지 버튼들과 간격을 둡니다.
        with st.container(key="sidebar_footer"):
            st.divider()
            _render_account_section()
