"""
ui/layout.py — 상단 네비게이션(브랜드명/페이지 전환/상태뱃지/실시간 시계) 렌더링

모든 페이지에 공통으로 나타나는 헤더 영역을 담당합니다. 이 파일은 render_topnav()
하나만 외부(app.py)에 노출하며, 나머지 함수는 그 안에서만 쓰이는 내부 헬퍼입니다.
"""
from datetime import datetime

import streamlit as st

from utils.formatters import fmt_dt

# 버튼 라벨(예: "관리자 로그")이 컬럼 폭보다 길 때 두 줄로 줄바꿈되는 것을 막는 CSS.
# Streamlit이 버튼 라벨을 내부적으로 <p> 태그로 렌더링하는 구조를 이용해 nowrap을 강제합니다.
_BUTTON_NOWRAP_CSS = """
<style>
div[data-testid="stButton"] > button p {
    white-space: nowrap;
}
</style>
"""


def _render_status_badge() -> None:
    """RDS/S3 연결 상태를 상단 우측에 상시 노출합니다.
    관제 시스템 특성상 "지금 로그가 실제로 저장되고 있는가"는 항상 눈에 보여야 하므로
    설정 페이지 안에 숨기지 않고 모든 화면에 고정 배치합니다."""
    ss = st.session_state
    db_label = "🟢 RDS 연결됨" if ss.get("DB_ENABLED") else "🟡 메모리 모드"
    s3_label = "🟢 S3 연결됨" if ss.get("S3_ENABLED") else "🟡 S3 미연결"
    st.markdown(
        f"<div style='text-align:right; font-size:0.85rem; color:gray; white-space:nowrap;'>"
        f"{db_label} · {s3_label}</div>",
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
    """1초마다 독립적으로 재실행되는 실시간 시계 컴포넌트입니다 (fragment 덕분에 전체
    페이지가 아니라 이 부분만 갱신되어 다른 UI에 영향을 주지 않습니다). 항상 표시됩니다."""
    now = datetime.now()
    # 라벨("현재 시각")은 작게, 오전/오후는 중간 크기, 실제 시:분:초는 크고 굵게 표시하여 시각적 강조 차등을 둠
    clock_col, alert_col = st.columns([1, 2])
    with clock_col:
        st.markdown(
            f"<div style='text-align:left; line-height:2.2;'>"
            f"<span style='font-size:0.9rem; color:gray;'>현재 시각:</span> &nbsp;"
            f"<span style='font-size:1.2rem; font-weight:500;'>"
            f"{'오전' if now.hour < 12 else '오후'}</span> "
            f"<span style='font-size:1.6rem; font-weight:600;'>"
            f"{now.strftime('%I:%M:%S')}"
            f"</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    with alert_col:
        _render_recent_alerts()

def render_topnav() -> None:
    """상단 네비게이션 전체를 렌더링합니다 — 브랜드명, 페이지 전환 버튼 3개,
    RDS/S3 상태뱃지, 실시간 시계를 이 함수 하나에서 조립합니다.

    현재 선택된 페이지는 session_state.current_page에 저장되어 rerun 후에도 유지됩니다.
    """
    ss = st.session_state
    ss.setdefault("current_page", "관제 대시보드")
    st.markdown(_BUTTON_NOWRAP_CSS, unsafe_allow_html=True)

    # 1행: 브랜드명 — 버튼 줄과 분리된 별도의 줄에 항상 고정 노출.
    # 관제 시스템 화면에서 "지금 어떤 시스템을 보고 있는지"는 페이지 이동과 무관하게 항상 보여야 함.
    st.markdown(
        "<div style='font-size:1.3rem; font-weight:700; margin-bottom:0.8rem;'>"
        "GOP 통합 감시 시스템</div>",
        unsafe_allow_html=True,
    )

    # 2행: 페이지 전환 버튼 3개(좌측에 모음) + 상태뱃지(spacer_col로 우측 끝까지 밀어냄)
    tab1_col, tab2_col, tab3_col, spacer_col, status_col = \
        st.columns([1.4, 1.4, 1.1, 4.3, 1.8], vertical_alignment="center")
    with tab1_col:
        # 현재 페이지면 primary(강조색), 아니면 secondary(기본색) 버튼으로 현재 위치를 표시
        if st.button("실시간 감시", use_container_width=True,
                     type="primary" if ss.current_page == "관제 대시보드" else "secondary"):
            ss.current_page = "관제 대시보드"
            st.rerun()  # 클릭 즉시 페이지 전환이 반영되도록 강제 재실행
    with tab2_col:
        if st.button("관리자 로그", use_container_width=True,
                     type="primary" if ss.current_page == "탐지 데이터 로그" else "secondary"):
            ss.current_page = "탐지 데이터 로그"
            st.rerun()
    with tab3_col:
        if st.button("설정", use_container_width=True,
                     type="primary" if ss.current_page == "설정" else "secondary"):
            ss.current_page = "설정"
            st.rerun()
    with status_col:
        _render_status_badge()

    # 3행: 실시간 시계 — 표시 여부는 _render_clock() 내부에서 자체적으로 판단 (위 docstring 참고)
    _render_clock()
    st.divider()
