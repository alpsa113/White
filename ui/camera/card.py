"""
ui/camera/card.py — 카메라 카드(영상 슬롯+오버레이+확대) 렌더링

그리드/집중 보기가 공유하는 카드 UI 본체입니다. 확대/이동 기능은
ui/camera/zoom.py에, 탐지 로직은 services/tracking.py·playback.py에 위임하고
이 파일은 카드 레이아웃과 상태 전환(대기 → 재생 중 → 정지/완료)만 담당합니다.

영상 업로드는 이 카드에 있지 않습니다 — '설정' 페이지(ui/outposts/editor.py)에서
초소별로 EO/TIR CCTV 영상을 미리 매핑해두면, services/camera_registry.py가
대시보드 진입 시 카메라당 "배경 채널"(기본 EO) 하나만 자동으로 재생을
시작합니다(services/playback.start_camera_media, services/camera_registry.
_sync_preset_media) — EO/TIR을 항상 둘 다 동시에 재생하면 카메라가 몇 대만
있어도 디코딩 부담이 2배가 되어 메모리 부족 크래시로 이어졌기 때문입니다
(services/playback.py 모듈 docstring 참고).

[EO/TIR 버튼 = 필요할 때만 재생 시작/중지] 카드 상단 툴바의 EO/TIR 버튼
(§_render_channel_toggle, _toggle_channel)은 다음을 담당합니다:
  - 그리드 모드: 배타적 단일 선택 — 다른 채널을 누르면 "배경 채널"이
    바뀝니다. 기존 채널은 재생을 멈추고 리소스를 반납하며, 새 채널이
    처음부터 재생을 시작합니다.
  - 스포트라이트(집중 보기): 두 버튼을 독립적으로 켤 수 있어, 두 번째
    채널을 켜면 그 채널의 재생을 새로 시작해 2분할로 EO/TIR이 동시에
    재생됩니다. 끄면 그 채널의 재생도 함께 멈추고 리소스를 반납합니다
    (배경 채널은 계속 재생됩니다).
화면에 표시되지 않는 채널은 재생/탐지/클립 녹화가 되지 않습니다 — 배경
채널 하나만 페이지와 무관하게 항상 계속됩니다.

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
# 카드 상단 툴바 — [카메라 이름] .......... [EO][TIR][▦/⛶][↺] 2분할 배치
#
# 예전에는 이 바가 영상 위에 position:absolute로 겹쳐 그려졌지만, 영상
# 내용과 겹쳐 보기 어렵다는 피드백에 따라 지금은 영상 "위쪽" 카드 안의
# 별도 영역(일반 문서 흐름)으로 옮겨졌습니다 — 겹침 문제가 근본적으로
# 사라지므로 반투명 배경 등 대비용 스타일도 더는 필요 없지만, 카드 폭에
# 따라 배지 크기가 비례해서 커지고 작아지는 컨테이너 쿼리(cqw) 기반 반응형
# 레이아웃 자체는 계속 유용해 그대로 유지합니다(container-type: inline-size는
# 이제 CARD_CSS_TEMPLATE이 카드 컨테이너 자체에 선언합니다 — 이 바가 더는
# img_wrap 안에 있지 않기 때문입니다).
#
# 이름(좌측)과 나머지 컨트롤(EO/TIR/⛶·▦·↺, 우측)을 딱 2개 그룹으로만
# 나눕니다 — `justify-content: space-between`으로 이름은 왼쪽 끝, 컨트롤
# 그룹은 오른쪽 끝에 붙습니다. 컨트롤 그룹은 `flex: 0 0 auto`로 **절대
# 줄어들지 않고 항상 자기 내용물 크기 그대로** 렌더링되고, 이름 쪽만
# `flex: 1 1 0`(flex-basis:0 기준 축소/확장)으로 남는 공간만큼만 차지합니다.
#
# 이름 쪽 버튼/텍스트 엘리먼트는 `width:auto; max-width:100%;`로, 평소에는
# 텍스트 내용물 크기만큼만 차지해 왼쪽에 붙고(다른 버튼들처럼), 카드가 좁아져
# 부모 div(`flex:1 1 0; min-width:0`)가 줄어들면 그 폭을 넘지 못하고 넘치는
# 텍스트는 ellipsis로 잘리도록 했습니다. 실제로 브라우저(Playwright 헤드리스
# Chromium)에서 버튼들의 정확한 bounding box 좌표를 측정해 어떤 카드 폭
# (267px~909px)에서도 서로 겹치지 않는 것을 확인했습니다.
#
# (참고: 이전에 시도했던 방식들 — ① CSS Grid의 "1fr auto 1fr"은 가운데
# auto 트랙이 필요한 만큼 먼저 차지하고 남는 공간을 좌우 1fr 트랙에
# 나누는데, 이 계산이 카드가 좁을 때 좌우를 서로 다른 폭으로 만들어
# 오른쪽 그룹이 중앙 쪽으로 쏠려 보였습니다. ② 3그룹을 각각
# position:absolute로 독립 배치하는 방식은 더 예측 불가능하게 깨졌습니다.
# ③ 이름/EO·TIR/아이콘 3그룹을 "flex: 1 1 0"으로 균등분배했을 때는, 카드가
# 좁아지면 이름과 아이콘 그룹이 함께 짜부라지면서 아이콘 그룹이 통째로
# 거의 안 보이는 크기까지 줄어드는 문제가 있었습니다. 컨트롤 그룹을 축소
# 대상에서 아예 제외하고 이름 쪽만 희생시키는 지금의 2분할 구조가 가장
# 안전합니다.)
#
# 폰트/패딩은 고정 px가 아니라 **컨테이너 쿼리**(cqw = 이 카드 자신의 가로폭
# 기준 %)로 지정합니다 — 그리드 칸이 5~7개로 좁아지거나, 가로 스크롤 나머지
# 카메라 카드처럼 작아져도, 카드 폭에 비례해 배지 크기/글자가 함께 작아져서
# 서로 겹치거나 다음 카드로 번지지 않습니다. `container-type: inline-size`는
# ui/camera/zoom.py의 IMG_WRAP_CSS_TEMPLATE(topbar의 바로 위 부모)에
# 선언되어 있습니다. clamp()로 최소/최대 크기를 둬서 카드가 아주 작거나
# 아주 커도 글자가 지나치게 작아지거나 커지지 않게 막습니다.
#
# EO/TIR과 ⛶·▦·↺는 하나의 컨트롤 그룹(controls_{cid})으로 묶여 함께
# flex-wrap:nowrap을 적용받습니다 — 지정하지 않으면 카드가 좁을 때 버튼이
# 줄바꿈되며 이름 텍스트와 겹쳐 보이는 문제가 있었습니다.
#
# 배지(이름/EO·TIR/아이콘 버튼)는 색을 강제로 입힌 알약(pill) 모양 대신,
# Streamlit 기본 버튼 스타일 그대로 둡니다 — 더는 영상 위에 겹쳐지지 않아
# 밝은 배경으로 대비를 만들어줄 필요가 없어졌기 때문입니다(테마와도 자연스럽게
# 어울림). type="primary"/"secondary"/"tertiary" 구분만으로 현재 선택된
# 채널/버튼이 강조됩니다. 다만 padding/font-size는 그대로 clamp(cqw)로 둬서,
# 버튼 폭 자체는 이전과 동일하게 유지됩니다.
# ------------------------------------------------------------------ #
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
/* Streamlit이 st.container(horizontal=True)의 각 "레이아웃 래퍼"에도 width:100%를
   걸어두는 경우가 있어, 그 바로 안쪽 래퍼까지 한 겹 더 확실히 눌러줍니다. */
div[class*="st-key-controls_{cid}"] > div[data-testid="stLayoutWrapper"] {{
    width: auto !important;
    max-width: none !important;
    flex: 0 0 auto !important;
}}
</style>
"""

