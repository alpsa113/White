"""ui/outposts/marker_overlay.py — 지도 위 초소 마커 렌더링과 "CCTV 화면 보기" 선택 상태 공용 로직."""
import streamlit as st

SELECTED_COLOR = "#f85149"
DEFAULT_COLOR = "#58a6ff"

MAP_WRAP_KEY = "outpost_map_wrap"  # 지도 래퍼 컨테이너 key — 마커 절대좌표 기준점

BLINK_CSS = f"""
<style>
@keyframes outpost-marker-blink {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.15; }} }}
div[class*="st-key-{MAP_WRAP_KEY}"] {{ position: relative; }}
</style>
"""


def selected_ids() -> set:
    """설정 페이지 지도/관제 지도/카메라 화면 탭이 공유하는 선택 상태를 반환합니다."""
    return set(st.session_state.get("_map_selected_cam_ids", []))


def toggle_selection(cid: str) -> None:
    """마커 클릭 시 공유 선택 상태를 토글합니다."""
    ss = st.session_state
    ids = selected_ids()
    if cid in ids:
        ids.discard(cid)
    else:
        ids.add(cid)
    ss["_map_selected_cam_ids"] = list(ids)
    st.rerun()


def marker_css(cid: str, x_ratio: float, y_ratio: float, *, selected: bool, blinking: bool = False) -> str:
    """마커+정지 아이콘의 절대 위치 및 상태별(선택/점멸) 스타일. 크기는 지도 폭 기준 cqw로 비례합니다."""
    color = SELECTED_COLOR if selected else DEFAULT_COLOR
    blink_rule = "animation: outpost-marker-blink 1s infinite;" if blinking else ""
    return f"""
    <style>
    div[class*="st-key-outpost_marker_{cid}"] {{
        position: absolute;
        left: {x_ratio * 100:.3f}%;
        top: {y_ratio * 100:.3f}%;
        transform: translate(-50%, -50%);
        z-index: 10;
        width: auto !important;
    }}
    div[class*="st-key-outpost_marker_{cid}"] button {{
        width: clamp(12px, 6.5cqw, 22px); height: clamp(12px, 6.5cqw, 22px);
        min-height: 0 !important;
        box-sizing: border-box !important;
        padding: 0 !important; border-radius: 50% !important;
        display: flex !important; align-items: center; justify-content: center;
        background-color: {color} !important; color: white !important;
        border: clamp(1px, 0.6cqw, 2px) solid white !important;
        font-size: clamp(7px, 3.4cqw, 13px); font-weight: 700; line-height: 1;
        {blink_rule}
    }}
    div[class*="st-key-outpost_stop_{cid}"] {{
        position: absolute;
        left: calc({x_ratio * 100:.3f}% + 4.5cqw);
        top: calc({y_ratio * 100:.3f}% - 4.5cqw);
        transform: translate(-50%, -50%);
        z-index: 11;
        width: auto !important;
    }}
    div[class*="st-key-outpost_stop_{cid}"] button {{
        width: clamp(8px, 4.2cqw, 15px); height: clamp(8px, 4.2cqw, 15px);
        min-height: 0 !important;
        box-sizing: border-box !important;
        padding: 0 !important; border-radius: 50% !important;
        display: flex !important; align-items: center; justify-content: center;
        background-color: #21262d !important; color: white !important;
        border: 1px solid white !important;
        font-size: clamp(5px, 2.5cqw, 10px); line-height: 1;
    }}
    </style>
    """


def render_marker(cid: str, x_ratio: float, y_ratio: float, *, number: int, selected: bool,
                   blinking: bool = False, label: str) -> None:
    """지도 위 절대 좌표에 마커 버튼 1개를 그립니다. 클릭하면 선택 상태를 토글합니다."""
    st.markdown(marker_css(cid, x_ratio, y_ratio, selected=selected, blinking=blinking),
                unsafe_allow_html=True)
    with st.container(key=f"outpost_marker_{cid}"):
        help_txt = f"{label} — 클릭하여 선택 해제" if selected else f"{label} — 클릭하여 CCTV 화면 보기로 선택"
        if st.button(str(number), key=f"outpost_marker_btn_{cid}", help=help_txt):
            toggle_selection(cid)


def render_stop_icon(cid: str, *, label: str) -> None:
    """점멸 중인 마커 옆의 "⏹" 정지 아이콘을 그립니다(점멸만 멈추고 선택은 유지)."""
    ss = st.session_state
    with st.container(key=f"outpost_stop_{cid}"):
        if st.button("⏹", key=f"outpost_stop_btn_{cid}", help=f"{label} — 점멸 정지"):
            ss[f"blink_stopped_{cid}"] = True
            st.rerun()
