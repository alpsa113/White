"""ui/outposts/marker_overlay.py — 지도 위 초소 마커 렌더링과 "CCTV 화면 보기" 선택 상태 공용 로직."""
import streamlit as st

from ui.styles import CHECK_MARK_SVG, MAP_BLINK_CSS_TEMPLATE, MARKER_CSS_TEMPLATE

BLINK_COLOR = "#f85149"  # 사람 탐지로 점멸 중인 마커
DEFAULT_COLOR = "#58a6ff"

MAP_WRAP_KEY = "outpost_map_wrap"  # 지도 래퍼 컨테이너 key — 마커 절대좌표 기준점

BLINK_CSS = MAP_BLINK_CSS_TEMPLATE.format(wrap_key=MAP_WRAP_KEY)


def selected_ids() -> set:
    """설정 페이지 지도/관제 지도/카메라 화면 탭이 공유하는 선택 상태를 반환합니다."""
    return set(st.session_state.get("_map_selected_cam_ids", []))


def visible_camera_ids(cameras: list[dict]) -> set:
    """현재 대시보드 화면에 실제로 표시(재생)되고 있는 카메라 id 집합을 반환합니다.

    views/dashboard.py의 표시 분기(지도 필터 > 전체 구역 그리드 > 단일 집중 보기)와
    동일한 우선순위를 따릅니다."""
    ss = st.session_state
    valid = {c["id"] for c in cameras}
    sel = selected_ids() & valid
    if sel:
        return sel
    if ss.get("selected_cam") == "전체 구역":
        return valid
    focused_id = next((c["id"] for c in cameras if c["name"] == ss.get("selected_cam")), None)
    return {focused_id} if focused_id else set()


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


def stop_all_blinking() -> None:
    """사람 탐지로 점멸 중인 모든 마커의 점멸을 멈춥니다.

    사용자가 (탐지와 무관한) 다른 조작을 하면 앱 전역에서 한 번 호출됩니다."""
    ss = st.session_state
    for key in list(ss.keys()):
        if not key.startswith("person_tracks_") or not ss.get(key):
            continue
        channel_cid = key[len("person_tracks_"):]
        cid = channel_cid.rsplit("_", 1)[0]
        ss[f"blink_stopped_{cid}"] = True


def marker_css(cid: str, x_ratio: float, y_ratio: float, *, blinking: bool = False) -> str:
    """마커+정지 아이콘+체크 배지의 절대 위치 및 상태별(점멸) 스타일. 크기는 지도 폭 기준 cqw로 비례합니다."""
    return MARKER_CSS_TEMPLATE.format(
        cid=cid,
        x_pct=x_ratio * 100,
        y_pct=y_ratio * 100,
        color=BLINK_COLOR if blinking else DEFAULT_COLOR,
        blink_rule="animation: outpost-marker-blink 1s infinite;" if blinking else "",
    )


def render_marker(cid: str, x_ratio: float, y_ratio: float, *, number: int, selected: bool,
                   checked: bool | None = None, blinking: bool = False, label: str) -> None:
    """지도 위 절대 좌표에 마커 버튼 1개를 그립니다. 클릭하면 선택 상태를 토글합니다.

    checked=True면(현재 화면에 표시/재생 중인 카메라) 체크 표시가 함께 나타납니다.
    생략하면 selected 값을 그대로 사용합니다."""
    if checked is None:
        checked = selected
    st.markdown(marker_css(cid, x_ratio, y_ratio, blinking=blinking), unsafe_allow_html=True)
    with st.container(key=f"outpost_marker_{cid}"):
        help_txt = f"{label} — 클릭하여 선택 해제" if selected else f"{label} — 클릭하여 CCTV 화면 보기로 선택"
        if st.button(str(number), key=f"outpost_marker_btn_{cid}", help=help_txt):
            toggle_selection(cid)
    if checked:
        with st.container(key=f"outpost_check_{cid}"):
            st.markdown(CHECK_MARK_SVG, unsafe_allow_html=True)


def render_stop_icon(cid: str, *, label: str) -> None:
    """점멸 중인 마커 옆의 "⏹" 정지 아이콘을 그립니다(점멸만 멈추고 선택은 유지)."""
    ss = st.session_state
    with st.container(key=f"outpost_stop_{cid}"):
        if st.button("⏹", key=f"outpost_stop_btn_{cid}", help=f"{label} — 점멸 정지"):
            ss[f"blink_stopped_{cid}"] = True
            st.rerun()
