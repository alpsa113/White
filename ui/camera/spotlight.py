"""
ui/camera/spotlight.py — 특정 카메라를 크게 보여주는 집중 보기 레이아웃

포커스된 카메라 1개만 크게 표시합니다. 예전에는 우측에 나머지 카메라들을
세로로 나열하고, 좌측 하단에 초소 위치 지도를 함께 두었지만, 지도는 이제
'실시간 감시' 페이지 헤더의 미니맵(views/dashboard.py → ui.outposts.viewer.
render_map)으로 이동했고, 나머지 카메라 목록은 그리드 모드로 돌아가면 다시
볼 수 있으므로 스포트라이트 화면에서는 제거되었습니다.

사람 탐지 시 자동으로(services/playback.py의 _pending_selected_cam 예약),
또는 카드의 ⛶ 버튼으로 수동으로(ui/camera/card.py) 이 모드로 전환됩니다
(views/dashboard.py가 어느 모드를 그릴지 결정).

EO/TIR 동시 재생(2분할)은 스포트라이트에서만 지원됩니다(그리드 모드는
카드 1개당 항상 배경 채널 하나만 재생) — 여기서는 그냥 카메라 카드 1개를
그리는 것과 다를 게 없고, 실제로 보조 채널의 재생을 시작/중지하는 로직은
ui/camera/card.py(§_toggle_channel)에 있습니다. eo_video_slots/
tir_video_slots는 views/dashboard.py가 만들어 app.py까지 그대로 반환하는
딕셔너리로, ui/camera/card.py가 화면에 표시하기로 한 채널의 슬롯만 여기에
등록합니다.
"""
import streamlit as st

from ui.camera.card import render_camera_card


def render_camera_spotlight(cameras: list[dict], focused_name: str, eo_video_slots: dict,
                             tir_video_slots: dict) -> None:
    """focused_name에 해당하는 카메라를 크게 보여줍니다. focused_name을 찾지
    못하면(초소 삭제 등으로 사라진 경우) 안내 메시지만 표시합니다."""
    focused = next((c for c in cameras if c["name"] == focused_name), None)

    if focused:
        render_camera_card(focused, eo_video_slots, tir_video_slots)
    else:
        st.info("선택된 카메라를 찾을 수 없습니다.")
