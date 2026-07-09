"""
ui/outposts/viewer.py — 대시보드 '관제 지도' 탭: 초소 지도 + 실시간 카메라 요약

views/dashboard.py의 두 번째 탭("관제 지도")에서 호출됩니다. 오른쪽 지도 위의
마커를 클릭해 "이 탭 안에서만" 볼 카메라를 고르면, 왼쪽 패널이 선택된
카메라들로 구성된 그리드를 보여줍니다. 마커는 다중 선택이 가능합니다 —
1개를 고르면 카메라 1개짜리 그리드(=단일 화면), 여러 개를 고르면 기존
'카메라 화면' 탭의 그리드와 동일한 배치 규칙(services.camera_registry.
compute_grid_columns)으로 여러 화면이 함께 표시됩니다. 아무것도 선택하지
않은 초기 상태에는 전체 카메라를 보여줍니다.

이 선택 상태(session_state._map_selected_cam_ids)는 오직 "관제 지도" 탭
안에서만 의미가 있습니다 — '카메라 화면' 탭의 구역 선택(selected_cam)이나
그리드/스포트라이트 모드에는 전혀 영향을 주지 않습니다. Streamlit은 서버
코드로 현재 활성 탭을 강제 전환하는 기능도 제공하지 않으므로, 애초에 다른
탭으로 자동 이동시키는 것도 불가능합니다 — 그래서 두 탭의 "어느 카메라를
보고 있는지" 상태는 완전히 독립적으로 분리해두었습니다.

사람이 탐지된 카메라의 마커는 점멸(blink)합니다. 점멸 마커를 클릭하면(=마커
본체) 선택 토글만 될 뿐 점멸은 멈추지 않습니다 — 점멸을 멈추려면 마커 옆에
별도로 붙는 작은 "⏹" 정지 아이콘을 클릭해야 합니다. 정지 상태는 추적이
끊겨(person_tracks가 비어) 자동 해제되면 다음 탐지부터 다시 점멸합니다.

왼쪽 패널이 ui/camera/card.py의 인터랙티브 카드를 재사용하지 않는 이유:
Streamlit은 st.tabs()의 모든 탭 내용을 매 스크립트 실행마다 함께 그리므로
(화면에 보이지 않는 탭도 코드가 실행됨), 같은 위젯 key를 가진 카드를
'카메라 화면' 탭과 이 탭에 동시에 두면 key 충돌로 앱이 즉시 오류를 냅니다.
그래서 이 탭은 업로드/재생 제어가 없는 st.image() 기반 읽기 전용 화면만
보여주고, 실제 조작(업로드/확대 등)은 '카메라 화면' 탭에서 하도록 역할을
분리했습니다.
"""
import io

import streamlit as st
from PIL import Image

from services import outposts as outposts_service
from services.camera_registry import compute_grid_columns

_BLINK_CSS = """
<style>
@keyframes outpost-marker-blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.15; } }
div[class*="st-key-outpost_map_wrap"] { position: relative; }
</style>
"""


def _blank_thumb() -> Image.Image:
    """카메라에 아직 프레임이 없을 때 표시할 자리표시자 (16:9 비율)."""
    return Image.new("RGB", (320, 180), color=(230, 232, 235))


def _selected_ids() -> set:
    return set(st.session_state.get("_map_selected_cam_ids", []))


def _toggle_selection(cid: str) -> None:
    """마커 클릭 시 선택 상태를 토글합니다 (지도 탭 전용 — 다른 탭 상태는 건드리지 않음)."""
    ss = st.session_state
    selected = _selected_ids()
    if cid in selected:
        selected.discard(cid)
    else:
        selected.add(cid)
    ss["_map_selected_cam_ids"] = list(selected)
    st.rerun()


