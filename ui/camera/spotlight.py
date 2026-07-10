"""
ui/camera/spotlight.py — 특정 카메라를 크게 보여주는 집중 보기 레이아웃

배치 (2열):
  좌측 열 — 2행: 1행 [탐지된 CCTV 화면(포커스 카메라)], 2행 [초소 위치 지도 —
            초소 마커 + 점멸]. 위아래로 쌓입니다.
  우측 열 — 나머지 카메라들을 세로로 나열, 고정 높이(`st.container(height=
            REST_HEIGHT_PX)`)를 넘치면 Streamlit이 기본 제공하는 세로
            스크롤바가 자동으로 생깁니다.

세로 스크롤은 Streamlit의 `st.container(height=N)` 파라미터 하나로 해결됩니다
— 커스텀 CSS(overflow-x, flex-basis 등)가 전혀 필요 없어, 예전에 가로
스크롤 실험에서 겪었던 것과 같은 종류의 레이아웃 버그가 애초에 생길 수
없는 구조입니다.

지도는 ui.outposts.viewer.render_map()가 이미지 실제 종횡비에 래퍼를
고정해서 그리므로, 폭이 좁아져도 잘리거나 마커 위치가 어긋나지 않습니다.

사람 탐지 시 자동으로(services/playback.py의 _pending_selected_cam 예약),
또는 카드의 ⛶ 버튼으로 수동으로(ui/camera/card.py) 이 모드로 전환됩니다
(views/dashboard.py가 어느 모드를 그릴지 결정). 예전에는 별도의 "관제 지도"
탭이 있었지만 제거되었고, 그 자리에 있던 지도(마커 점멸 포함)는 이제 이
레이아웃의 좌측 열 2행에 포함되어 있습니다(ui/outposts/viewer.render_map 재사용).
"""
import streamlit as st

from ui.camera.card import render_camera_card
from ui.outposts.viewer import render_map

# 우측 열("나머지 카메라") 세로 스크롤 영역의 고정 높이(px) — 좌측 열
# (카메라 화면 + 지도, 위아래로 쌓인 높이)과 대략 비슷한 눈높이가 되도록
# 잡았습니다. 카메라가 몇 대든 이 높이를 넘치면 자동으로 세로 스크롤바가
# 생기고, 카드 자체의 폭/높이는 그대로 유지됩니다.
REST_HEIGHT_PX = 760


def render_camera_spotlight(cameras: list[dict], focused_name: str, video_slots: dict) -> None:
    """focused_name에 해당하는 카메라를 좌측 열 1행에 크게, 좌측 열 2행에
    초소 위치 지도를 보여주고, 나머지 카메라는 우측 열에 세로로 나열합니다
    (넘치면 세로 스크롤). focused_name을 찾지 못하면(초소 삭제 등으로 사라진
    경우) 좌측 1행을 비워두고 지도/나머지 카메라만 보여줍니다."""
    focused = next((c for c in cameras if c["name"] == focused_name), None)
    others = [c for c in cameras if c is not focused]

    left_col, right_col = st.columns([2.5, 1])

    with left_col:
        if focused:
            render_camera_card(focused, video_slots)
        else:
            st.info("선택된 카메라를 찾을 수 없습니다.")
        render_map(cameras)

    with right_col:
        if others:
            with st.container(height=REST_HEIGHT_PX):
                for cam in others:
                    render_camera_card(cam, video_slots)
        else:
            st.caption("표시할 다른 카메라가 없습니다.")
