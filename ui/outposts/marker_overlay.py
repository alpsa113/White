"""
ui/outposts/marker_overlay.py — 지도 위 초소 마커 오버레이 (관제 지도) +
마커 선택 상태 공용 로직 (설정 페이지 지도 미리보기와도 공유)

"관제 지도"는 더 이상 별도 탭이 아니라, '실시간 감시' 페이지가 스포트라이트
(특정 카메라 포커스) 모드일 때 우측에 끼워 넣는 패널입니다
(ui/camera/spotlight.py → ui/outposts/viewer.render_map). 이 파일은 그
지도의 마커 렌더링과, 설정 페이지 지도 미리보기·관제 지도·'카메라 화면'
그리드 필터가 함께 쓰는 "CCTV 화면 보기" 선택 상태를 담당합니다.

색상 규칙 (설정 페이지 지도 미리보기 · 관제 지도 공통):
- 기본(아직 CCTV 화면 보기로 선택되지 않음): 하늘색(#58a6ff)
- "CCTV 화면 보기"로 선택됨: 빨간색(#f85149)
  → session_state._map_selected_cam_ids(두 화면이 공유하는 선택 상태)에
    포함되어 있으면 선택된 것으로 간주합니다.

`toggle_selection()`을 호출하면 `_map_selected_cam_ids`(다중 선택 상태)가
갱신됩니다. 이 상태는 세 곳 모두에서 같은 뜻으로 쓰입니다: 관제 지도의
왼쪽 CCTV 요약, 두 화면의 마커 색상, 그리고 '실시간 감시' 페이지에 표시할
카메라 필터(views/dashboard.py가 이 값을 직접 읽어 선택된 카메라들만
그리드로 보여줍니다 — 스포트라이트로 확대하는 것이 아니라 기존 그리드
배치 그대로 대상만 좁히는 것입니다).

`render_marker()`(클릭 가능한 마커 버튼)는 관제 지도(스포트라이트 우측
패널)에서만 사용합니다. 설정 페이지의 지도 미리보기는 새 마커를 클릭으로
추가해야 해서 `streamlit_image_coordinates`가 이미 클릭을 가로채므로, 그
위에 마커 버튼을 또 겹치지 않고 대신 PIL로 마커를 이미지에 그려 넣어
보여주기만 하고(`ui/outposts/editor.py` 참고), 선택/해제·삭제는 목록의
별도 버튼으로 `toggle_selection()`/`services.outposts.remove_marker()`를
직접 호출합니다.

점멸(사람 탐지)은 색상과는 별개 축입니다 — 선택 여부와 무관하게 현재
색상(빨강/하늘색) 그대로 깜빡이는 효과만 덧붙습니다. 정지(⏹) 아이콘은
점멸 중일 때만 그리는 관제 지도에서 선택적으로 사용합니다.
"""
import streamlit as st

SELECTED_COLOR = "#f85149"   # CCTV 화면 보기로 선택된 마커
DEFAULT_COLOR = "#58a6ff"    # 기본(미선택) 마커 — 하늘색

MAP_WRAP_KEY = "outpost_map_wrap"  # 관제 지도 탭이 이 key로 지도 래퍼 컨테이너를 감싸야 마커 절대좌표 기준점이 잡힘

BLINK_CSS = f"""
<style>
@keyframes outpost-marker-blink {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.15; }} }}
div[class*="st-key-{MAP_WRAP_KEY}"] {{ position: relative; }}
</style>
"""


def selected_ids() -> set:
    """세 화면(설정 페이지 지도, 관제 지도 탭, 카메라 화면 탭)이 공유하는
    "CCTV 화면 보기" 선택 상태를 반환합니다."""
    return set(st.session_state.get("_map_selected_cam_ids", []))


def toggle_selection(cid: str) -> None:
    """마커 클릭(또는 목록의 선택 버튼) 시 선택 상태를 토글합니다
    (설정 페이지 지도 / 관제 지도 탭 / 카메라 화면 탭 공용)."""
    ss = st.session_state
    ids = selected_ids()
    if cid in ids:
        ids.discard(cid)
    else:
        ids.add(cid)
    ss["_map_selected_cam_ids"] = list(ids)
    st.rerun()


def marker_css(cid: str, x_ratio: float, y_ratio: float, *, selected: bool, blinking: bool = False) -> str:
    """마커 1개(+옆에 붙는 정지 아이콘)의 절대 위치 + 상태별(선택/점멸) 스타일.
    ui/camera/zoom.py의 오버레이 위치 지정 패턴(div[class*="st-key-..."])을 그대로 따릅니다.
    설정 페이지 지도 미리보기(ui/outposts/editor._draw_markers)가 PIL로 그리는
    "번호 매긴 원" 모양과 맞추기 위해, 버튼 안에 번호가 들어갈 수 있도록
    크기/폰트를 키웠습니다(§3.2 두 화면 모두 같은 마커 모양)."""
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
        width: 26px; height: 26px; padding: 0; border-radius: 50%;
        background-color: {color} !important; color: white !important;
        border: 2px solid white !important;
        font-size: 13px; font-weight: 700; line-height: 1;
        {blink_rule}
    }}
    div[class*="st-key-outpost_stop_{cid}"] {{
        position: absolute;
        left: calc({x_ratio * 100:.3f}% + 18px);
        top: calc({y_ratio * 100:.3f}% - 18px);
        transform: translate(-50%, -50%);
        z-index: 11;
        width: auto !important;
    }}
    div[class*="st-key-outpost_stop_{cid}"] button {{
        width: 18px; height: 18px; padding: 0; border-radius: 50%;
        background-color: #21262d !important; color: white !important;
        border: 1px solid white !important; font-size: 10px; line-height: 1;
    }}
    </style>
    """


def render_marker(cid: str, x_ratio: float, y_ratio: float, *, number: int, selected: bool,
                   blinking: bool = False, label: str) -> None:
    """지도 위 절대 좌표에 마커 버튼 1개를 그립니다 (설정 페이지 지도 미리보기와
    동일하게 번호가 적힌 원 — number는 1-based CCTV 번호). 클릭하면 공유
    선택 상태를 토글합니다."""
    st.markdown(marker_css(cid, x_ratio, y_ratio, selected=selected, blinking=blinking),
                unsafe_allow_html=True)
    with st.container(key=f"outpost_marker_{cid}"):
        help_txt = f"{label} — 클릭하여 선택 해제" if selected else f"{label} — 클릭하여 CCTV 화면 보기로 선택"
        if st.button(str(number), key=f"outpost_marker_btn_{cid}", help=help_txt):
            toggle_selection(cid)


def render_stop_icon(cid: str, *, label: str) -> None:
    """점멸 중인 마커 옆에 붙는 "⏹" 정지 아이콘을 그립니다 (점멸만 멈추고 선택은 건드리지 않음)."""
    ss = st.session_state
    with st.container(key=f"outpost_stop_{cid}"):
        if st.button("⏹", key=f"outpost_stop_btn_{cid}", help=f"{label} — 점멸 정지"):
            ss[f"blink_stopped_{cid}"] = True
            st.rerun()
