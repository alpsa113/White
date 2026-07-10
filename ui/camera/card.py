"""ui/camera/card.py — 카메라 카드(영상 슬롯+오버레이+확대) 렌더링. EO/TIR 중 선택된 채널 하나만 재생하며, 채널 전환 시 멈춘 지점부터 이어서 재생됩니다."""

import streamlit as st
from PIL import Image
from urllib.parse import quote

from config import API_BASE_URL
from services import outposts as outposts_service
from services.playback import HAS_CV2, reset_cam_state, start_camera_media
from ui.camera.zoom import IMG_WRAP_CSS_TEMPLATE, inject_live_zoom_script

# 카드 상단 툴바 CSS — [카메라 이름] .......... [EO][TIR][▦/⛶][↺]
# 컨테이너 쿼리(cqw)로 카드 폭에 비례해 배지 크기가 커지고 작아집니다.
TOPBAR_CSS_TEMPLATE = """
<style>
div[class*="st-key-topbar_{cid}"] {{
    width: 100% !important;
    padding: 1.6cqw 2cqw;
    display: flex !important;
    flex-direction: row !important;
    flex-wrap: nowrap !important;
    align-items: center;
    justify-content: space-between;
    gap: 1.5cqw;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) {{
    flex: 1 1 0;
    min-width: 0;
    overflow-x: hidden;
    overflow-y: visible;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) button,
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) p {{
    display: inline-block !important;
    width: auto !important;
    max-width: 100% !important;
    min-width: 0 !important;
    box-sizing: border-box !important;
    overflow-x: hidden !important;
    overflow-y: visible !important;
    text-overflow: ellipsis !important;
    white-space: nowrap !important;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(2) {{
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
}}
div[class*="st-key-topbar_{cid}"] p {{
    margin: 0 !important;
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px);
    font-size: clamp(0.55rem, 3cqw, 0.85rem);
    line-height: 1.4;
    display: inline-block;
    white-space: nowrap;
}}
div[class*="st-key-topbar_{cid}"] button {{
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px) !important;
    min-height: 0 !important;
    height: auto !important;
    white-space: nowrap !important;
    flex-shrink: 0;
}}
div[class*="st-key-topbar_{cid}"] button p {{
    font-size: clamp(0.55rem, 3cqw, 0.85rem) !important;
    margin: 0 !important;
    white-space: nowrap !important;
}}
div[class*="st-key-controls_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-controls_{cid}"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
    align-items: center;
    gap: clamp(3px, 1.2cqw, 8px);
}}
div[class*="st-key-channel_toggle_{cid}"],
div[class*="st-key-view_toggle_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-channel_toggle_{cid}"],
div[data-testid="stHorizontalBlock"][class*="st-key-view_toggle_{cid}"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    flex: 0 0 auto !important;
    width: auto !important;
    max-width: none !important;
    gap: clamp(2px, 1cqw, 6px);
}}
div[class*="st-key-controls_{cid}"] > div[data-testid="stLayoutWrapper"] {{
    width: auto !important;
    max-width: none !important;
    flex: 0 0 auto !important;
}}
</style>
"""

# 카드 여백 최소화 + cqw 기준점(container-type) 선언
CARD_CSS_TEMPLATE = """
<style>
div[class*="st-key-card_{cid}"] {{
    padding: 0.35rem !important;
    container-type: inline-size;
}}
</style>
"""


@st.cache_data
def _blank_placeholder() -> Image.Image:
    """매핑 전 표시할 16:9 빈 화면(캐시됨)."""
    return Image.new("RGB", (960, 540), color=(230, 232, 235))


