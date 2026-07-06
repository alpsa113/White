"""
ui/alert_panel.py — 우측 사람 탐지 경보 패널 렌더링

이번 세션에서 탐지된 사람만 카드 형태로 나열하고, 각 카드에서 오탐/경보 처리,
비고 입력, 탐지 화면 팝업 열기까지 처리합니다. 동물 탐지는 이 패널에 나타나지
않고 토스트 알림으로만 처리됩니다 (services/video_tracking.py 참고).
"""
import streamlit as st

from services.alerts import update_remark, persist_log
from ui.dialogs import open_popup

def render_alert_panel() -> None:
    """대시보드 우측의 사람 탐지 경보 패널을 렌더링합니다."""
    ss = st.session_state
    dashboard_alerts = ss.dashboard_alerts  # 이번 세션에서 탐지된 사람만 (RDS 과거 이력과 무관)
    st.markdown(f"**사람 탐지 경보 ({len(dashboard_alerts)}건)**")

    # 전체 지우기 — 로그 자체는 유지하고, 경보 패널 표시만 초기화
    if st.button("지우기", use_container_width=True):
        for a in ss.dashboard_alerts:
            a["show_on_dashboard"] = False
            persist_log(a)
        ss.dashboard_alerts = []
        st.rerun()

    if not dashboard_alerts:
        st.success("대기 중")
        return

    # 최근 탐지가 위에 오도록 역순으로 표시
    for alert in reversed(dashboard_alerts):
        with st.container(border=True):
            st.markdown(
                f"🚨 **{alert['class_name']}** ({alert['confidence']:.0%})<br>"
                f"📍 {alert['camera']}",
                unsafe_allow_html=True
            )
            # 비고 입력 — on_change 콜백에서 메모리 갱신 + DB 동기화까지 즉시 처리
            st.text_input(
                "비고", value=alert["remarks"], key=f"remark_input_{alert['id']}",
                on_change=update_remark, args=(alert["id"],),
                label_visibility="collapsed", placeholder="특이사항 입력"
            )

            b1, b2 = st.columns(2)
            with b1:
                if st.button("오탐", key=f"false_{alert['id']}", use_container_width=True):
                    alert["status"] = "오탐"
                    persist_log(alert)
                    st.rerun()
            with b2:
                if st.button("경보", key=f"true_{alert['id']}", use_container_width=True):
                    alert["status"] = "사람탐지(경보)"
                    persist_log(alert)
                    st.rerun()

            # 오탐/경보 처리가 된 건은 상태를 카드에 바로 표시하여 이미 검토했는지 한눈에 확인 가능
            if alert["status"] != "대기":
                st.caption(f"✓ 처리상태: **{alert['status']}**")
            if st.button("🔍 탐지 화면", key=f"view_{alert['id']}", use_container_width=True):
                open_popup(alert["id"])
                st.rerun()
