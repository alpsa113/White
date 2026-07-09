"""
views/logs.py — 페이지2: 탐지 데이터 로그 관리

dashboard.py와 마찬가지로 render() 함수로만 노출되며, app.py에서 import하여
호출하는 방식으로만 사용합니다. (폴더명을 "views"로 지은 이유는 views/dashboard.py
상단 설명 참고)

로그 목록을 최신순으로 정렬한 뒤, 조회 탭과 편집 탭 두 개를 조립합니다.
편집 탭(render_manage_tab)은 admin 권한에서만 노출됩니다 — user 권한은 이
페이지에서 조회만 가능하고 수정/삭제는 할 수 없습니다.
"""
import streamlit as st

from ui.log_tabs import render_view_tab, render_manage_tab


def render() -> None:
    """탐지 데이터 로그 페이지 전체를 렌더링합니다."""
    ss = st.session_state
    st.caption("Dual-YOLO 데이터베이스 스키마(inference_jobs, detections 등)를 반영한 추론 결과입니다.")

    if not ss.detection_logs:
        st.info("현재 기록된 탐지 데이터가 없습니다.")
        return

    # 최신 탐지일시(created_at) 기준으로 정렬 — DB 레코드와 메모리 레코드의 필드 차이는
    # a.get("created_at")가 없을 때 date+time 조합으로 대체하여 흡수합니다.
    sorted_logs = sorted(
        ss.detection_logs,
        key=lambda a: (
            a.get("created_at") or f"{a.get('date', '')} {a.get('time', '')}",
            a.get("id", 0)
        ),
        reverse=True,
    )

    # 조회(읽기 전용)와 편집(수정/삭제)을 탭으로 분리하여, 실수로 값을 바꾸는 것을 방지.
    # 편집 탭은 admin 권한에서만 렌더링합니다 — user는 탭 자체가 보이지 않습니다.
    if ss.role == "admin":
        tab_view, tab_manage = st.tabs(["로그 조회 및 이미지", "로그 편집 및 삭제"])
        with tab_manage:
            render_manage_tab(sorted_logs)
    else:
        (tab_view,) = st.tabs(["로그 조회 및 이미지"])

    with tab_view:
        render_view_tab(sorted_logs)
