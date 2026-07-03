"""
ui/alert_panel.py — 우측 사람 탐지 경보 패널 렌더링
"""
import streamlit as st

from services.alerts import update_remark, persist_log


def render_alert_panel() -> None:
    """대시보드 우측의 사람 탐지 경보 패널을 렌더링합니다."""
    ss = st.session_state
    dashboard_alerts = ss.dashboard_alerts  # 이번 세션 탐지만
    st.markdown(f"**사람 탐지 경보 ({len(dashboard_alerts)}건)**")

    if st.button("지우기", use_container_width=True):
        for a in ss.dashboard_alerts:
            a["show_on_dashboard"] = False
            persist_log(a)
        ss.dashboard_alerts = []  # 경보 패널만 초기화 (로그는 유지)
        st.rerun()

    if not dashboard_alerts:
        st.success("대기 중")
        return

    for alert in reversed(dashboard_alerts):
        with st.container(border=True):
            st.markdown(
                f"🚨 **{alert['class_name']}** ({alert['confidence']:.0%})<br>"
                f"📍 {alert['camera']}",
                unsafe_allow_html=True
            )
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

            if alert["status"] != "대기":
                st.caption(f"✓ 처리상태: **{alert['status']}**")
            if st.button("🔍 탐지 화면", key=f"view_{alert['id']}", use_container_width=True):
                ss["popup_id"] = alert["id"]
                st.rerun()