# 카드 바깥(테두리)과 실제 영상 사이 여백을 최소화 — Streamlit의 기본
# border=True 컨테이너 패딩(약 1rem)이 꽤 커서, 회색 영상 박스가 테두리
# 안에서 필요 이상으로 작아 보이는 문제가 있었습니다.
#
# container-type: inline-size — 상단 툴바(TOPBAR_CSS_TEMPLATE)가 쓰는 cqw
# 단위의 기준점을 카드 컨테이너 자체에 선언합니다. 툴바가 예전엔 img_wrap
# 안(영상 위 오버레이)에 있어 그쪽에 선언되어 있었지만, 이제 카드 안쪽
# 상단(영상 바깥)의 별도 영역으로 옮겨졌으므로 카드 자신의 폭 기준으로
# 바꿨습니다 — 그리드 칸 개수가 달라져 카드 폭이 바뀌어도 툴바 배지 크기가
# 함께 비례해서 커지고 작아집니다.
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
    """매핑 전 카드에 표시할 빈 화면 — 실제 영상과 같은 16:9 비율로 만들어,
    매핑 전/후로 박스 크기가 크게 달라지지 않게 합니다. 결과가 항상 같으므로
    캐시해서 매 렌더마다 새로 생성하지 않습니다."""
    return Image.new("RGB", (960, 540), color=(230, 232, 235))


