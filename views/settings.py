"""
views/settings.py — 페이지3: 설정

데모 모드, 사람 등장 비율, 시계 표시 여부 등 자주 바뀌지 않는 설정을 모아둔
페이지입니다. render() 함수로만 노출되며 app.py에서 호출합니다.
"""
import streamlit as st


def render() -> None:
    """설정 페이지 전체를 렌더링합니다."""
    ss = st.session_state
    st.markdown("### 시스템 설정")

    # ==================================================================== #
    # [중요] 이 페이지의 위젯은 "위젯 전용 key(_xxx_widget)"와 "실제 상태
    # key(simulate, person_ratio 등)"를 분리하고, on_change 콜백으로 값을
    # 복사하는 패턴을 씁니다.
    #
    # 이유: 이 위젯들은 설정 페이지에서만 그려지는데, Streamlit은 특정 실행에서
    # 그려지지 않는 위젯의 key를 session_state에서 삭제합니다. 만약 위젯 key를
    # 다른 파일(예: services/detection.py의 데모 로직)에서 직접 참조하면,
    # 페이지를 옮겨 다닐 때 그 값이 사라지거나 초기화되는 문제가 생깁니다.
    # 위젯 key와 실제 상태 key를 분리해두면, 위젯이 화면에서 사라져도 실제
    # 상태값은 항상 안정적으로 유지됩니다.
    # ==================================================================== #

    # ── 데모 모드 설정 ──
    # (데모 모드를 완전히 제거할 경우, 이 구획 전체와 services/detection.py의
    #  simulate_detections()/run_detection() 안 데모 분기, state.py의 관련 두 줄을 함께 삭제)
    st.markdown("**데모 모드**")

    def _sync_simulate():
        """체크박스 값을 실제 상태 키(simulate)로 복사."""
        ss["simulate"] = ss["_simulate_widget"]

    def _sync_person_ratio():
        """슬라이더 값을 실제 상태 키(person_ratio)로 복사."""
        ss["person_ratio"] = ss["_person_ratio_widget"]

    # 데모 모드 On/Off — 꺼져 있으면 실제 backend.py API를 호출하여 추론합니다.
    st.checkbox(
        "데모 모드 (무작위 탐지)",
        value=ss.get("simulate", True),
        key="_simulate_widget",
        on_change=_sync_simulate,
    )
    # 데모 모드일 때만 의미가 있으므로, 꺼져 있으면 슬라이더 자체를 비활성화
    st.slider(
        "사람 등장 비율", 0.00, 1.00,
        value=ss.get("person_ratio", 0.03),
        step=0.01,
        disabled=not ss.get("simulate", True),
        key="_person_ratio_widget",
        on_change=_sync_person_ratio,
    )

    st.divider()

    # ── 시스템 상태 표시 ──
    st.markdown("**시스템 상태**")
    # DB_ENABLED는 state.py에서 앱이 리런될 때마다 db.init_db() 결과로 갱신됩니다.
    if ss.get("DB_ENABLED"):
        st.success("🟢 RDS 연결됨 - 로그가 영구 저장됩니다.")
    else:
        st.warning("🟡 메모리 모드 - RDS 미연결 (로그는 재시작 시 사라짐).")
        # init_db() 실패 시 db_rds.py가 이 키에 상세 에러 메시지를 남겨둡니다.
        if ss.get("_db_init_error"):
            with st.expander("RDS 연결 오류 보기"):
                st.code(ss["_db_init_error"])

    # S3_ENABLED는 state.py에서 s3.is_enabled() 결과로 갱신됩니다 (secrets.toml [s3] 설정 여부).
    if ss.get("S3_ENABLED"):
        st.success("🟢 S3 연결됨 - 탐지 스냅샷 이미지가 영구 저장됩니다.")
    else:
        st.warning("🟡 S3 미연결 - 스냅샷은 메모리에만 보관되며 재시작 시 사라짐.")