def render_camera_card(cam: dict, video_slots: dict) -> None:
    """카메라 1대에 대한 카드를 렌더링합니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True, key=f"card_{cid}"):
        st.markdown(CARD_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
        is_grid = ss.get("selected_cam") == "전체 구역"
        image_slot = _render_image_area(cam, is_grid, video_slots)

        if not is_grid:
            inject_live_zoom_script(cid)

        _render_playback_state(cam, image_slot)


def _render_channel_toggle(cam: dict) -> None:
    """EO/TIR 전환 탭. 매핑된 채널만 누를 수 있습니다.

    disabled 버튼에는 help를 넣지 않습니다 — Streamlit이 이중 DOM 래퍼를 만들어 레이아웃이 깨집니다."""
    ss = st.session_state
    cid = cam["id"]
    active = ss.get(f"active_channel_{cid}", "eo")

    eo_video = outposts_service.get_marker_video(cid, "eo")
    tir_video = outposts_service.get_marker_video(cid, "tir")

    with st.container(key=f"channel_toggle_{cid}", horizontal=True):
        if st.button(
            "EO", key=f"chan_eo_{cid}",
            type="primary" if active == "eo" else "secondary",
            disabled=eo_video is None,
            help="EO(가시광) 영상으로 전환" if eo_video is not None else None,
        ):
            _switch_channel(cam, "eo", eo_video)

        if st.button(
            "TIR", key=f"chan_tir_{cid}",
            type="primary" if active == "tir" else "secondary",
            disabled=tir_video is None,
            help="TIR(열화상) 영상으로 전환" if tir_video is not None else None,
        ):
            _switch_channel(cam, "tir", tir_video)


def _switch_channel(cam: dict, channel: str, video: tuple[bytes, str] | None) -> None:
    """재생 채널을 EO/TIR 중 하나로 전환합니다. 이미 재생해본 채널이면 멈춘 지점부터 이어서 재생합니다."""
    ss = st.session_state
    cid = cam["id"]
    if ss.get(f"active_channel_{cid}", "eo") == channel:
        return
    ss[f"active_channel_{cid}"] = channel
    if video:
        suffix = f"_{channel}"
        result = start_camera_media(cam, video[0], video[1], state_suffix=suffix)
        if result == "unchanged":
            ss[f"playing_{cid}{suffix}"] = True
            ss.pop(f"play_start_wall_{cid}{suffix}", None)
    else:
        reset_cam_state(cid, state_suffix=f"_{channel}")
    st.rerun()


def _render_image_area(cam: dict, is_grid: bool, video_slots: dict):
    """카드 상단 툴바와 영상 영역을 그리고, 프레임 표시용 st.empty() 슬롯을 반환합니다."""
    ss = st.session_state
    cid = cam["id"]

    st.markdown(TOPBAR_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)

    with st.container(key=f"topbar_{cid}"):
        if is_grid:
            if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                ss["_pending_selected_cam"] = cam["name"]
                st.rerun()
        else:
            st.markdown(f"**{cam['name']}**")

        with st.container(key=f"controls_{cid}", horizontal=True):
            _render_channel_toggle(cam)

            with st.container(key=f"view_toggle_{cid}", horizontal=True):
                if is_grid:
                    if st.button("⛶", key=f"expand_btn_{cid}", help="이 카메라 크게 보기"):
                        ss["_pending_selected_cam"] = cam["name"]
                        st.rerun()
                else:
                    if st.button("▦", key=f"grid_btn_{cid}", help="전체 그리드로 돌아가기"):
                        ss["selected_cam"] = "전체 구역"
                        ss["_map_selected_cam_ids"] = []
                        st.rerun()
                    if st.button("↺", key=f"reset_zoom_{cid}", help="확대 초기화"):
                        st.markdown(
                            f"<script>window.parent.document.querySelectorAll("
                            f"'div[class*=\"st-key-img_wrap_{cid}\"] img').forEach("
                            f"el => el.style.transform = 'none');</script>",
                            unsafe_allow_html=True,
                        )

    st.markdown(IMG_WRAP_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
    with st.container(key=f"img_wrap_{cid}"):
        image_slot = st.empty()

        active_channel = ss.get(f"active_channel_{cid}", "eo")
        suffix = f"_{active_channel}"
        tmp_path = ss.get(f"tmp_path_{cid}{suffix}")
        use_stream = (not ss.get("simulate", True)) and HAS_CV2 and tmp_path and ss.get(f"playing_{cid}{suffix}")
        if use_stream:
            fps = ss.get(f"fps_{cid}{suffix}", 30.0)
            stream_url = f"{API_BASE_URL}/stream?path={quote(tmp_path)}&fps={fps}"
            image_slot.markdown(
                f'<img src="{stream_url}" style="width:100%; border-radius:4px; display:block;">',
                unsafe_allow_html=True,
            )
        else:
            video_slots[cid] = image_slot

    return image_slot


def _render_playback_state(cam: dict, image_slot) -> None:
    """매핑 전 / 재생 중 / 정지(또는 완료) 상태에 맞는 화면을 그립니다(현재 선택 채널 기준)."""
    ss = st.session_state
    cid = cam["id"]
    suffix = f"_{ss.get(f'active_channel_{cid}', 'eo')}"

    if ss.get(f"fp_{cid}{suffix}") is None:
        image_slot.image(_blank_placeholder(), use_container_width=True)

    elif ss.get(f"playing_{cid}{suffix}"):
        if st.button("⏸️ 일시정지 (테스트용)", key=f"pause_btn_{cid}", use_container_width=True):
            ss[f"playing_{cid}{suffix}"] = False
            st.rerun()
    else:
        result = ss.get(f"result_{cid}{suffix}")
        if result:
            image_slot.image(result, use_container_width=True)

        cap = ss.get(f"cap_{cid}{suffix}")
        if not ss.get(f"finished_{cid}{suffix}") and cap is not None and cap.isOpened():
            if st.button("▶️ 재개 (테스트용)", key=f"resume_btn_{cid}", use_container_width=True):
                ss[f"playing_{cid}{suffix}"] = True
                ss.pop(f"play_start_wall_{cid}{suffix}", None)
                st.rerun()

        if ss.get(f"finished_{cid}{suffix}"):
            st.caption("영상 재생에 실패했습니다 — '설정' 페이지에서 영상을 다시 매핑해주세요.")
