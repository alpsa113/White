"""views/settings.py — 페이지3: 설정. 초소 정보/영상 매핑, 데모 모드, 시스템 상태를 표시합니다."""
import streamlit as st

from ui.outposts.editor import render_outpost_editor


def render() -> None:
    """설정 페이지 전체를 렌더링합니다."""
    ss = st.session_state
    is_admin = ss.get("role") == "admin"

    render_outpost_editor()

    st.divider()
    st.markdown("### 시스템 설정")

    # 위젯 key(_xxx_widget)와 실제 상태 key를 분리 — 위젯이 안 그려지는 페이지에서도 값 유지
    if is_admin:
        st.markdown("**데모 모드**")

        def _sync_simulate():
            ss["simulate"] = ss["_simulate_widget"]

        def _sync_person_ratio():
            ss["person_ratio"] = ss["_person_ratio_widget"]

        st.checkbox(
            "데모 모드 (무작위 탐지)",
            value=ss.get("simulate", True),
            key="_simulate_widget",
            on_change=_sync_simulate,
        )
        st.slider(
            "사람 등장 비율", 0.00, 1.00,
            value=ss.get("person_ratio", 0.03),
            step=0.01,
            disabled=not ss.get("simulate", True),
            key="_person_ratio_widget",
            on_change=_sync_person_ratio,
        )

        st.divider()

    st.markdown("**시스템 상태**")
    if ss.get("DB_ENABLED"):
        st.success("🟢 RDS 연결됨 - 로그가 영구 저장됩니다.")
    else:
        st.warning("🟡 메모리 모드 - RDS 미연결 (로그는 재시작 시 사라짐).")
        if ss.get("_db_init_error") and is_admin:
            with st.expander("RDS 연결 오류 보기"):
                st.code(ss["_db_init_error"])

    if ss.get("S3_ENABLED"):
        st.success("🟢 S3 연결됨 - 탐지 스냅샷 이미지가 영구 저장됩니다.")
    else:
        st.warning("🟡 S3 미연결 - 스냅샷은 메모리에만 보관되며 재시작 시 사라짐.")
