"""services/playback.py — 영상 재생 제어. 카메라 1대당 EO/TIR 중 현재 선택된 채널 하나만 디코딩합니다."""
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

from config import DETECT_EVERY_SECONDS, IMAGE_EXTS, VIDEO_EXTS, CLIP_STORAGE_MAX_WIDTH
from services.detection import draw_boxes
from services.tracking import process_frame
from services.clip_recorder import push_frame_buffer, start_pending_clips, append_pending_clips


def reset_cam_state(cid: str, state_suffix: str = "") -> None:
    """카메라 채널 하나(EO 또는 TIR)의 재생 상태와 리소스를 정리합니다."""
    key = lambda name: f"{name}_{cid}{state_suffix}"

    if key("cap") in st.session_state:
        cap = st.session_state[key("cap")]
        if cap is not None:
            cap.release()

    # tmp_path가 이 함수가 직접 만든 임시파일일 때만 삭제합니다(외부 소유 경로는 보존).
    if key("tmp_path") in st.session_state and st.session_state.get(key("tmp_path_owned"), True):
        try:
            os.remove(st.session_state[key("tmp_path")])
        except Exception:
            pass

    for k in ("cap", "tmp_path", "tmp_path_owned", "cursor", "total_frames", "playing", "finished",
              "result", "person_tracks", "animal_tracks", "animals_visible", "last_dets", "last_toasts", "fp",
              "fps", "play_start_wall", "play_start_frame", "last_detect_time", "progress",
              "frame_buffer", "pending_clips", "stream_start_frame"):
        st.session_state.pop(key(k), None)


def start_camera_media(cam: dict, data: bytes | None, filename: str, state_suffix: str = "",
                        src_path: str | None = None) -> str:
    """카메라 채널에 미디어를 반영합니다. 이미 같은 파일이면 "unchanged"를 반환해 재생 위치를 보존합니다.
    src_path가 있으면(예: 초소에 매핑된 영상) 그 파일을 그대로 열어 재사용하고, 세션 메모리에
    바이트를 따로 들고 있거나 디스크에 한 번 더 복사하지 않습니다.

    반환값: "video" | "image" | "unchanged" | "unsupported" | "no_cv2"
    """
    ss = st.session_state
    cid = cam["id"]
    key = lambda name: f"{name}_{cid}{state_suffix}"

    fp = (filename, src_path) if src_path else (filename, len(data or b""))
    if ss.get(key("fp")) == fp:
        return "unchanged"

    reset_cam_state(cid, state_suffix)
    ss[key("fp")] = fp
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in VIDEO_EXTS:
        if not HAS_CV2:
            return "no_cv2"
        if src_path:
            ss[key("tmp_path")] = src_path
            ss[key("tmp_path_owned")] = False
        else:
            with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
                tmp.write(data)
                ss[key("tmp_path")] = tmp.name
            ss[key("tmp_path_owned")] = True

        cap = cv2.VideoCapture(ss[key("tmp_path")])
        ss[key("cap")] = cap
        ss[key("total_frames")] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        ss[key("fps")] = fps if fps and fps > 0 else 30.0
        ss[key("cursor")] = 0
        ss[key("playing")] = True
        ss[key("finished")] = False
        return "video"

    elif ext in IMAGE_EXTS:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        dets, _, _ = process_frame(cam, image, "이미지", single=True)
        ss[key("result")] = draw_boxes(image, dets)
        return "image"

    else:
        return "unsupported"


def _downscale_for_clip(frame_rgb: np.ndarray) -> np.ndarray:
    """클립/버퍼 저장용 프레임을 CLIP_STORAGE_MAX_WIDTH 이하로 축소합니다."""
    height, width = frame_rgb.shape[:2]
    if width <= CLIP_STORAGE_MAX_WIDTH:
        return frame_rgb
    new_height = int(height * CLIP_STORAGE_MAX_WIDTH / width)
    return cv2.resize(frame_rgb, (CLIP_STORAGE_MAX_WIDTH, new_height))


