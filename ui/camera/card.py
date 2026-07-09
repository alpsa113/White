"""
ui/camera/card.py — 카메라 카드(영상 슬롯+오버레이+확대) 렌더링

그리드/집중 보기가 공유하는 카드 UI 본체입니다. 확대/이동 기능은
ui/camera/zoom.py에, 탐지 로직은 services/tracking.py·playback.py에 위임하고
이 파일은 카드 레이아웃과 상태 전환(대기 → 재생 중 → 정지/완료)만 담당합니다.

영상 업로드는 이 카드에 있지 않습니다 — '설정' 페이지(ui/outposts/editor.py)에서
초소별로 EO/TIR CCTV 영상을 미리 매핑해두면, services/camera_registry.py가
대시보드 진입 시 자동으로 EO 영상의 재생을 시작합니다
(services/playback.start_camera_media). 카드 상단 오버레이 바의 EO/TIR
탭으로 그 중 어느 채널을 재생할지 즉석에서 전환할 수 있습니다(§_render_channel_toggle).

예전에 사이드바에 있던 "구역 선택" 드롭다운(전체 구역 ↔ 특정 카메라)은
제거되었습니다 — 특정 카메라로 전환은 그리드 모드의 ⛶ 버튼(또는 사람 탐지
시 자동)으로, 전체 그리드로 되돌아가는 것은 집중 보기(스포트라이트) 모드의
▦ 버튼으로 각 카드 자체에서 직접 할 수 있습니다.
"""

import streamlit as st
from PIL import Image
from urllib.parse import quote

from config import API_BASE_URL
from services import outposts as outposts_service
from services.playback import HAS_CV2, reset_cam_state, start_camera_media
from ui.camera.zoom import IMG_WRAP_CSS_TEMPLATE, inject_live_zoom_script

# ------------------------------------------------------------------ #
# 영상 위 상단 오버레이 바 — [카메라 이름] [EO/TIR 전환] [▦ 그리드 보기 / ⛶ 확대 / ↺ 초기화] 한 줄 배치
#
# CSS Grid(1fr auto 1fr)로 3영역을 나눠, 이름은 항상 좌측 끝, EO/TIR 전환은
# 항상 정중앙, ⛶/▦·↺는 항상 우측 끝에 붙도록 고정합니다(양쪽 폭이 서로
# 달라도 가운데 그룹이 흔들리지 않음 — flex "space-between"만으로는 이걸
# 보장할 수 없어 grid를 씁니다).
#
# 폰트/패딩은 고정 px가 아니라 **컨테이너 쿼리**(cqw = 이 카드 자신의 가로폭
# 기준 %)로 지정합니다 — 그리드 칸이 5~7개로 좁아지거나, 가로 스크롤 나머지
# 카메라 카드(320px)처럼 작아져도, 카드 폭에 비례해 배지 크기/글자가 함께
# 작아져서 서로 겹치거나 다음 카드로 번지지 않습니다. `container-type:
# inline-size`는 ui/camera/zoom.py의 IMG_WRAP_CSS_TEMPLATE(topbar의 바로
# 위 부모)에 선언되어 있습니다. clamp()로 최소/최대 크기를 둬서 카드가
# 아주 작거나 아주 커도 글자가 지나치게 작아지거나 커지지 않게 막습니다.
#
# EO/TIR 두 버튼은 flex-wrap을 nowrap으로 강제합니다 — 지정하지 않으면
# 카드가 좁을 때 두 버튼이 세로로 줄바꿈되면서 이름 텍스트와 겹쳐 보이는
# 문제가 있었습니다. 이름 쪽도 min-width:0 + ellipsis로 넘치는 대신
# "..."으로 잘리게 해 가운데/오른쪽 영역을 침범하지 않도록 했습니다.
#
# 모든 배지(이름/EO·TIR/아이콘 버튼)를 밝은 배경 + 검은 글씨의 알약(pill)
# 모양으로 통일해, 영상 내용이 밝든 어둡든 항상 잘 보이게 합니다. 현재
# 선택된(primary) 버튼은 파란색 대신, 살짝 어두운 회색 음영 + 안쪽 그림자로
# "눌린" 느낌만 주어 자연스럽게 구분되도록 했습니다.
# ------------------------------------------------------------------ #
TOPBAR_CSS_TEMPLATE = """
<style>
div[class*="st-key-topbar_{cid}"] {{
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    z-index: 12;
    width: 100% !important;
    padding: 1.6cqw 2cqw;
    display: grid !important;
    grid-template-columns: 1fr auto 1fr;
    align-items: center;
    column-gap: 1.5cqw;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) {{
    justify-self: start;
    min-width: 0;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) button,
div[class*="st-key-topbar_{cid}"] > div:nth-child(1) p {{
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
}}
div[class*="st-key-topbar_{cid}"] > div:nth-child(2) {{ justify-self: center; min-width: 0; }}
div[class*="st-key-topbar_{cid}"] > div:nth-child(3) {{ justify-self: end; min-width: 0; }}
div[class*="st-key-topbar_{cid}"] p {{
    background-color: rgba(255,255,255,0.92);
    color: #111111 !important;
    margin: 0 !important;
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px);
    border-radius: 6px;
    font-size: clamp(0.55rem, 3cqw, 0.85rem);
    line-height: 1.4;
    display: inline-block;
    white-space: nowrap;
}}
div[class*="st-key-topbar_{cid}"] button {{
    background-color: rgba(255,255,255,0.92) !important;
    color: #111111 !important;
    border: 1px solid rgba(0,0,0,0.15) !important;
    border-radius: 6px !important;
    padding: clamp(1px, 0.8cqw, 5px) clamp(4px, 2cqw, 10px) !important;
    font-weight: 600;
    opacity: 1 !important;
    min-height: 0 !important;
    height: auto !important;
}}
div[class*="st-key-topbar_{cid}"] button p {{
    font-size: clamp(0.55rem, 3cqw, 0.85rem) !important;
    margin: 0 !important;
}}
div[class*="st-key-topbar_{cid}"] button[data-testid="stBaseButton-primary"] {{
    background-color: #cbd5e1 !important;
    color: #111111 !important;
    border-color: #94a3b8 !important;
    box-shadow: inset 0 1px 3px rgba(0,0,0,0.18);
}}
div[class*="st-key-channel_toggle_{cid}"],
div[class*="st-key-view_toggle_{cid}"] {{
    display: flex !important;
    flex-wrap: nowrap !important;
    width: auto !important;
    gap: clamp(2px, 1cqw, 6px);
}}
</style>
"""


