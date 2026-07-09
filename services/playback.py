"""
services/playback.py — 영상 재생 제어 (업로드 상태 정리, 다중 카메라 재생 루프)

reset_cam_state(): 카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
run_playback_loop(): 여러 카메라의 영상을 하나의 반복문 안에서 함께 재생하며,
                    프레임마다 탐지(services/tracking.py)와 클립 녹화
                    (services/clip_recorder.py)를 호출합니다. 실제 인코딩·
                    업로드 로직은 clip_recorder.py에 위임되어 있습니다.
"""
import io
import os
import tempfile
import time

import streamlit as st
from PIL import Image
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config import DETECT_EVERY_SECONDS, IMAGE_EXTS, VIDEO_EXTS
from services.detection import draw_boxes
from services.tracking import process_frame
from services.clip_recorder import push_frame_buffer, start_pending_clips, append_pending_clips


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
              "fps", "play_start_wall", "play_start_frame", "last_detect_time", "progress",
              "frame_buffer", "pending_clips"):
        st.session_state.pop(f"{k}_{cid}", None)


# ------------------------------------------------------------------ #
# 미디어 반영 (설정 페이지의 사전 업로드 + 카메라 최초 로딩 시 자동 반영 공용)
# ------------------------------------------------------------------ #
def start_camera_media(cam: dict, data: bytes, filename: str) -> str:
    """카메라 채널(cam)에 미디어 바이트(data)를 반영합니다 — 영상이면 재생을
    시작하고, 이미지면 1회 분석 결과를 저장합니다.

    설정 페이지에서 초소에 영상을 매핑할 때(services/outposts.set_marker_video)와,
    대시보드 진입 시 그 매핑을 카메라에 자동으로 반영할 때(services/camera_registry.
    get_active_cameras) 양쪽에서 공용으로 사용됩니다 — 기존 ui/camera/card.py의
    자체 업로드 버튼이 하던 일을 대체합니다.

    이 함수는 st.rerun()을 직접 호출하지 않습니다 — 호출부가 언제 다시 그릴지를
    결정합니다(예: 설정 페이지 저장 버튼은 저장 후 한 번만, 카메라 목록 계산 시
    자동 반영은 같은 스크립트 실행 안에서 바로 이어서 그려지므로 별도 rerun 불필요).

    반환값: "video" | "image" | "unchanged" | "unsupported" | "no_cv2"
    """
    ss = st.session_state
    cid = cam["id"]

    # 파일명+크기 조합으로 "이미 반영된 미디어인지"를 판별 — 동일하면 재처리하지 않음
    fp = (filename, len(data))
    if ss.get(f"fp_{cid}") == fp:
        return "unchanged"

    reset_cam_state(cid)
    ss[f"fp_{cid}"] = fp
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in VIDEO_EXTS:
        if not HAS_CV2:
            return "no_cv2"
        # cv2.VideoCapture는 파일 경로가 필요하므로, 바이트를 임시파일로 먼저
        # 저장한 뒤 그 경로를 열어 재생을 시작합니다.
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
            tmp.write(data)
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
        return "video"

    elif ext in IMAGE_EXTS:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        dets, _, _ = process_frame(cam, image, "이미지", single=True)
        ss[f"result_{cid}"] = draw_boxes(image, dets)
        return "image"

    else:
        return "unsupported"


# ------------------------------------------------------------------ #
# 다중 카메라 재생 루프
# ------------------------------------------------------------------ #
def run_playback_loop(active_cams: list[dict], video_slots: dict) -> None:
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

            cursor = ss.get(f"cursor_{cid}", 0)
            # 오랫동안 이 함수가 호출되지 않았던 경우(다른 페이지에 머무름 등),
            # 밀린 프레임 수가 아주 커질 수 있습니다. 이걸 한 프레임씩 순차
            # 재생(cap.read())으로 다 따라잡으려면 너무 오래 걸려 그동안 화면이
            # 빈 채로 남아있게 되므로, 이런 경우는 코덱 재탐색(seek)으로 즉시
            # 그 지점까지 점프합니다.
            LARGE_GAP_THRESHOLD = 60  # 이보다 많이 밀려 있으면 순차 재생 대신 즉시 점프
            if target_frame - cursor > LARGE_GAP_THRESHOLD:
                if total_frames and target_frame >= total_frames:
                    target_frame = target_frame % total_frames if total_frames else 0
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                cursor = target_frame
                ss[f"cursor_{cid}"] = cursor

            def _restart_loop(cid=cid, cap=cap):
                """영상 처음으로 되돌아가 반복 재생을 이어갑니다 (24시간
                끊김없이 도는 실제 CCTV를 업로드 영상 1개로 시뮬레이션)."""
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

            # 화면 렌더링 성능을 위해 가로 해상도를 1080px로 제한 (원본 비율 유지)
            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # DETECT_EVERY_SECONDS 주기마다 한 번만 실제 추론, 나머지는 직전 박스를 재사용
            last_detect = ss.get(f"last_detect_time_{cid}", 0)
            if now - last_detect >= DETECT_EVERY_SECONDS:
                ss[f"last_detect_time_{cid}"] = now
                dets, is_new_alert, new_alert_ids = process_frame(cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                ss[f"last_dets_{cid}"] = dets
                if is_new_alert:
                    need_ui_refresh = True
                    # 사람이 새로 탐지되면 그 카메라로 자동 전환
                    # 위젯이 그려지기 전에 반영되도록 예약 방식(_pending_selected_cam)을 재사용
                    ss["_pending_selected_cam"] = cam["name"]
            else:
                dets = ss.get(f"last_dets_{cid}", [])
                new_alert_ids = []

            annotated = draw_boxes(pil_img, dets)

            # 클립/버퍼에는 바운딩 박스가 그려진 화면(annotated)을 저장해야 합니다 —
            # 박스를 그리기 전의 원본 프레임을 저장하면 클립 재생 시 박스가 보이지 않습니다.
            annotated_np = np.array(annotated)  # PIL(RGB) → numpy 배열 (imageio도 RGB를 기대함)
            push_frame_buffer(cid, annotated_np, now)             # 최근 N초 순환 버퍼에 추가
            start_pending_clips(cam, new_alert_ids, fps, now)     # 새 탐지가 있으면 클립 녹화 시작
            append_pending_clips(cid, annotated_np, now)          # 대기 중인 클립에 이번 프레임 추가

            ss[f"result_{cid}"] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            time.sleep(0.005)

        # 백그라운드에서 완성된 클립이 있으면(플래그 변화 감지) 다음 반복에서 화면을 갱신
        if ss.get("_clip_ready_flag", 0) != ss.get("_clip_seen_flag", 0):
            ss["_clip_seen_flag"] = ss.get("_clip_ready_flag", 0)
            need_ui_refresh = True

        if need_ui_refresh:
            st.rerun()

        if frames_processed == 0:
            break
    st.rerun()
