"""
views/dashboard.py — 페이지1: 관제 대시보드

폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은 위치에
"pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을 별도 페이지로
등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립 실행용 페이지가 아니라
render() 함수만 노출하는 모듈이므로, 그 자동 동작과 충돌하지 않도록 폴더명을
"views"로 정했습니다. 반드시 app.py에서 import하여 호출하는 방식으로만 사용하세요.

라이브 카메라 피드(그리드/집중 보기), 우측 경보 패널, 팝업, 실시간 재생 루프를
조립합니다. 세부 렌더링은 ui/, services/ 모듈에 위임합니다.
"""
import math

import streamlit as st

from config import build_camera_list, MAX_CAMERAS
from ui.camera_card import render_camera_grid, render_camera_focus, show_person_dialog
from ui.alert_panel import render_alert_panel
from services.video_tracking import run_playback_loop, reset_cam_state


def _sync_grid_count() -> None:
    """number_input(+/- 스텝퍼)의 변경값을 실제 상태 키(grid_count)로 복사하는 콜백.

    위젯 전용 key(_grid_count_widget)와 실제 상태 key(grid_count)를 분리해두는 이유:
    이 위젯은 '전체 구역'일 때만 그려지는데, Streamlit은 특정 실행에서 그려지지 않는
    위젯의 key를 session_state에서 삭제합니다. 위젯 key를 다른 곳에서 직접 참조하면
    페이지를 옮겨 다닐 때 값이 사라지는 문제가 생기므로, 항상 안정적으로 유지되어야
    하는 실제 값은 이렇게 별도 key로 분리해 관리합니다.
    """
    st.session_state["grid_count"] = st.session_state["_grid_count_widget"]


def _render_grid_count_selector() -> None:
    """'전체 구역' 모드에서만 노출되는 총 카메라 개수 선택 UI (+/- 스텝퍼).
    특정 카메라 집중 보기 중에는 그리드 개념 자체가 없으므로 아무것도 그리지 않고 종료합니다."""
    ss = st.session_state
    if ss.get("selected_cam") != "전체 구역":
        return
    # step=1을 주면 Streamlit이 입력창 옆에 -/+ 버튼을 자동으로 붙여줍니다.
    st.number_input(
        "카메라 개수", min_value=1, max_value=MAX_CAMERAS, step=1,
        value=ss.get("grid_count", 4),
        key="_grid_count_widget", on_change=_sync_grid_count,
        label_visibility="visible",
    )


def render() -> None:
    """관제 대시보드 페이지 전체를 렌더링합니다."""
    ss = st.session_state

    # 사용자가 정한 총 개수(grid_count)만큼 카메라 슬롯을 그때그때 생성합니다.
    # config.CAMERA_NAMES에 없는 번호는 build_camera_list가 "CCTV-NN (구역 N)"으로 자동 생성합니다.
    total = max(1, min(ss.get("grid_count", 4), MAX_CAMERAS))
    auto_cols = math.ceil(math.sqrt(total))  # 총 개수를 정사각형에 가깝게 배치 (예: 5개 → 3열, 9개 → 3x3)
    cameras = build_camera_list(total)

    # ── 그리드 축소 시 리소스 정리 ──
    # 예: 9칸 → 4칸으로 줄이면 cam5~cam9에 업로드했던 영상의 cv2.VideoCapture 핸들과
    # 임시파일이 메모리에 남아있을 수 있으므로, 이번 렌더에서 사라진 카메라 ID만 찾아 정리합니다.
    prev_ids = set(ss.get("_prev_camera_ids", []))
    curr_ids = {c["id"] for c in cameras}
    for cid in prev_ids - curr_ids:
        reset_cam_state(cid)
    ss["_prev_camera_ids"] = list(curr_ids)  # 다음 렌더에서 비교할 수 있도록 현재 목록을 저장해둠

    # 그리드를 줄였는데 마침 그 사라진 카메라를 집중 보기 중이었다면, selectbox의
    # options에 없는 값이 남아 에러가 나므로 안전하게 '전체 구역'으로 되돌립니다.
    valid_options = ["전체 구역"] + [c["name"] for c in cameras]
    if ss.get("selected_cam") not in valid_options:
        ss["selected_cam"] = "전체 구역"

    # 좌측(카메라 영역) : 우측(경보 패널) = 6 : 1 비율로 화면을 분할
    left_col, right_col = st.columns([6, 1])

    video_slots = {}     # {camera_id: st.empty()} — 각 카메라의 영상이 표시될 자리
    progress_slots = {}  # {camera_id: st.empty()} — 각 카메라의 진행률 바가 표시될 자리

    with left_col:
        # ── 헤더 행: 제목 + 구역 선택 드롭다운 + 카메라 개수 스텝퍼 ──
        h1, h2, h3 = st.columns([3.5, 1.2, 2])
        with h1:
            st.markdown("🔴 **라이브 카메라 피드**")
        with h2:
            # "전체 구역" 선택 시 그리드로, 특정 카메라명 선택 시 그 카메라만 확대 표시
            st.selectbox(
                "구역 선택",
                options=valid_options,
                key="selected_cam",
                label_visibility="visible",
            )
        with h3:
            _render_grid_count_selector()

        if ss["selected_cam"] == "전체 구역":
            # 정사각형에 가깝게 자동 계산된 열 수(auto_cols)로 그리드 렌더링
            render_camera_grid(cameras, video_slots, progress_slots, cols_per_row=auto_cols)
        else:
            # 특정 카메라 1개만 전체 너비로 확대 표시
            render_camera_focus(cameras, ss["selected_cam"], video_slots, progress_slots)

    # ── 우측: 사람 탐지 경보 패널 ──
    with right_col:
        render_alert_panel()

    # ── 팝업 트리거 확인 ──
    # popup_id가 설정되어 있으면(경보 패널 '탐지 화면' 클릭, 자동 팝업 등) 해당 로그를
    # 찾아 다이얼로그로 띄웁니다. pop()으로 꺼내 쓰므로 팝업은 한 번만 뜨고 자동 소비됩니다.
    popup_id = ss.pop("popup_id", None)
    if popup_id is not None:
        target = next((a for a in ss.detection_logs if a["id"] == popup_id), None)
        if target is not None:
            show_person_dialog(target)

    # ------------------------------------------------------------------ #
    # MASTER STREAMING LOOP (다중 영상 실시간 처리 메인 루프)
    # ------------------------------------------------------------------ #
    # 재생 중(playing_{id}=True)인 카메라만 골라 재생 루프에 전달합니다.
    # 재생 중인 영상이 하나도 없으면 루프를 아예 실행하지 않아 불필요한 대기를 피합니다.
    active_cams = [cam for cam in cameras if ss.get(f"playing_{cam['id']}")]
    if active_cams:
        run_playback_loop(active_cams, video_slots, progress_slots)
