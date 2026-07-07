"""
ui/camera/card.py — 카메라 카드(업로드+영상 슬롯+확대) 렌더링

그리드/집중 보기가 공유하는 카드 UI 본체입니다. 확대/이동 기능은
ui/camera/zoom.py에, 탐지 로직은 services/tracking.py·playback.py에 위임하고
이 파일은 카드 레이아웃과 상태 전환(대기 → 재생 중 → 정지/완료)만 담당합니다.
"""

import tempfile
import streamlit as st
from PIL import Image
from urllib.parse import quote

from config import IMAGE_EXTS, VIDEO_EXTS
from config import API_BASE_URL
from services.playback import reset_cam_state, HAS_CV2
from services.tracking import process_frame
from services.detection import draw_boxes
from ui.camera.zoom import ZOOM_OVERLAY_CSS_TEMPLATE, inject_live_zoom_script

try:
    import cv2
except ImportError:
    cv2 = None

@st.cache_data
def _blank_placeholder() -> Image.Image:
    """업로드 전 카드에 표시할 빈 화면 — 실제 영상과 같은 16:9 비율로 만들어,
    업로드 전/후로 박스 크기가 크게 달라지지 않게 합니다. 결과가 항상 같으므로
    캐시해서 매 렌더마다 새로 생성하지 않습니다."""
    return Image.new("RGB", (960, 540), color=(230, 232, 235))

def render_camera_card(cam: dict, video_slots: dict) -> None:
    """카메라 1대에 대한 카드를 렌더링합니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True, key=f"card_{cid}"):
        # 제목 줄 — 그리드에서는 클릭 가능한 버튼(집중 보기로 전환), 집중 보기에서는 일반 텍스트
        with st.container(horizontal=True, horizontal_alignment="distribute"):
            if ss.get("selected_cam") == "전체 구역":
                if st.button(f"**{cam['name']}**", key=f"title_btn_{cid}", type="tertiary"):
                    ss["_pending_selected_cam"] = cam["name"]
                    st.rerun()
            else:
                st.markdown(f"**{cam['name']}**")

            with st.popover("⚙️"):  # 업로드/초기화는 팝오버 안에 숨겨 카드를 깔끔하게 유지
                uploaded = st.file_uploader(
                    "미디어 업로드", type=list(IMAGE_EXTS + VIDEO_EXTS), key=f"upload_{cid}"
                )

        if uploaded is not None:
            _handle_upload(cam, uploaded)

        is_grid = ss.get("selected_cam") == "전체 구역"
        image_slot = _render_image_area(cam, is_grid, video_slots)

        # 확대/이동 기능은 집중 보기에서만 활성화 (그리드 칸에서 실수로 휠/드래그가 걸리는 것 방지)
        if not is_grid:
            inject_live_zoom_script(cid)

        # 아래에서 영상 프레임만 별도 fragment로 갱신 — 테두리/버튼(위쪽)은 재생 중에도 다시 그려지지 않아 깜빡임이 없음
        _render_playback_state(cam, image_slot)


def _handle_upload(cam: dict, uploaded) -> None:
    """새로 업로드된 파일을 처리합니다 — 영상이면 재생을 시작하고,
    이미지면 즉시 1회 분석 후 결과를 저장해둡니다."""
    ss = st.session_state
    cid = cam["id"]

    # 파일명+크기 조합으로 "새로 업로드된 파일인지"를 판별 — 동일 파일이면 재처리하지 않음
    fp = (uploaded.name, uploaded.size)
    if ss.get(f"fp_{cid}") == fp:
        return

    reset_cam_state(cid)
    ss[f"fp_{cid}"] = fp
    ext = uploaded.name.rsplit(".", 1)[-1].lower()

    if ext in VIDEO_EXTS:
        if not HAS_CV2:
            st.error("opencv-python 필요")
            return
        # cv2.VideoCapture는 파일 경로가 필요하므로, 업로드된 바이트를
        # 임시파일로 먼저 저장한 뒤 그 경로를 열어 재생을 시작합니다.
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            ss[f"tmp_path_{cid}"] = tmp.name

        cap = cv2.VideoCapture(ss[f"tmp_path_{cid}"])
        ss[f"cap_{cid}"] = cap
        ss[f"total_frames_{cid}"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # 영상 자체의 FPS를 읽어서 재생 속도를 실제 영상 속도에 맞춥니다.
        # 일부 영상은 FPS 값을 못 읽어오는 경우가 있어 0 이하면 30fps로 대체합니다.
        fps = cap.get(cv2.CAP_PROP_FPS)
        ss[f"fps_{cid}"] = fps if fps and fps > 0 else 30.0
        ss[f"cursor_{cid}"] = 0
        ss[f"playing_{cid}"] = True
        ss[f"finished_{cid}"] = False
        st.rerun()  # 재생 상태를 즉시 반영 → 이후 카드가 스스로 재생을 이어받음
    else:
        image = Image.open(uploaded).convert("RGB")
        dets, _, _ = process_frame(cam, image, "이미지", single=True)
        ss[f"result_{cid}"] = draw_boxes(image, dets)
        st.rerun()


def _render_image_area(cam: dict, is_grid: bool, video_slots: dict):
    """영상/이미지 표시 영역과 그 위에 겹쳐지는 확대(⛶)/초기화(↺) 아이콘을
    그리고, 프레임을 표시할 st.empty() 슬롯을 반환합니다."""
    ss = st.session_state
    cid = cam["id"]

    # 이 자리는 fragment "바깥"에서 한 번만 만들어지고, 안쪽 fragment는 이 자리에
    # 이미지만 갈아끼웁니다 (테두리/버튼과 무관하게 독립적으로 갱신됨).
    st.markdown(ZOOM_OVERLAY_CSS_TEMPLATE.format(cid=cid), unsafe_allow_html=True)
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

        if is_grid:
            # 그리드 모드면 재생/일시정지 상태와 무관하게 항상 "크게 보기" 아이콘 노출
            with st.container(key=f"expand_overlay_{cid}"):
                if st.button("⛶", key=f"expand_btn_{cid}", help="이 카메라 크게 보기"):
                    ss["_pending_selected_cam"] = cam["name"]
                    st.rerun()
        elif not is_grid:
            # 집중 보기(크게 본 상태)일 때만 확대 초기화 아이콘 노출
            with st.container(key=f"reset_overlay_{cid}"):
                if st.button("↺", key=f"reset_zoom_{cid}", help="확대 초기화"):
                    st.markdown(
                        f"<script>window.parent.document.querySelectorAll("
                        f"'div[class*=\"st-key-img_wrap_{cid}\"] img').forEach("
                        f"el => el.style.transform = 'none');</script>",
                        unsafe_allow_html=True,
                    )

    return image_slot


def _render_playback_state(cam: dict, image_slot) -> None:
    """업로드 전 / 재생 중 / 정지(또는 완료) 세 가지 상태에 맞는 화면을 그립니다."""
    ss = st.session_state
    cid = cam["id"]

    if ss.get(f"fp_{cid}") is None:
        # 업로드 전 — 실제 영상과 같은 16:9 비율의 빈 화면으로 자리를 잡아둬서
        # "⛶" 오버레이 아이콘 위치가 업로드 전후로 흔들리지 않게 합니다.
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
            st.caption("영상 재생에 실패했습니다 — 다시 업로드해주세요.")