def run_playback_loop(active_cams: list[dict], video_slots: dict) -> None:
    """여러 카메라(각각 현재 선택된 채널 1개씩)를 하나의 반복문에서 함께 재생합니다."""
    ss = st.session_state
    need_ui_refresh = False

    def _channel_suffix(cid: str) -> str:
        return f"_{ss.get(f'active_channel_{cid}', 'eo')}"

    for cam in active_cams:
        cid = cam["id"]
        suffix = _channel_suffix(cid)
        if ss.get(f"play_start_wall_{cid}{suffix}") is None:
            ss[f"play_start_wall_{cid}{suffix}"] = time.time()
            ss[f"play_start_frame_{cid}{suffix}"] = ss.get(f"cursor_{cid}{suffix}", 0)

    while True:
        frames_processed = 0

        for cam in active_cams:
            cid = cam["id"]
            suffix = _channel_suffix(cid)
            key = lambda name, cid=cid, suffix=suffix: f"{name}_{cid}{suffix}"
            channel_cid = f"{cid}{suffix}"

            if not ss.get(key("playing")):
                continue

            cap = ss.get(key("cap"))
            if cap is None or not cap.isOpened():
                ss[key("playing")] = False
                continue

            fps = ss.get(key("fps"), 30.0)
            total_frames = ss.get(key("total_frames"), 0)

            now = time.time()
            start_wall = ss[key("play_start_wall")]
            start_frame = ss[key("play_start_frame")]
            target_frame = start_frame + int((now - start_wall) * fps)

            cursor = ss.get(key("cursor"), 0)
            # 밀린 프레임이 많으면 순차 재생 대신 즉시 seek
            LARGE_GAP_THRESHOLD = 60
            if target_frame - cursor > LARGE_GAP_THRESHOLD:
                if total_frames and target_frame >= total_frames:
                    target_frame = target_frame % total_frames if total_frames else 0
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
                cursor = target_frame
                ss[key("cursor")] = cursor

            def _restart_loop(cap=cap, key=key, channel_cid=channel_cid):
                """영상 처음으로 되돌아가 반복 재생합니다."""
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ss[key("cursor")] = 0
                ss[key("play_start_wall")] = time.time()
                ss[key("play_start_frame")] = 0
                ss.pop(f"person_tracks_{channel_cid}", None)
                ss.pop(f"animal_tracks_{channel_cid}", None)
                ss.pop(f"last_dets_{channel_cid}", None)

            if total_frames and target_frame >= total_frames:
                _restart_loop()
                target_frame = 0

            frames_to_advance = min(target_frame - cursor, 30)
            if frames_to_advance <= 0:
                continue

            # 메모리 부족 시 cv2.read()가 예외를 던질 수 있어 카메라 단위로만 격리
            # 한 번에 여러 프레임을 따라잡을 때도(frames_to_advance > 1) 클립이 끊기지
            # 않도록, 건너뛰지 않고 batch_frames에 전부 모아 클립 버퍼에 반영합니다.
            batch_frames = []
            try:
                for _ in range(frames_to_advance):
                    ret, frame = cap.read()
                    cursor += 1
                    if not ret:
                        _restart_loop()
                        cursor = 0
                        ret, frame = cap.read()
                        if ret:
                            cursor = 1
                            batch_frames = [frame]
                        else:
                            batch_frames = []
                        break
                    batch_frames.append(frame)
            except (cv2.error, SystemError, MemoryError):
                batch_frames = []

            if not batch_frames:
                ss[key("playing")] = False
                ss[key("finished")] = True
                continue

            frames_processed += 1
            ss[key("cursor")] = cursor
            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

            # 배치의 모든 프레임에 동일한 리사이즈를 적용해야 클립 프레임 크기가 일정하게 유지됩니다
            # (마지막 프레임에만 적용하면 프레임마다 크기가 미세하게 달라져 인코딩이 실패합니다).
            src_height, src_width = batch_frames[0].shape[:2]
            if src_width > 1080:
                cap_height = int(src_height * 1080 / src_width)
                batch_frames = [cv2.resize(f, (1080, cap_height)) for f in batch_frames]

            last_frame = batch_frames[-1]
            rgb = cv2.cvtColor(last_frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # 탐지/트래킹/클립 상태를 채널별로 격리하기 위한 가상 카메라
            tracking_cam = {**cam, "id": channel_cid}

            last_detect = ss.get(f"last_detect_time_{channel_cid}", 0)
            if now - last_detect >= DETECT_EVERY_SECONDS:
                ss[f"last_detect_time_{channel_cid}"] = now
                dets, is_new_alert, new_alert_ids = process_frame(tracking_cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                ss[f"last_dets_{channel_cid}"] = dets
                if is_new_alert:
                    need_ui_refresh = True
                    ss["_pending_selected_cam"] = cam["name"]
            else:
                dets = ss.get(f"last_dets_{channel_cid}", [])
                new_alert_ids = []

            annotated = draw_boxes(pil_img, dets)

            start_pending_clips(tracking_cam, new_alert_ids, now)

            n = len(batch_frames)
            for i, raw in enumerate(batch_frames):
                frame_time = now - (n - 1 - i) / fps
                if i == n - 1:
                    frame_annotated = annotated
                else:
                    raw_rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
                    frame_annotated = draw_boxes(Image.fromarray(raw_rgb), dets)
                clip_frame = _downscale_for_clip(np.array(frame_annotated))
                push_frame_buffer(channel_cid, clip_frame, frame_time)
                append_pending_clips(channel_cid, clip_frame, frame_time)

            ss[key("result")] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            time.sleep(0.005)

        if ss.get("_clip_ready_flag", 0) != ss.get("_clip_seen_flag", 0):
            ss["_clip_seen_flag"] = ss.get("_clip_ready_flag", 0)
            need_ui_refresh = True

        # st.rerun()은 여기서 호출하지 않고 while만 빠져나옴 — 호출부(app.py)가 한 번만 rerun
        if need_ui_refresh or frames_processed == 0:
            break
