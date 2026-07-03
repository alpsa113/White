"""
views/dashboard.py — 페이지1: 관제 대시보드

이 폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은
위치에 "pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을
별도 페이지로 등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립
실행용 페이지가 아니라 render() 함수만 노출하는 모듈이므로, 그 자동 동작과
충돌하지 않도록 폴더명을 바꿨습니다. 반드시 app.py에서 import하여 호출하는
방식으로만 사용하세요.

라이브 카메라 피드(그리드/집중 보기), 우측 경보 패널, 팝업, 실시간 재생 루프를
조립합니다. 세부 렌더링은 ui/, services/ 모듈에 위임합니다.
"""
import streamlit as st

from config import CAMERAS
from ui.camera_card import render_camera_grid, render_camera_focus, show_person_dialog
from ui.alert_panel import render_alert_panel
from services.video_tracking import run_playback_loop


def render() -> None:
    """관제 대시보드 페이지 전체를 렌더링합니다."""
    ss = st.session_state

    # 영상 슬롯과 경보 패널 영역을 분리 (비율 6:1)
    left_col, right_col = st.columns([6, 1])

    video_slots = {}
    progress_slots = {}

    with left_col:
        # ── 헤더 행: 라이브 카메라 피드 제목 + 구역 선택 드롭다운 ──
        h1, h2 = st.columns([5, 1])
        with h1:
            st.markdown("🔴 **라이브 카메라 피드**")
        with h2:
            st.selectbox(
                "구역 선택",
                options=["전체 구역"] + [c["name"] for c in CAMERAS],
                key="selected_cam",
                label_visibility="collapsed",
            )

        if ss["selected_cam"] == "전체 구역":
            render_camera_grid(video_slots, progress_slots)
        else:
            render_camera_focus(ss["selected_cam"], video_slots, progress_slots)

    # 대시보드 우측 알람 패널 렌더링
    with right_col:
        render_alert_panel()

    # 다이얼로그(팝업) 트리거 확인
    popup_id = ss.pop("popup_id", None)
    if popup_id is not None:
        target = next((a for a in ss.detection_logs if a["id"] == popup_id), None)
        if target is not None:
            show_person_dialog(target)

    # ------------------------------------------------------------------ #
    # MASTER STREAMING LOOP (다중 영상 실시간 처리 메인 루프)
    # ------------------------------------------------------------------ #
    active_cams = [cam for cam in CAMERAS if ss.get(f"playing_{cam['id']}")]
    if active_cams:
        run_playback_loop(active_cams, video_slots, progress_slots)
