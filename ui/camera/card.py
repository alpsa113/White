"""ui/camera/card.py — 카메라 카드(영상 슬롯+오버레이+확대) 렌더링. EO/TIR 중 선택된 채널 하나만 재생하며, 채널 전환 시 멈춘 지점부터 이어서 재생됩니다."""

import streamlit as st
from PIL import Image
from urllib.parse import quote

from config import API_BASE_URL
from services import outposts as outposts_service
from services.playback import HAS_CV2, reset_cam_state, start_camera_media
from ui.camera.zoom import inject_live_zoom_script, inject_reset_zoom_script
from ui.styles import CARD_CSS_TEMPLATE, IMG_WRAP_CSS_TEMPLATE, TOPBAR_CSS_TEMPLATE


@st.cache_data
def _blank_placeholder() -> Image.Image:
    """매핑 전 표시할 16:9 빈 화면(캐시됨)."""
    return Image.new("RGB", (960, 540), color=(17, 24, 33))


def render_camera_card(cam: dict, video_slots: dict, *, is_focused: bool = False) -> None:
    """카메라 1대에 대한 카드를 렌더링합니다.

    is_focused=True면(지도 마커로 필터링된 그리드) '전체 구역' 그리드여도
    집중 보기와 같은 컨트롤(전체 보기로 돌아가기/줌 리셋)을 보여줍니다."""
    ss = st.session_state
    cid = cam["id"]
    is_grid = ss.get("selected_cam") == "전체 구역" and not is_focused
    # 그리드/집중보기는 컨테이너 구조(열 개수 등)가 서로 달라, 같은 key를 그대로
    # 재사용하면 Streamlit이 레이아웃 전환 시 이전 모드의 DOM 조각을 잘못 이어붙여
    # 화면이 중복/깨져 보이는 문제가 있었습니다. 모드별로 key를 분리해 방지합니다.
    mode = "grid" if is_grid else "spot"

    with st.container(border=True, key=f"card_{cid}_{mode}"):
        st.markdown(CARD_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
        image_slot = _render_image_area(cam, is_grid, mode, video_slots)

        if not is_grid:
            inject_live_zoom_script(cid)
            if ss.pop(f"_reset_zoom_pending_{cid}", False):
                inject_reset_zoom_script(cid)

        _render_playback_state(cam, mode, image_slot)


def _render_channel_toggle(cam: dict, mode: str) -> None:
    """EO/TIR 전환 탭. 매핑된 채널만 누를 수 있습니다.

    disabled 버튼에는 help를 넣지 않습니다 — Streamlit이 이중 DOM 래퍼를 만들어 레이아웃이 깨집니다."""
    ss = st.session_state
    cid = cam["id"]
    active = ss.get(f"active_channel_{cid}", "eo")

    eo_video = outposts_service.get_marker_video(cid, "eo")
    tir_video = outposts_service.get_marker_video(cid, "tir")

    with st.container(key=f"channel_toggle_{cid}_{mode}", horizontal=True):
        if st.button(
            "EO", key=f"chan_eo_{cid}_{mode}",
            type="primary" if active == "eo" else "secondary",
            disabled=eo_video is None,
            help="EO(가시광) 영상으로 전환" if eo_video is not None else None,
        ):
            _switch_channel(cam, "eo", eo_video)

        if st.button(
            "TIR", key=f"chan_tir_{cid}_{mode}",
            type="primary" if active == "tir" else "secondary",
            disabled=tir_video is None,
            help="TIR(열화상) 영상으로 전환" if tir_video is not None else None,
        ):
            _switch_channel(cam, "tir", tir_video)


def _switch_channel(cam: dict, channel: str, video: tuple[str, str] | None) -> None:
    """재생 채널을 EO/TIR 중 하나로 전환합니다. 이미 재생해본 채널이면 멈춘 지점부터 이어서 재생합니다."""
    ss = st.session_state
    cid = cam["id"]
    if ss.get(f"active_channel_{cid}", "eo") == channel:
        return
    ss[f"active_channel_{cid}"] = channel
    if video:
        path, filename = video
        suffix = f"_{channel}"
        result = start_camera_media(cam, None, filename, state_suffix=suffix, src_path=path)
        if result == "unchanged":
            ss[f"playing_{cid}{suffix}"] = True
            ss.pop(f"play_start_wall_{cid}{suffix}", None)
            ss[f"stream_start_frame_{cid}{suffix}"] = ss.get(f"cursor_{cid}{suffix}", 0)
        else:
            ss[f"stream_start_frame_{cid}{suffix}"] = 0
    else:
        reset_cam_state(cid, state_suffix=f"_{channel}")
    st.rerun()


def _render_image_area(cam: dict, is_grid: bool, mode: str, video_slots: dict):
    """카드 상단 툴바와 영상 영역을 그리고, 프레임 표시용 st.empty() 슬롯을 반환합니다."""
    ss = st.session_state
    cid = cam["id"]

    st.markdown(TOPBAR_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)

    with st.container(key=f"topbar_{cid}_{mode}"):
        if is_grid:
            if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                ss["_pending_selected_cam"] = cam["name"]
                st.rerun()
        else:
            st.markdown(f"**{cam['name']}**")

        with st.container(key=f"controls_{cid}_{mode}", horizontal=True):
            _render_channel_toggle(cam, mode)

            with st.container(key=f"view_toggle_{cid}_{mode}", horizontal=True):
                if is_grid:
                    if st.button("⤡", key=f"expand_btn_{cid}", help="화면 확대"):
                        ss["_pending_selected_cam"] = cam["name"]
                        st.rerun()
                else:
                    if st.button("🗗", key=f"grid_btn_{cid}", help="전체 그리드로 돌아가기"):
                        ss["selected_cam"] = "전체 구역"
                        ss["_map_selected_cam_ids"] = []
                        st.rerun()
                    if st.button("↺", key=f"reset_zoom_{cid}", help="원본으로 돌아가기"):
                        ss[f"_reset_zoom_pending_{cid}"] = True

    st.markdown(IMG_WRAP_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
    with st.container(key=f"img_wrap_{cid}_{mode}"):
        image_slot = st.empty()

        active_channel = ss.get(f"active_channel_{cid}", "eo")
        suffix = f"_{active_channel}"
        tmp_path = ss.get(f"tmp_path_{cid}{suffix}")
        use_stream = (not ss.get("simulate", True)) and HAS_CV2 and tmp_path and ss.get(f"playing_{cid}{suffix}")
        if use_stream:
            fps = ss.get(f"fps_{cid}{suffix}", 30.0)
            start_frame = ss.get(f"stream_start_frame_{cid}{suffix}", 0)
            stream_url = f"{API_BASE_URL}/stream?path={quote(tmp_path)}&fps={fps}&start_frame={start_frame}"
            image_slot.markdown(
                f'<img src="{stream_url}" style="width:100%; border-radius:4px; display:block;">',
                unsafe_allow_html=True,
            )
        else:
            video_slots[cid] = image_slot

    return image_slot


def _render_playback_state(cam: dict, mode: str, image_slot) -> None:
    """매핑 전 / 재생 중 / 정지(또는 완료) 상태에 맞는 화면을 그립니다(현재 선택 채널 기준)."""
    ss = st.session_state
    cid = cam["id"]
    suffix = f"_{ss.get(f'active_channel_{cid}', 'eo')}"

    if ss.get(f"fp_{cid}{suffix}") is None:
        image_slot.image(_blank_placeholder(), use_container_width=True)

    elif ss.get(f"playing_{cid}{suffix}"):
        if st.button("⏸️ 일시정지 (테스트용)", key=f"pause_btn_{cid}_{mode}", use_container_width=True):
            ss[f"playing_{cid}{suffix}"] = False
            st.rerun()
    else:
        result = ss.get(f"result_{cid}{suffix}")
        if result:
            image_slot.image(result, use_container_width=True)

        cap = ss.get(f"cap_{cid}{suffix}")
        if not ss.get(f"finished_{cid}{suffix}") and cap is not None and cap.isOpened():
            if st.button("▶️ 재개 (테스트용)", key=f"resume_btn_{cid}_{mode}", use_container_width=True):
                ss[f"playing_{cid}{suffix}"] = True
                ss.pop(f"play_start_wall_{cid}{suffix}", None)
                st.rerun()

        if ss.get(f"finished_{cid}{suffix}"):
            st.caption("영상 재생에 실패했습니다 — '설정' 페이지에서 영상을 다시 매핑해주세요.")
