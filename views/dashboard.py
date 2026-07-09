"""
views/dashboard.py — 페이지1: 관제 대시보드 ('실시간 감시')

폴더명을 "pages"가 아닌 "views"로 지은 이유: Streamlit은 app.py와 같은 위치에
"pages/"라는 이름의 폴더가 있으면 자동으로 그 안의 각 .py 파일을 별도 페이지로
등록하고 사이드바 네비게이션을 만듭니다. 이 파일은 독립 실행용 페이지가 아니라
render() 함수만 노출하는 모듈이므로, 그 자동 동작과 충돌하지 않도록 폴더명을
"views"로 정했습니다. 반드시 app.py에서 import하여 호출하는 방식으로만 사용하세요.

카메라 목록 준비는 services/camera_registry.py, 헤더의 날짜/시각 시계는
ui/camera/toolbar.py, 카드 배치는 ui/camera/grid.py·spotlight.py에 위임하고,
이 파일은 배치 순서만 조립합니다 (render()가 영상 재생 등으로 아주 자주
재실행되므로, 로직은 최대한 다른 모듈에 둡니다).

예전에는 "카메라 화면"/"관제 지도" 탭 2개로 나뉘어 있었지만, "관제 지도" 탭은
제거되었습니다 — 그 지도(마커 점멸 포함)는 스포트라이트 모드일 때
ui.camera.spotlight 안에 포함되어 있습니다(ui.outposts.viewer.render_map).
"구역 선택" 드롭다운도 사이드바에서 제거되었고, 그리드 ↔ 스포트라이트
전환은 이제 각 카메라 카드 자체의 버튼(⛶/▦, ui.camera.card)으로 합니다.

화면 구성 — 세 가지 모드:
    지도(설정 페이지 / 카드에 포함된 관제 지도)에서 마커를 하나 이상 선택한 경우
        → 선택된 카메라들만 그리드로 필터링 (ui.camera.grid) — 아래 그리드/
          스포트라이트 여부와 무관하게 이 필터가 우선합니다. 확대하는 것이
          아니라 기존 그리드 배치 그대로 대상만 좁히는 것입니다.
    (지도 선택이 없을 때) 그리드 모드(selected_cam == "전체 구역") → 그리드
        (ui.camera.grid, 평상시 기본 모드)
    (지도 선택이 없을 때) 특정 카메라 포커스 모드 → 스포트라이트: 1행(포커스
        카메라 | 관제 지도), 2행(나머지 카메라, 가로 스크롤) (ui.camera.spotlight)

지도에서 마커를 선택/해제하면(ui.outposts.marker_overlay.toggle_selection)
session_state._map_selected_cam_ids가 갱신되고, 이 페이지는 그 값을 직접
읽어 필터링합니다 — 설정 페이지 지도와 이 페이지에 포함된 관제 지도 모두
하나의 선택 상태를 공유합니다.

사람이 새로 탐지되면 services/playback.py가 _pending_selected_cam을 예약해
자동으로 그 카메라의 스포트라이트로 전환시킵니다 (consume_pending_camera_switch가
반영). 단, 지도 선택 필터가 걸려 있으면(위 참고) 그 필터가 우선이라 자동
전환은 지도 선택이 없을 때만 실제로 스포트라이트로 나타납니다.
"""
import streamlit as st

from services.camera_registry import get_valid_area_options, compute_grid_columns
from ui.camera.toolbar import render_header_clock, consume_pending_camera_switch
from ui.camera.grid import render_camera_grid
from ui.camera.spotlight import render_camera_spotlight
from ui.outposts.marker_overlay import selected_ids


def render(cameras: list[dict]) -> dict:
    """관제 대시보드 페이지 전체를 렌더링합니다.

    cameras는 app.py가 미리 계산해서 넘겨줍니다 — 카메라 목록/재생 상태는
    이 페이지가 화면에 보이든 안 보이든 항상 계산되어야, 다른 페이지를 보는
    동안에도 탐지가 계속 이루어질 수 있기 때문입니다. 이 함수는 카드를 그리며
    채운 video_slots를 반환하고, 실제 재생 루프 호출은 app.py가 담당합니다.
    """
    consume_pending_camera_switch()
    get_valid_area_options(cameras)  # 반환값은 쓰지 않지만, 삭제된 카메라를 보던 stale 선택값을 여기서 안전하게 되돌려둠

    video_slots = {}

    # 헤더 행 — 좌측 제목, 우측 날짜+시각 (예전에 사이드바에 있던 시계가 이 자리로 옮겨옴)
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        render_header_clock()

    map_selected = selected_ids()
    if map_selected:
        # 지도에서 선택한 카메라만 — 확대(스포트라이트)가 아니라 그리드로 필터링
        filtered = [c for c in cameras if c["id"] in map_selected] or cameras
        st.caption(
            f"🗺️ 지도에서 선택한 카메라 {len(filtered)}개만 표시 중 — "
            "선택을 해제하면 원래 화면으로 돌아갑니다."
        )
        render_camera_grid(filtered, video_slots, cols_per_row=compute_grid_columns(len(filtered)))
    elif st.session_state["selected_cam"] == "전체 구역":
        # 평상시 기본 모드 — 정사각형에 가깝게 자동 계산된 열 수로 그리드 렌더링
        render_camera_grid(cameras, video_slots, cols_per_row=compute_grid_columns(len(cameras)))
    else:
        # 특정 카메라에 포커스 — 1행(포커스 카메라 | 관제 지도), 2행(나머지 카메라, 가로 스크롤)
        render_camera_spotlight(cameras, st.session_state["selected_cam"], video_slots)

    return video_slots