@st.cache_data
def _blank_placeholder() -> Image.Image:
    """매핑 전 카드에 표시할 빈 화면 — 실제 영상과 같은 16:9 비율로 만들어,
    매핑 전/후로 박스 크기가 크게 달라지지 않게 합니다. 결과가 항상 같으므로
    캐시해서 매 렌더마다 새로 생성하지 않습니다."""
    return Image.new("RGB", (960, 540), color=(230, 232, 235))


def render_camera_card(cam: dict, video_slots: dict) -> None:
    """카메라 1대에 대한 카드를 렌더링합니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True, key=f"card_{cid}"):
        is_grid = ss.get("selected_cam") == "전체 구역"
        image_slot = _render_image_area(cam, is_grid, video_slots)

        # 확대/이동 기능은 집중 보기에서만 활성화 (그리드 칸에서 실수로 휠/드래그가 걸리는 것 방지)
        if not is_grid:
            inject_live_zoom_script(cid)

        # 아래에서 영상 프레임만 별도 fragment로 갱신 — 오버레이 바(위쪽)는 재생 중에도
        # 다시 그려지지 않아 깜빡임이 없음
        _render_playback_state(cam, image_slot)


def _render_channel_toggle(cam: dict) -> None:
    """EO(가시광)/TIR(열화상) 영상 전환 탭. 설정 페이지에서 매핑해둔 채널만
    누를 수 있고, 누르면 그 채널의 영상으로 즉시 재생을 다시 시작합니다."""
    ss = st.session_state
    cid = cam["id"]
    active = ss.get(f"active_channel_{cid}", "eo")

    eo_video = outposts_service.get_marker_video(cid, "eo")
    tir_video = outposts_service.get_marker_video(cid, "tir")

    with st.container(key=f"channel_toggle_{cid}", horizontal=True):
        if st.button(
            "EO", key=f"chan_eo_{cid}",
            type="primary" if active == "eo" else "secondary",
            disabled=eo_video is None, help="EO(가시광) 영상으로 전환",
        ):
            _switch_channel(cam, "eo", eo_video)

        if st.button(
            "TIR", key=f"chan_tir_{cid}",
            type="primary" if active == "tir" else "secondary",
            disabled=tir_video is None, help="TIR(열화상) 영상으로 전환",
        ):
            _switch_channel(cam, "tir", tir_video)


def _switch_channel(cam: dict, channel: str, video: tuple[bytes, str] | None) -> None:
    """카드의 재생 채널을 EO/TIR 중 하나로 전환합니다. 이미 그 채널이면 아무것도
    하지 않고, 매핑된 영상이 있으면 그 영상으로 재생을 다시 시작하고, 없으면
    (이론상 버튼이 disabled라 발생하지 않지만) 재생 상태만 정리합니다."""
    ss = st.session_state
    cid = cam["id"]
    if ss.get(f"active_channel_{cid}", "eo") == channel:
        return
    ss[f"active_channel_{cid}"] = channel
    if video:
        start_camera_media(cam, video[0], video[1])
    else:
        reset_cam_state(cid)
    st.rerun()


def _render_image_area(cam: dict, is_grid: bool, video_slots: dict):
    """영상/이미지 표시 영역과 그 위에 겹쳐지는 상단 오버레이 바(이름/EO·TIR
    전환/확대(⛶)·초기화(↺))를 그리고, 프레임을 표시할 st.empty() 슬롯을 반환합니다."""
    ss = st.session_state
    cid = cam["id"]

    # 이 자리는 fragment "바깥"에서 한 번만 만들어지고, 안쪽 fragment는 이 자리에
    # 이미지만 갈아끼웁니다 (오버레이 바와 무관하게 독립적으로 갱신됨).
    st.markdown(IMG_WRAP_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
    st.markdown(TOPBAR_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
    with st.container(key=f"img_wrap_{cid}"):
        image_slot = st.empty()

        # 데모 모드가 아니고, 영상이 재생 중이면 백엔드 MJPEG 스트림으로 화면을 채웁니다.
        # 이 경우 run_playback_loop가 이 슬롯에 직접 프레임을 쓰지 않도록
        # video_slots에 등록하지 않습니다 (탐지/로그/알람은 그쪽에서 계속 별도로 처리됨).
        tmp_path = ss.get(f"tmp_path_{cid}")
        use_stream = (not ss.get("simulate", True)) and HAS_CV2 and tmp_path and ss.get(f"playing_{cid}")
        if use_stream:
            fps = ss.get(f"fps_{cid}", 30.0)
            stream_url = f"{API_BASE_URL}/stream?path={quote(tmp_path)}&fps={fps}"
            image_slot.markdown(
                f'<img src="{stream_url}" style="width:100%; border-radius:4px; display:block;">',
                unsafe_allow_html=True,
            )
        else:
            video_slots[cid] = image_slot

        # 상단 오버레이 바 — [카메라 이름] [EO/TIR 전환] [⛶ 크게 보기 / ↺ 확대 초기화]
        # 배치(좌/중앙/우)는 위 TOPBAR_CSS_TEMPLATE의 CSS grid가 전담합니다.
        with st.container(key=f"topbar_{cid}"):
            if is_grid:
                if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                    ss["_pending_selected_cam"] = cam["name"]
                    st.rerun()
            else:
                st.markdown(f"**{cam['name']}**")

            _render_channel_toggle(cam)

            # 우측 슬롯 — 그리드 모드: [⛶ 크게 보기]만.
            # 집중 보기(스포트라이트) 모드: [▦ 전체 그리드로 돌아가기] [↺ 확대 초기화]
            # (예전 사이드바의 "구역 선택 → 전체 구역" 기능이 이 ▦ 버튼 하나로 대체되었습니다.)
            with st.container(key=f"view_toggle_{cid}", horizontal=True):
                if is_grid:
                    if st.button("⛶", key=f"expand_btn_{cid}", help="이 카메라 크게 보기"):
                        ss["_pending_selected_cam"] = cam["name"]
                        st.rerun()
                else:
                    if st.button("▦", key=f"grid_btn_{cid}", help="전체 그리드로 돌아가기"):
                        ss["selected_cam"] = "전체 구역"
                        st.rerun()
                    if st.button("↺", key=f"reset_zoom_{cid}", help="확대 초기화"):
                        st.markdown(
                            f"<script>window.parent.document.querySelectorAll("
                            f"'div[class*=\"st-key-img_wrap_{cid}\"] img').forEach("
                            f"el => el.style.transform = 'none');</script>",
                            unsafe_allow_html=True,
                        )

    return image_slot


def _render_playback_state(cam: dict, image_slot) -> None:
    """매핑 전 / 재생 중 / 정지(또는 완료) 세 가지 상태에 맞는 화면을 그립니다."""
    ss = st.session_state
    cid = cam["id"]

    if ss.get(f"fp_{cid}") is None:
        # 아직 이 초소에 매핑된 영상이 없는 상태 — 실제 영상과 같은 16:9 비율의
        # 빈 화면으로 자리를 잡아둬서 오버레이 바 위치가 흔들리지 않게 합니다.
        image_slot.image(_blank_placeholder(), use_container_width=True)

    elif ss.get(f"playing_{cid}"):
        # TODO(임시/테스트용): 반복 재생 중 로그가 계속 쌓이는 것을 막기 위한 일시정지 버튼.
        # 실제 데모/배포 시에는 24시간 끊김없이 도는 것이 맞으므로 제거를 검토할 것.
        if st.button("⏸️ 일시정지 (테스트용)", key=f"pause_btn_{cid}", use_container_width=True):
            ss[f"playing_{cid}"] = False
            st.rerun()
        # 실제 프레임 갱신 자체는 run_playback_loop()가 전담
    else:
        result = ss.get(f"result_{cid}")
        if result:
            image_slot.image(result, use_container_width=True)

        # TODO(임시/테스트용): 위 일시정지 버튼과 짝을 이루는 재개 버튼.
        cap = ss.get(f"cap_{cid}")
        if not ss.get(f"finished_{cid}") and cap is not None and cap.isOpened():
            if st.button("▶️ 재개 (테스트용)", key=f"resume_btn_{cid}", use_container_width=True):
                ss[f"playing_{cid}"] = True
                ss.pop(f"play_start_wall_{cid}", None)  # 재개 시점 기준으로 타이머 재설정
                st.rerun()

        if ss.get(f"finished_{cid}"):
            st.caption("영상 재생에 실패했습니다 — '설정' 페이지에서 영상을 다시 매핑해주세요.")
