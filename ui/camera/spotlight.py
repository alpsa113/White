"""
ui/camera/spotlight.py — 특정 카메라를 크게 보여주는 집중 보기 레이아웃

배치:
  1행 (2열, 3:1 비율): [포커스된 카메라 큰 화면] | [관제 지도 — 초소 마커 + 점멸]
  2행 (1열): 나머지 카메라들을 가로로 나열 — 카메라가 많아지면 좁아지며
             욱여넣는 대신 가로 스크롤바가 생깁니다.

1행 비율(3:1)은 예전(관제 지도가 별도 탭이었을 때) 스포트라이트 레이아웃이
쓰던 것과 동일합니다 — 포커스된 카메라 화면이 훨씬 크게 보이는 것이
핵심이고, 관제 지도는 "지금 어디를 보고 있는지" 참고용으로 작게 곁들이는
용도입니다. 지도는 ui.outposts.viewer.render_map()가 이미지 실제 종횡비에
래퍼를 고정해서 그리므로, 폭이 좁아져도 잘리거나 마커 위치가 어긋나지
않습니다.

카메라 화면(3)과 지도(1)는 폭 비율은 다르지만 둘 다 가로세로 비율이 고정된
콘텐츠라서 세로 높이가 서로 다르게 나옵니다 — 카메라 쪽이 훨씬 넓은 만큼
훨씬 높아지기 때문입니다. 지도를 그 큰 높이에 맞춰 억지로 늘리면(찌그러짐)
부자연스러우므로, 대신 지도를 자기 컬럼 안에서 세로 중앙에 배치해 카메라와
나란히 있을 때 상단에 붙어 아래쪽에 큰 빈 공간이 남는 것을 방지합니다.

사람 탐지 시 자동으로(services/playback.py의 _pending_selected_cam 예약),
또는 카드의 ⛶ 버튼으로 수동으로(ui/camera/card.py) 이 모드로 전환됩니다
(views/dashboard.py가 어느 모드를 그릴지 결정). 예전에는 별도의 "관제 지도"
탭이 있었지만 제거되었고, 그 자리에 있던 지도(마커 점멸 포함)는 이제 이
레이아웃의 1행 우측에 포함되어 있습니다(ui/outposts/viewer.render_map 재사용).
"""
import streamlit as st

from ui.camera.card import render_camera_card
from ui.outposts.viewer import render_map

# 관제 지도 컬럼을 세로 중앙 정렬하는 CSS — 카메라 쪽이 훨씬 높아도 지도가
# 상단에 붙어 아래에 빈 공간만 남기지 않고, 그 높이 한가운데에 오도록 합니다.
# (Streamlit의 st.columns() 행은 기본적으로 자식을 stretch하므로, 이 컨테이너의
# height:100%가 실제로 그 행의 높이(=더 큰 쪽인 카메라 컬럼 높이)를 채웁니다.)
MAP_COL_CSS = """
<style>
div[class*="st-key-spotlight_map_col"] {
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
}
</style>
"""

# 2행(나머지 카메라) 카드 1개의 고정 폭(px) — 카메라가 많아져도 이 폭을
# 유지한 채 가로 스크롤바가 생기게 합니다(좁아지며 다 욱여넣지 않음).
# 카드 상단 오버레이 바(이름·EO/TIR·⛶)는 컨테이너 쿼리로 이 폭에 맞춰
# 자동으로 배지 크기를 줄이므로, 이 폭이 좁아도 버튼끼리 겹치지 않습니다.
REST_CARD_WIDTH_PX = 280


def _rest_row_css(cids: list[str]) -> str:
    """가로 스크롤 행 자체 + 그 안의 카드들이 각각 고정 폭을 유지하도록 하는
    CSS를 한 번에 묶어서 반환합니다. (카드 개수만큼 반복 주입하지 않고
    한 번만 주입해야, 그 style 태그 자체가 flex 아이템으로 끼어들어
    배치가 흐트러지는 일이 없습니다.)"""
    item_rules = "\n".join(
        f'div[class*="st-key-spotlight_rest_item_{cid}"] {{'
        f" flex: 0 0 {REST_CARD_WIDTH_PX}px;"
        f" width: {REST_CARD_WIDTH_PX}px;"
        f" min-width: {REST_CARD_WIDTH_PX}px;"
        f" flex-shrink: 0;"
        f" }}"
        for cid in cids
    )
    return f"""
    <style>
    div[class*="st-key-spotlight_rest_row"] {{
        display: flex;
        flex-wrap: nowrap;
        align-items: flex-start;
        overflow-x: auto;
        overflow-y: hidden;
        gap: 12px;
        padding-bottom: 8px;
    }}
    {item_rules}
    </style>
    """


def render_camera_spotlight(cameras: list[dict], focused_name: str, video_slots: dict) -> None:
    """focused_name에 해당하는 카메라를 1행 좌측에 크게, 1행 우측엔 관제 지도를
    보여주고, 나머지 카메라는 2행에 가로로 나열합니다(카메라가 많으면 가로
    스크롤). focused_name을 찾지 못하면(초소 삭제 등으로 사라진 경우) 좌측을
    비워두고 지도/나머지 카메라만 보여줍니다."""
    focused = next((c for c in cameras if c["name"] == focused_name), None)
    others = [c for c in cameras if c is not focused]

    main_col, map_col = st.columns([3, 1])
    with main_col:
        if focused:
            render_camera_card(focused, video_slots)
        else:
            st.info("선택된 카메라를 찾을 수 없습니다.")
    with map_col:
        st.markdown(MAP_COL_CSS, unsafe_allow_html=True)
        with st.container(key="spotlight_map_col"):
            render_map(cameras)

    if others:
        # 카드 개수만큼 반복하지 않고 한 번만 주입 — 위 _rest_row_css() docstring 참고
        st.markdown(_rest_row_css([c["id"] for c in others]), unsafe_allow_html=True)
        with st.container(key="spotlight_rest_row", horizontal=True):
            for cam in others:
                with st.container(key=f"spotlight_rest_item_{cam['id']}"):
                    render_camera_card(cam, video_slots)
