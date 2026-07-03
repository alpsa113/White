"""
ui/camera_card.py — 카메라 카드(업로드+영상 슬롯) 렌더링 및 사람 탐지 팝업

'전체 구역' 2×2 그리드와 '특정 카메라' 집중 보기가 원본에서 거의 동일한
카드 UI를 중복 작성하고 있었기 때문에, render_camera_card() 하나로 통합해
그리드/집중보기 양쪽에서 재사용하도록 했습니다.
"""
import tempfile

import streamlit as st
from PIL import Image

import s3_storage as s3
from config import CAMERAS, IMAGE_EXTS, VIDEO_EXTS
from services.video_tracking import reset_cam_state, process_frame, HAS_CV2
from services.detection import draw_boxes

try:
    import cv2
except ImportError:
    cv2 = None


def render_camera_card(cam: dict, video_slots: dict, progress_slots: dict) -> None:
    """카메라 1대에 대한 카드(제목 + 업로드 팝오버 + 영상 슬롯)를 렌더링합니다."""
    ss = st.session_state
    cid = cam["id"]

    with st.container(border=True):
        c1, c2 = st.columns([0.85, 0.15])
        with c1:
            st.markdown(f"**{cam['name']}**")
        with c2:
            with st.popover("⚙️"):
                uploaded = st.file_uploader(
                    "미디어 업로드", type=list(IMAGE_EXTS + VIDEO_EXTS), key=f"upload_{cid}"
                )
                if st.button("비우기 🗑️", key=f"clear_btn_{cid}", use_container_width=True):
                    reset_cam_state(cid)
                    st.rerun()

        video_slots[cid] = st.empty()
        progress_slots[cid] = st.empty()

        if uploaded is not None:
            fp = (uploaded.name, uploaded.size)
            if ss.get(f"fp_{cid}") != fp:
                reset_cam_state(cid)
                ss[f"fp_{cid}"] = fp
                ext = uploaded.name.rsplit(".", 1)[-1].lower()

                if ext in VIDEO_EXTS:
                    if not HAS_CV2:
                        st.error("opencv-python 필요")
                    else:
                        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
                            tmp.write(uploaded.getvalue())
                            ss[f"tmp_path_{cid}"] = tmp.name

                        cap = cv2.VideoCapture(ss[f"tmp_path_{cid}"])
                        ss[f"cap_{cid}"] = cap
                        ss[f"total_frames_{cid}"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        ss[f"cursor_{cid}"] = 0
                        ss[f"playing_{cid}"] = True
                        ss[f"finished_{cid}"] = False
                        st.rerun()
                else:
                    image = Image.open(uploaded).convert("RGB")
                    dets, _ = process_frame(cam, image, "이미지", single=True)
                    ss[f"result_{cid}"] = draw_boxes(image, dets)
                    st.rerun()

        if ss.get(f"fp_{cid}") is None:
            video_slots[cid].info("대기 중 — ⚙️ 아이콘을 눌러 업로드하세요")
        elif not ss.get(f"playing_{cid}"):
            result = ss.get(f"result_{cid}")
            if result:
                video_slots[cid].image(result, use_container_width=True)
            if ss.get(f"finished_{cid}"):
                st.caption("✅ 영상 분석 완료")


def render_camera_grid(video_slots: dict, progress_slots: dict) -> None:
    """'전체 구역' 선택 시 2×2 그리드로 모든 카메라 카드를 렌더링합니다."""
    for row_start in range(0, len(CAMERAS), 2):
        cols = st.columns(2)
        for col, cam in zip(cols, CAMERAS[row_start: row_start + 2]):
            with col:
                render_camera_card(cam, video_slots, progress_slots)


def render_camera_focus(cam_name: str, video_slots: dict, progress_slots: dict) -> None:
    """특정 카메라 선택 시 해당 채널만 전체 너비로 확대 표시합니다."""
    cam = next((c for c in CAMERAS if c["name"] == cam_name), None)
    if cam:
        render_camera_card(cam, video_slots, progress_slots)


@st.dialog("🚨 사람 탐지 상세", width="small")
def show_person_dialog(alert: dict) -> None:
    """특정 탐지 로그의 스냅샷 이미지와 상세 정보를 크게 띄워주는 다이얼로그(팝업)입니다."""
    ss = st.session_state
    snap = alert.get("snapshot")
    if snap is not None:
        # 이번 세션에서 탐지된 경우: 메모리 스냅샷 우선 사용
        st.image(snap, use_container_width=True)
    elif ss.get("S3_ENABLED") and alert.get("image_path"):
        # 재시작 후 복원된 로그: S3 객체 키로 임시 URL을 발급해 표시
        url = s3.get_presigned_url(alert["image_path"])
        if url:
            st.image(url, use_container_width=True)
        else:
            st.info("S3 이미지를 불러올 수 없습니다.")
    else:
        st.info("표시할 스냅샷이 없습니다.")
    extra = f" · 누적 {alert['hit_frames']}프레임 추적" if alert["source"] == "영상" else ""
    st.markdown(f"**{alert['camera']}** — {alert['class_name']} 신뢰도 {alert['confidence']:.0%}")
    st.caption(f"{alert['source']}{extra} · {alert['date']} {alert['time']}")
    if st.button("닫기", use_container_width=True):
        ss.popup_id = None
        st.rerun()
