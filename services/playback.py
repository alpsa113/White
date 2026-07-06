"""
services/playback.py — 영상 재생 제어 (업로드 상태 정리, 다중 카메라 재생 루프)

reset_cam_state(): 카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
run_playback_loop(): 여러 카메라의 영상을 하나의 반복문 안에서 함께 재생합니다.
                    YIELD_INTERVAL마다 한 번씩 스스로 짧게 리런하여, 그 사이
                    쌓인 버튼 클릭(팝업 닫기, 페이지 이동 등)이 씹히지 않고
                    처리되도록 합니다.
"""
import os
import time

import streamlit as st
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config import DETECT_EVERY_SECONDS
from services.detection import draw_boxes
from services.tracking import process_frame

# ------------------------------------------------------------------ #
# 카메라 상태 정리
# ------------------------------------------------------------------ #
def reset_cam_state(cid: str):
    """카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
    새 영상 업로드, '비우기' 클릭, 그리드 축소로 슬롯이 사라질 때 호출됩니다."""
    if f"cap_{cid}" in st.session_state:
        cap = st.session_state[f"cap_{cid}"]
        if cap is not None:
            cap.release()

    if f"tmp_path_{cid}" in st.session_state:
        try:
            os.remove(st.session_state[f"tmp_path_{cid}"])
        except Exception:
            pass

    for k in ("cap", "tmp_path", "cursor", "total_frames", "playing", "finished",
              "result", "person_tracks", "animal_tracks", "animals_visible", "last_dets", "last_toasts", "fp",
              "fps", "play_start_wall", "play_start_frame", "last_detect_time", "progress"):
        st.session_state.pop(f"{k}_{cid}", None)


# ------------------------------------------------------------------ #
# 다중 카메라 재생 루프
# ------------------------------------------------------------------ #
def run_playback_loop(active_cams: list[dict], video_slots: dict, progress_slots: dict) -> None:
    """활성화된(재생 중인) 여러 카메라 피드를 하나의 반복문 안에서 함께 재생합니다."""
    ss = st.session_state
    need_ui_refresh = False

    for cam in active_cams:
        cid = cam["id"]
        if ss.get(f"play_start_wall_{cid}") is None:
            ss[f"play_start_wall_{cid}"] = time.time()
            ss[f"play_start_frame_{cid}"] = ss.get(f"cursor_{cid}", 0)

    while True:
        frames_processed = 0

        for cam in active_cams:
            cid = cam["id"]
            if not ss.get(f"playing_{cid}"):
                continue

            cap = ss.get(f"cap_{cid}")
            if cap is None or not cap.isOpened():
                ss[f"playing_{cid}"] = False
                continue

            fps = ss.get(f"fps_{cid}", 30.0)
            total_frames = ss.get(f"total_frames_{cid}", 0)

            now = time.time()
            start_wall = ss[f"play_start_wall_{cid}"]
            start_frame = ss[f"play_start_frame_{cid}"]
            target_frame = start_frame + int((now - start_wall) * fps)

            def _restart_loop(cid=cid, cap=cap):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ss[f"cursor_{cid}"] = 0
                ss[f"play_start_wall_{cid}"] = time.time()
                ss[f"play_start_frame_{cid}"] = 0
                ss.pop(f"person_tracks_{cid}", None)
                ss.pop(f"animal_tracks_{cid}", None)
                ss.pop(f"last_dets_{cid}", None)

            if total_frames and target_frame >= total_frames:
                _restart_loop()
                target_frame = 0

            cursor = ss.get(f"cursor_{cid}", 0)
            frames_to_advance = min(max(1, target_frame - cursor), 30)

            frame = None
            for _ in range(frames_to_advance):
                ret, frame = cap.read()
                cursor += 1
                if not ret:
                    _restart_loop()
                    cursor = 0
                    ret, frame = cap.read()
                    if ret:
                        cursor = 1
                    break

            if frame is None:
                ss[f"playing_{cid}"] = False
                ss[f"finished_{cid}"] = True
                continue

            frames_processed += 1
            ss[f"cursor_{cid}"] = cursor
            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            last_detect = ss.get(f"last_detect_time_{cid}", 0)
            if now - last_detect >= DETECT_EVERY_SECONDS:
                ss[f"last_detect_time_{cid}"] = now
                dets, is_new_alert = process_frame(cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                ss[f"last_dets_{cid}"] = dets
                if is_new_alert:
                    need_ui_refresh = True
            else:
                dets = ss.get(f"last_dets_{cid}", [])

            annotated = draw_boxes(pil_img, dets)
            ss[f"result_{cid}"] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            time.sleep(0.005)

        if need_ui_refresh:
            st.rerun()

        if frames_processed == 0:
            break
    st.rerun()