def _render_camera_summary(cameras: list[dict]) -> None:
    """왼쪽 패널 — 지도에서 선택한 카메라들을 그리드로 나열합니다 (읽기 전용).
    아무것도 선택되지 않았으면 전체 카메라를 그리드로 보여줍니다."""
    ss = st.session_state
    st.markdown("**CCTV 화면**")
    if not cameras:
        st.caption("등록된 카메라가 없습니다.")
        return

    selected = _selected_ids()
    display_cams = [c for c in cameras if c["id"] in selected] or cameras
    if selected:
        st.caption(f"선택된 카메라 {len(display_cams)}개 — 지도에서 마커를 다시 클릭하면 선택이 해제됩니다.")
    else:
        st.caption("전체 카메라 표시 중 — 지도에서 마커를 클릭하면 해당 카메라만 볼 수 있습니다.")

    cols_per_row = compute_grid_columns(len(display_cams))
    for row_start in range(0, len(display_cams), cols_per_row):
        row_cams = display_cams[row_start: row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, cam in zip(cols, row_cams):
            with col:
                cid = cam["id"]
                frame = ss.get(f"result_{cid}")
                has_person = bool(ss.get(f"person_tracks_{cid}"))
                caption = f"🔴 {cam['name']} · 사람 탐지중" if has_person else cam["name"]
                st.image(frame if frame is not None else _blank_thumb(),
                          use_container_width=True, caption=caption)


def _marker_css(cid: str, x_ratio: float, y_ratio: float, blinking: bool, selected: bool) -> str:
    """마커 1개의 절대 위치 + 상태별(점멸/선택) 스타일을 담은 CSS 블록.
    ui/camera/zoom.py의 오버레이 위치 지정 패턴(div[class*="st-key-..."])을 그대로 따릅니다."""
    blink_rule = "animation: outpost-marker-blink 1s infinite;" if blinking else ""
    color = "#f85149" if blinking else "#58a6ff"
    ring_rule = "box-shadow: 0 0 0 3px #ffffff, 0 0 0 5px #3fb950;" if selected else ""
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
        width: 20px; height: 20px; padding: 0; border-radius: 50%;
        background-color: {color} !important; color: white !important;
        border: 2px solid white !important;
        {blink_rule}
        {ring_rule}
    }}
    div[class*="st-key-outpost_stop_{cid}"] {{
        position: absolute;
        left: calc({x_ratio * 100:.3f}% + 15px);
        top: calc({y_ratio * 100:.3f}% - 15px);
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


def _render_map(cameras: list[dict]) -> None:
    """오른쪽 패널 — 지도 이미지 위에 초소 마커를 겹쳐 그립니다. 마커를 클릭하면
    왼쪽 패널에 표시할 카메라 선택이 토글되고(다중 선택 가능), 점멸 중인 마커는
    옆에 별도 "⏹" 정지 아이콘이 함께 붙습니다."""
    ss = st.session_state
    st.markdown("**관제 지도**")

    map_bytes = outposts_service.get_map_image_bytes()
    outposts = outposts_service.get_outposts()
    if map_bytes is None or not outposts:
        st.info("설정 페이지에서 지도를 업로드하고 초소를 마킹하면 여기에 표시됩니다.")
        return

    cam_name_by_id = {c["id"]: c["name"] for c in cameras}
    selected = _selected_ids()
    st.markdown(_BLINK_CSS, unsafe_allow_html=True)

    with st.container(key="outpost_map_wrap"):
        st.image(Image.open(io.BytesIO(map_bytes)), use_container_width=True)

        for o in outposts:
            cid = o["id"]
            cam_name = cam_name_by_id.get(cid, cid)
            tracks = ss.get(f"person_tracks_{cid}")
            is_blinking = bool(tracks) and not ss.get(f"blink_stopped_{cid}", False)
            # 추적이 끊기면(더 이상 사람이 없으면) 정지 상태를 해제해 다음 탐지 때 다시 점멸하도록 함
            if not tracks:
                ss.pop(f"blink_stopped_{cid}", None)

            is_selected = cid in selected
            st.markdown(_marker_css(cid, o["x_ratio"], o["y_ratio"], is_blinking, is_selected),
                        unsafe_allow_html=True)

            # 마커 본체 — 클릭하면 왼쪽 패널의 카메라 선택을 토글 (점멸은 멈추지 않음)
            with st.container(key=f"outpost_marker_{cid}"):
                help_txt = f"{cam_name} — 클릭하여 선택 해제" if is_selected else f"{cam_name} — 클릭하여 선택"
                if st.button("●", key=f"outpost_marker_btn_{cid}", help=help_txt):
                    _toggle_selection(cid)

            # 점멸 중일 때만 별도 정지 아이콘 노출
            if is_blinking:
                with st.container(key=f"outpost_stop_{cid}"):
                    if st.button("⏹", key=f"outpost_stop_btn_{cid}",
                                 help=f"{cam_name} — 점멸 정지"):
                        ss[f"blink_stopped_{cid}"] = True
                        st.rerun()


def render_outpost_map(cameras: list[dict]) -> None:
    """대시보드 '관제 지도' 탭 전체(왼쪽 CCTV 그리드 + 오른쪽 지도)를 렌더링합니다."""
    ss = st.session_state
    # 삭제된 카메라가 선택 목록에 남아있지 않도록 정리 (초소 삭제/전체초기화 대응)
    valid_ids = {c["id"] for c in cameras}
    stale = [cid for cid in ss.get("_map_selected_cam_ids", []) if cid not in valid_ids]
    if stale:
        ss["_map_selected_cam_ids"] = [cid for cid in ss["_map_selected_cam_ids"] if cid not in stale]

    left, right = st.columns([1, 1])
    with left:
        _render_camera_summary(cameras)
    with right:
        _render_map(cameras)
