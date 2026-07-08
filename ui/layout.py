"""
ui/layout.py — 사이드바 네비게이션(브랜드명/페이지 전환/상태뱃지/실시간 시계) 렌더링

모든 페이지에 공통으로 나타나는 영역을 담당합니다. 이 파일은 render_sidebar()
하나만 외부(app.py)에 노출하며, 나머지 함수는 그 안에서만 쓰이는 내부 헬퍼입니다.
CCTV 화면이 메인 영역 최상단에 붙을 수 있도록, 페이지 전환/상태/시계는 모두
st.sidebar에 그립니다.
"""
from datetime import datetime

import streamlit as st

from utils.formatters import fmt_dt
from ui.styles import (
    BUTTON_NOWRAP_CSS, BRAND_TITLE_STYLE, STATUS_BADGE_STYLE,
    CLOCK_LABEL_STYLE, CLOCK_PERIOD_STYLE, CLOCK_TIME_STYLE,
)


def _render_status_badge() -> None:
    """RDS/S3 연결 상태를 사이드바에 상시 노출합니다.
    관제 시스템 특성상 "지금 로그가 실제로 저장되고 있는가"는 항상 눈에 보여야 하므로
    설정 페이지 안에 숨기지 않고 모든 화면에 고정 배치합니다."""
    ss = st.session_state
    db_label = "🟢 RDS 연결됨" if ss.get("DB_ENABLED") else "🟡 메모리 모드"
    s3_label = "🟢 S3 연결됨" if ss.get("S3_ENABLED") else "🟡 S3 미연결"
    st.markdown(
        f"<div style='{STATUS_BADGE_STYLE}'>{db_label}<br>{s3_label}</div>",
        unsafe_allow_html=True,
    )
    # RDS 갱신/저장 실패 시 services/alerts.py 등에서 이 키에 메시지를 남겨둡니다.
    # 몇 초 뒤 사라지는 토스트가 아니라 배너(st.error)로 표시하여 놓칠 위험을 줄입니다.
    if ss.get("db_write_warning"):
        st.error(f"⚠️ {ss.pop('db_write_warning')}")


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


@st.fragment(run_every=1)
def _render_clock() -> None:
    """1초마다 독립적으로 재실행되는 실시간 시계 컴포넌트입니다. fragment
    덕분에 전체 페이지가 아니라 이 부분만 갱신되어 다른 UI에 영향을 주지
    않습니다. 사이드바 폭이 좁으므로 시계와 최근 탐지 배너를 세로로 배치합니다.

    주의: st.fragment로 감싼 함수 내부에서는 st.sidebar.xxx를 직접 호출할 수
    없습니다 (StreamlitAPIException). 대신 이 함수는 일반 st.xxx만 쓰고,
    호출하는 쪽(render_sidebar)에서 `with st.sidebar:` 컨텍스트 안에서
    이 함수를 호출해야 사이드바에 그려집니다."""
    now = datetime.now()
    st.markdown(
        f"<div style='text-align:left; line-height:1.6;'>"
        f"<span style='{CLOCK_LABEL_STYLE}'>현재 시각:</span> &nbsp;"
        f"<span style='{CLOCK_PERIOD_STYLE}'>"
        f"{'오전' if now.hour < 12 else '오후'}</span> "
        f"<span style='{CLOCK_TIME_STYLE}'>"
        f"{now.strftime('%I:%M:%S')}"
        f"</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    _render_recent_alerts()


def _render_account_section() -> None:
    """계정 정보(아이디·권한)와 로그아웃 버튼. 로그인 페이지를 제외한 모든
    페이지의 사이드바 맨 아래에 노출됩니다."""
    ss = st.session_state
    role_label = "관리자" if ss.role == "admin" else "사용자"
    st.caption(f"👤 {ss.get('username', '')} · {role_label}")
    if st.button("로그아웃", use_container_width=True):
        # 계정 관련 상태만 초기화 — detection_logs 등 나머지 세션 데이터는 그대로 둡니다.
        ss.authenticated = False
        ss.role = None
        ss.username = None
        st.rerun()


def render_sidebar() -> None:
    """사이드바 전체를 렌더링합니다 — 브랜드명, 페이지 전환 버튼(role에 따라
    노출 범위가 다름), RDS/S3 상태뱃지, 실시간 시계, 계정 정보/로그아웃을 이
    함수 하나에서 조립합니다. (기존 render_topnav()를 대체 — 메인 영역이
    아닌 st.sidebar에 그려서 CCTV 화면이 메인 영역 최상단에 붙도록 합니다.)

    함수 본문 전체를 `with st.sidebar:` 컨텍스트로 감싸고, 내부 헬퍼들은
    plain st.xxx만 호출합니다. _render_clock()이 st.fragment로 감싸여 있어
    fragment 내부에서 st.sidebar.xxx를 직접 호출할 수 없기 때문입니다
    (호출 시점에 이미 사이드바 컨텍스트 안에 있으면 plain st.xxx로도 사이드바에
    그려집니다).

    이 함수는 반드시 session_state.authenticated가 True일 때만 호출되어야
    합니다 (app.py가 로그인 게이트에서 이를 보장합니다).

    현재 선택된 페이지는 session_state.current_page에 저장되어 rerun 후에도 유지됩니다.
    """
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")
    st.markdown(BUTTON_NOWRAP_CSS, unsafe_allow_html=True)

    with st.sidebar:
        # 브랜드명 — 사이드바 최상단에 항상 고정 노출.
        # 관제 시스템 화면에서 "지금 어떤 시스템을 보고 있는지"는 페이지 이동과 무관하게 항상 보여야 함.
        st.markdown(
            f"<div style='{BRAND_TITLE_STYLE}'>GOP 통합 감시 시스템</div>",
            unsafe_allow_html=True,
        )

        # 페이지 전환 버튼 — 사이드바에서는 세로로 자연스럽게 쌓이므로 컬럼 분할이 불필요
        # 현재 페이지면 primary(강조색), 아니면 secondary(기본색) 버튼으로 현재 위치를 표시
        #
        # 권한별 노출 범위:
        #   admin → "실시간 감시" / "관리자 로그" / "설정" 3개 모두
        #   user  → "실시간 감시" 하나만 (버튼 자체를 숨겨 다른 페이지로 이동할 수단을 제공하지 않음.
        #            app.py에서도 current_page를 강제 고정하는 이중 방어를 함께 적용합니다)
        if st.button("실시간 감시", use_container_width=True,
                     type="primary" if ss.current_page == "관제 대시보드" else "secondary"):
            ss.current_page = "관제 대시보드"
            st.rerun()  # 클릭 즉시 페이지 전환이 반영되도록 강제 재실행
        if ss.role == "admin":
            if st.button("관리자 로그", use_container_width=True,
                         type="primary" if ss.current_page == "탐지 데이터 로그" else "secondary"):
                ss.current_page = "탐지 데이터 로그"
                st.rerun()
            if st.button("설정", use_container_width=True,
                         type="primary" if ss.current_page == "설정" else "secondary"):
                ss.current_page = "설정"
                st.rerun()

        _render_status_badge()
        st.divider()

        # 실시간 시계 (항상 표시) + 최근 탐지 배너
        _render_clock()
        st.divider()

        # 계정 정보 + 로그아웃 — 항상 맨 아래에 배치해 "설정류" 위젯과 시각적으로 분리
        _render_account_section()