def render_camera_card(cam: dict, eo_video_slots: dict, tir_video_slots: dict) -> None:
    """카메라 1대에 대한 카드를 렌더링합니다.

    eo_video_slots/tir_video_slots — 이 카드가 EO/TIR 중 무엇을 화면에
    표시하기로 했는지에 따라, 그 채널에 해당하는 딕셔너리에만 이 카드의
    st.empty() 슬롯을 등록합니다(§_render_image_area). app.py가 이 두
    딕셔너리를 이용해 EO/TIR 재생 루프를 각각 돌립니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True, key=f"card_{cid}"):
        st.markdown(CARD_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
        is_grid = ss.get("selected_cam") == "전체 구역"
        image_slot, primary_channel = _render_image_area(cam, is_grid, eo_video_slots, tir_video_slots)

        # 확대/이동 기능은 집중 보기에서만 활성화 (그리드 칸에서 실수로 휠/드래그가 걸리는 것 방지)
        if not is_grid:
            inject_live_zoom_script(cid)

        # 아래에서 영상 프레임만 별도 fragment로 갱신 — 오버레이 바(위쪽)는 재생 중에도
        # 다시 그려지지 않아 깜빡임이 없음
        _render_playback_state(cam, image_slot, primary_channel)


def _render_channel_toggle(cam: dict, is_grid: bool) -> None:
    """EO(가시광)/TIR(열화상) 전환 탭. 설정 페이지에서 매핑해둔 채널만 누를
    수 있습니다. 그리드 모드(is_grid=True)에서는 배타적 단일 선택 — 다른
    채널을 누르면 배경 채널이 바뀝니다(기존 채널 정지, 새 채널 재생 시작).
    스포트라이트(is_grid=False)에서는 두 버튼이 독립 토글이라 함께 켤 수
    있고, 함께 켜지면(2분할 동시 재생) 두 버튼 모두 강조(primary) 표시됩니다
    (§_toggle_channel).

    [중요] disabled 버튼에는 help(툴팁)를 넣지 않습니다 — Streamlit은
    disabled 버튼에 help가 있으면 마우스 오버 이벤트를 감지하기 위해
    버튼을 숨겨진 래퍼로 한 번 더 감싼 "이중 DOM" 구조를 만듭니다. 이
    구조가 컨트롤 그룹의 "내용물 기준 자연스러운 폭"을 실제보다 훨씬
    넓게 계산되게 만들어(그룹 자체는 flex-shrink:0이라 줄어들지 않으므로),
    옆에 있는 카메라 이름 칸이 밀려서 안 보일 정도로 줄어드는 문제가
    있었습니다. 영상이 아직 매핑되지 않아 버튼이 비활성화된 초기 상태에서
    특히 두드러집니다 — help를 빼면 이 이중 구조 자체가 생기지 않습니다."""
    ss = st.session_state
    cid = cam["id"]
    active = ss.get(f"active_channel_{cid}", "eo")
    secondary = None if is_grid else ss.get(f"active_channel_secondary_{cid}")

    eo_video = outposts_service.get_marker_video(cid, "eo")
    tir_video = outposts_service.get_marker_video(cid, "tir")

    eo_on = active == "eo" or secondary == "eo"
    tir_on = active == "tir" or secondary == "tir"

    with st.container(key=f"channel_toggle_{cid}", horizontal=True):
        if st.button(
            "EO", key=f"chan_eo_{cid}",
            type="primary" if eo_on else "secondary",
            disabled=eo_video is None,
            help="EO(가시광) 영상" if eo_video is not None else None,
        ):
            _toggle_channel(cam, "eo", eo_video, is_grid)

        if st.button(
            "TIR", key=f"chan_tir_{cid}",
            type="primary" if tir_on else "secondary",
            disabled=tir_video is None,
            help="TIR(열화상) 영상" if tir_video is not None else None,
        ):
            _toggle_channel(cam, "tir", tir_video, is_grid)


def _toggle_channel(cam: dict, channel: str, video: tuple[bytes, str] | None, is_grid: bool) -> None:
    """EO/TIR 버튼 클릭을 처리합니다.

    그리드 모드(is_grid=True)에서는 배타적 단일 선택입니다 — 다른 채널을
    누르면 그 카메라의 "배경 채널"이 바뀝니다: 기존 채널의 재생을 멈추고
    리소스를 반납한 뒤, 새 채널의 재생을 처음부터 시작합니다(§_switch_background).

    스포트라이트(is_grid=False)에서는 두 채널을 독립적으로 켜고 끌 수
    있습니다 — 켜져 있던(표시 중인) 채널을 다시 누르면 끄고(보조 채널이
    있었다면 그 채널을 배경으로 승격), 꺼져 있던 채널을 누르면 보조로 켜서
    그 채널의 재생을 새로 시작해 2분할 동시 재생을 시작합니다. 보조 채널을
    끄면 그 채널의 재생도 함께 멈춥니다(배경 채널은 계속 재생). 마지막
    남은 단일 채널은 끌 수 없습니다(항상 최소 1개는 재생되어야 함).

    두 채널을 항상 동시에 재생하지 않고 필요할 때만 켜고 끄는 이유는
    services/playback.py 모듈 docstring 참고 — 항상 둘 다 재생하면 카메라가
    몇 대만 있어도 메모리 부족 크래시로 이어졌습니다."""
    ss = st.session_state
    cid = cam["id"]

    if is_grid:
        _switch_background_channel(cam, channel, video)
        return

    active = ss.get(f"active_channel_{cid}", "eo")
    secondary = ss.get(f"active_channel_secondary_{cid}")

    if channel == active:
        if secondary is not None:
            # 배경 채널을 끄고, 보조로 켜져 있던 채널을 배경으로 승격
            # (그 채널은 이미 재생 중이므로 재생 상태를 건드릴 필요가 없음)
            ss[f"active_channel_{cid}"] = secondary
            ss.pop(f"active_channel_secondary_{cid}", None)
        # 보조가 없으면(현재 단일 재생 중인 마지막 채널) 끌 수 없으므로 아무 것도 하지 않음
        st.rerun()
        return

    if channel == secondary:
        # 보조로 켜져 있던 채널을 다시 누르면 재생을 멈추고 단일 표시로 복귀
        ss.pop(f"active_channel_secondary_{cid}", None)
        reset_cam_state(cid, state_suffix=f"_{channel}")
        st.rerun()
        return

    # 꺼져 있던 채널을 보조로 켜서 재생을 새로 시작하고 2분할 동시 재생을
    # 시작합니다. (채널이 EO/TIR 2개뿐이라 이미 배경+보조가 둘 다 차 있는
    # 경우는 여기 도달하지 않습니다.)
    ss[f"active_channel_secondary_{cid}"] = channel
    if video:
        start_camera_media(cam, video[0], video[1], state_suffix=f"_{channel}")
    st.rerun()


def _switch_background_channel(cam: dict, channel: str, video: tuple[bytes, str] | None) -> None:
    """그리드 모드에서 카드의 "배경 채널"(항상 재생되는 단일 채널)을
    전환합니다. 이미 그 채널이면 아무것도 하지 않습니다. 그렇지 않으면
    이전 채널의 재생을 멈추고, 매핑된 영상이 있으면 새 채널로 재생을 처음
    부터 시작합니다(없으면, 이론상 버튼이 disabled라 발생하지 않지만,
    재생 상태만 비웁니다)."""
    ss = st.session_state
    cid = cam["id"]
    old_channel = ss.get(f"active_channel_{cid}", "eo")
    if old_channel == channel:
        return
    ss[f"active_channel_{cid}"] = channel
    reset_cam_state(cid, state_suffix=f"_{old_channel}")
    if video:
        start_camera_media(cam, video[0], video[1], state_suffix=f"_{channel}")
    st.rerun()


def _render_image_area(cam: dict, is_grid: bool, eo_video_slots: dict, tir_video_slots: dict):
    """카드 안쪽 상단 툴바(이름/EO·TIR 표시 전환/확대(⛶)·초기화(↺))와 영상/이미지
    표시 영역을 순서대로 그리고, (주로 표시되는 채널의 st.empty() 슬롯, 그
    채널명)을 반환합니다.

    툴바가 영상보다 먼저(위쪽에) 그려지므로 더 이상 영상 위에 겹쳐지지
    않습니다 — 예전에는 영상 내용과 겹쳐 보이는 오버레이 방식이었습니다.

    스포트라이트에서 EO/TIR을 동시에 켠 경우(active_channel_secondary_{cid}가
    설정된 경우), 영상 영역을 2분할해 왼쪽에 배경 채널, 오른쪽에 보조 채널을
    나란히 표시합니다 — 이때는 두 채널 모두 실제로 재생·탐지 중입니다
    (_toggle_channel이 보조 채널 재생을 새로 시작해두었기 때문). 여기서는
    각 채널의 st.empty() 슬롯을 그 채널에 해당하는 딕셔너리(eo_video_slots
    또는 tir_video_slots)에 등록하기만 하면, app.py가 돌리는 EO/TIR 재생
    루프가 알아서 그 슬롯에 프레임을 그려 넣습니다."""
    ss = st.session_state
    cid = cam["id"]

    st.markdown(TOPBAR_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)

    # 카드 안쪽 상단 툴바 — [카메라 이름] .......... [EO/TIR 전환] [⛶ 크게 보기 / ↺ 확대 초기화]
    # 배치는 위 TOPBAR_CSS_TEMPLATE의 2분할(이름 좌측 / 컨트롤 그룹 우측)이 전담합니다.
    with st.container(key=f"topbar_{cid}"):
        if is_grid:
            if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                ss["_pending_selected_cam"] = cam["name"]
                st.rerun()
        else:
            st.markdown(f"**{cam['name']}**")

        # 컨트롤 그룹 — EO/TIR 전환 + 우측 아이콘을 하나의 flex 그룹으로 묶어
        # "flex-shrink:0"을 함께 적용받게 합니다(TOPBAR_CSS_TEMPLATE 참고) —
        # 카드가 아무리 좁아져도 이 그룹 전체는 절대 줄어들지 않고, 대신
        # 이름 쪽만 짧게 잘립니다.
        with st.container(key=f"controls_{cid}", horizontal=True):
            _render_channel_toggle(cam, is_grid)

            # 그리드 모드: [⛶ 크게 보기]만.
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
                        # 지도에서 선택해둔 마커가 남아있으면 그리드 필터 모드가 우선
                        # 적용되어(§views/dashboard.py) "전체" 그리드가 아니라 "선택된
                        # 카메라만" 보이는 필터링된 그리드로 돌아가게 됩니다 — 이 버튼은
                        # 이름 그대로 "전체" 그리드로 돌아가는 것이 목적이므로 함께 비웁니다.
                        ss["_map_selected_cam_ids"] = []
                        # 그리드로 돌아가면 스포트라이트 전용 2분할 재생도 함께 정리합니다
                        # (그리드 모드는 카드 1개당 항상 단일/배경 채널만 재생) — 보조
                        # 채널이 켜져 있었다면 재생을 멈추고 리소스를 반납합니다.
                        secondary = ss.pop(f"active_channel_secondary_{cid}", None)
                        if secondary:
                            reset_cam_state(cid, state_suffix=f"_{secondary}")
                        st.rerun()
                    if st.button("↺", key=f"reset_zoom_{cid}", help="확대 초기화"):
                        st.markdown(
                            f"<script>window.parent.document.querySelectorAll("
                            f"'div[class*=\"st-key-img_wrap_{cid}\"] img').forEach("
                            f"el => el.style.transform = 'none');</script>",
                            unsafe_allow_html=True,
                        )

    # 이 자리는 fragment "바깥"에서 한 번만 만들어지고, 안쪽 fragment는 이 자리에
    # 이미지만 갈아끼웁니다 (툴바와 무관하게 독립적으로 갱신됨).
    st.markdown(IMG_WRAP_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
    primary_channel = ss.get(f"active_channel_{cid}", "eo")
    secondary_channel = None if is_grid else ss.get(f"active_channel_secondary_{cid}")
    slots_by_channel = {"eo": eo_video_slots, "tir": tir_video_slots}

    with st.container(key=f"img_wrap_{cid}"):
        if secondary_channel:
            # 2분할 — 왼쪽 주 채널, 오른쪽 보조 채널. 둘 다 이미 백그라운드에서
            # 계속 재생·탐지 중이므로, 여기서는 각자의 최신 프레임(없으면 빈
            # 화면)으로 우선 채워두고, 슬롯을 해당 채널의 재생 루프에 등록만 합니다.
            primary_col, secondary_col = st.columns(2, gap="small")
            with primary_col:
                image_slot = st.empty()
                primary_result = ss.get(f"result_{cid}_{primary_channel}")
                image_slot.image(
                    primary_result if primary_result is not None else _blank_placeholder(),
                    use_container_width=True,
                )
            with secondary_col:
                sec_slot = st.empty()
                sec_result = ss.get(f"result_{cid}_{secondary_channel}")
                sec_slot.image(
                    sec_result if sec_result is not None else _blank_placeholder(),
                    use_container_width=True,
                )
            slots_by_channel[primary_channel][cid] = image_slot
            slots_by_channel[secondary_channel][cid] = sec_slot
        else:
            image_slot = st.empty()

            # 데모 모드가 아니고, 영상이 재생 중이면 백엔드 MJPEG 스트림으로 화면을 채웁니다.
            # 이 경우 재생 루프가 이 슬롯에 직접 프레임을 쓰지 않도록 슬롯 딕셔너리에
            # 등록하지 않습니다 (탐지/로그/알람은 그쪽에서 계속 별도로 처리됨).
            tmp_path = ss.get(f"tmp_path_{cid}_{primary_channel}")
            use_stream = (not ss.get("simulate", True)) and HAS_CV2 and tmp_path and ss.get(f"playing_{cid}_{primary_channel}")
            if use_stream:
                fps = ss.get(f"fps_{cid}_{primary_channel}", 30.0)
                stream_url = f"{API_BASE_URL}/stream?path={quote(tmp_path)}&fps={fps}"
                image_slot.markdown(
                    f'<img src="{stream_url}" style="width:100%; border-radius:4px; display:block;">',
                    unsafe_allow_html=True,
                )
            else:
                slots_by_channel[primary_channel][cid] = image_slot

    return image_slot, primary_channel


def _render_playback_state(cam: dict, image_slot, channel: str) -> None:
    """매핑 전 / 재생 중 / 정지(또는 완료) 세 가지 상태에 맞는 화면을 그립니다.
    channel은 이 image_slot이 표시하는 주 채널("eo"/"tir")입니다 — 상태
    키는 모두 f"{key}_{cid}_{channel}" 형태로 그 채널 전용입니다."""
    ss = st.session_state
    cid = cam["id"]
    suffix = f"_{channel}"

    if ss.get(f"fp_{cid}{suffix}") is None:
        # 아직 이 채널에 매핑된 영상이 없는 상태 — 실제 영상과 같은 16:9 비율의
        # 빈 화면으로 자리를 잡아둬서 오버레이 바 위치가 흔들리지 않게 합니다.
        image_slot.image(_blank_placeholder(), use_container_width=True)

    elif ss.get(f"playing_{cid}{suffix}"):
        # TODO(임시/테스트용): 반복 재생 중 로그가 계속 쌓이는 것을 막기 위한 일시정지 버튼.
        # 실제 데모/배포 시에는 24시간 끊김없이 도는 것이 맞으므로 제거를 검토할 것.
        if st.button("⏸️ 일시정지 (테스트용)", key=f"pause_btn_{cid}_{channel}", use_container_width=True):
            ss[f"playing_{cid}{suffix}"] = False
            st.rerun()
        # 실제 프레임 갱신 자체는 run_playback_loop()가 전담
    else:
        result = ss.get(f"result_{cid}{suffix}")
        if result:
            image_slot.image(result, use_container_width=True)

        # TODO(임시/테스트용): 위 일시정지 버튼과 짝을 이루는 재개 버튼.
        cap = ss.get(f"cap_{cid}{suffix}")
        if not ss.get(f"finished_{cid}{suffix}") and cap is not None and cap.isOpened():
            if st.button("▶️ 재개 (테스트용)", key=f"resume_btn_{cid}_{channel}", use_container_width=True):
                ss[f"playing_{cid}{suffix}"] = True
                ss.pop(f"play_start_wall_{cid}{suffix}", None)  # 재개 시점 기준으로 타이머 재설정
                st.rerun()

        if ss.get(f"finished_{cid}{suffix}"):
            st.caption("영상 재생에 실패했습니다 — '설정' 페이지에서 영상을 다시 매핑해주세요.")
