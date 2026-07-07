"""
services/playback.py — 영상 재생 제어 (업로드 상태 정리, 다중 카메라 재생 루프)

reset_cam_state(): 카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
run_playback_loop(): 여러 카메라의 영상을 하나의 반복문 안에서 함께 재생하며,
                    새로운 탐지가 발생하면 그 전후 CLIP_PRE/POST_SECONDS 구간을
                    짧은 mp4 클립으로 녹화해 S3에 올리고 로그의 스냅샷을 교체합니다.
"""
import os
import tempfile
import time
from collections import deque

import streamlit as st
from PIL import Image
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

import imageio.v2 as imageio  # H.264 인코딩 전용 — cv2.VideoWriter는 브라우저 재생용 코덱을 못 만듦 (아래 _finalize_clip 참고)

import db_rds as db
import s3_storage as s3
from config import DETECT_EVERY_SECONDS, CLIP_PRE_SECONDS, CLIP_POST_SECONDS
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
              "fps", "play_start_wall", "play_start_frame", "last_detect_time", "progress",
              "frame_buffer", "pending_clips"):
        st.session_state.pop(f"{k}_{cid}", None)


# ------------------------------------------------------------------ #
# 탐지 전후 클립 녹화 — 최근 N초 프레임을 버퍼링해두었다가, 새 탐지가 발생하면
# "이전 구간"을 떼어내고 "이후 구간"을 마저 채워 짧은 mp4로 인코딩합니다.
# ------------------------------------------------------------------ #
def _push_frame_buffer(cid: str, frame_rgb, now: float) -> None:
    """최근 CLIP_PRE_SECONDS 분량의 프레임(바운딩 박스가 그려진 RGB 배열)만
    유지하는 순환 버퍼에 프레임을 추가합니다. 오래된 프레임은 자동으로 버려집니다."""
    ss = st.session_state
    buf = ss.setdefault(f"frame_buffer_{cid}", deque())
    buf.append((now, frame_rgb.copy()))
    cutoff = now - CLIP_PRE_SECONDS
    while buf and buf[0][0] < cutoff:
        buf.popleft()


def _start_pending_clips(cam: dict, new_alert_ids: list[int], fps: float, now: float) -> None:
    """새로 탐지된 로그마다, 지금까지 쌓인 '이전 N초' 프레임을 시작점으로 하는
    대기 클립을 등록합니다. 이후 프레임은 _append_pending_clips()가 계속 채우다가,
    CLIP_POST_SECONDS가 지나면 자동으로 인코딩·업로드됩니다."""
    if not new_alert_ids:
        return
    ss = st.session_state
    cid = cam["id"]
    buf = ss.get(f"frame_buffer_{cid}", deque())
    pre_frames = [f for _, f in buf]  # 지금까지의 '이전 N초' 프레임 복사

    pending = ss.setdefault(f"pending_clips_{cid}", [])
    for aid in new_alert_ids:
        pending.append({
            "aid": aid,
            "camera_name": cam["name"],
            "frames": list(pre_frames),
            "capture_until": now + CLIP_POST_SECONDS,
            "fps": fps,
        })


# services/playback.py

def _append_pending_clips(cid: str, frame_rgb, now: float) -> bool:
    """대기 중인 클립들에 현재 프레임(바운딩 박스가 그려진 RGB 배열)을 계속
    추가하고, 목표 시간(탐지 이후 CLIP_POST_SECONDS)에 도달한 클립은 mp4로
    인코딩해 S3에 업로드한 뒤 대기 목록에서 제거합니다.
    
    클립 저장이 완료되면 True를 반환합니다.
    """
    ss = st.session_state
    pending = ss.get(f"pending_clips_{cid}", [])
    if not pending:
        return False

    clip_finalized = False
    still_pending = []
    for pc in pending:
        pc["frames"].append(frame_rgb.copy())
        if now >= pc["capture_until"]:
            _finalize_clip(pc)
            clip_finalized = True  # 클립 최종 완료 표시
        else:
            still_pending.append(pc)
    ss[f"pending_clips_{cid}"] = still_pending
    
    return clip_finalized


def _finalize_clip(pc: dict) -> None:
    """모아둔 프레임을 mp4(H.264) 파일로 인코딩하고 S3에 업로드한 뒤, 해당 로그
    레코드의 스냅샷 경로를 이 클립으로 교체합니다.

    cv2.VideoWriter(fourcc='mp4v')는 이름과 달리 MPEG-4 Part 2라는 구형
    코덱으로 인코딩하는데, 이건 대부분의 브라우저 <video> 태그가 지원하지
    않아 "재생 시도하다가 조용히 멈추는" 증상이 납니다. imageio-ffmpeg는
    pip 설치만으로 실제 H.264(avc1) 인코딩이 가능해 웹에서 확실히 재생됩니다.

    이 함수는 재생 루프 안에서 동기적으로 실행되므로, 인코딩이 오래 걸리면
    그 순간 다른 카메라들의 재생도 함께 살짝 밀릴 수 있습니다."""
    frames = pc["frames"]
    if not frames:
        return

    fps = pc.get("fps") or 10.0

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        clip_path = tmp.name

    try:
        writer = imageio.get_writer(clip_path, fps=fps, codec="libx264", format="FFMPEG")
        for f in frames:
            # 버퍼에는 이미 바운딩 박스가 그려진 RGB(PIL 기반) 프레임이 저장되어 있으므로
            # 별도 색공간 변환 없이 그대로 씁니다.
            writer.append_data(f)
        writer.close()

        if not st.session_state.get("S3_ENABLED"):
            return  # S3 미설정 시 클립을 만들 이유가 없음 (스냅샷 이미지 그대로 유지)

        key = s3.upload_clip(clip_path, pc["camera_name"])
        if key:
            _apply_clip_to_log(pc["aid"], key)
    finally:
        try:
            os.remove(clip_path)
        except Exception:
            pass


def _apply_clip_to_log(aid: int, s3_key: str) -> None:
    """해당 로그의 스냅샷 경로/타입을 방금 업로드한 클립으로 교체합니다.
    메모리(session_state)와 DB 양쪽 모두 갱신합니다."""
    ss = st.session_state
    for a in ss.detection_logs:
        if a.get("id") == aid:
            a["image_path"] = s3_key
            a["uri"] = s3_key           # 로그 조회 화면은 uri를 우선 참조하므로 함께 갱신
            a["content_type"] = "video/mp4"
            if ss.get("DB_ENABLED"):
                try:
                    db.update_snapshot_uri(aid, s3_key, "video/mp4")
                except Exception as e:
                    ss["db_write_warning"] = f"클립 정보 저장 실패: {e}"
            break


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

            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

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
            # PIL 이미지(RGB)를 그대로 numpy 배열로 바꿔서 씁니다 (imageio도 RGB를 기대함).
            annotated_np = np.array(annotated)
            # 최근 CLIP_PRE_SECONDS 분량을 순환 버퍼에 추가 — 탐지 여부와 무관하게 매 처리 프레임마다 채워둡니다.
            _push_frame_buffer(cid, annotated_np, now)
            # 새로 생성된 로그(사람+동물 모두)마다 전후 클립 녹화를 시작
            _start_pending_clips(cam, new_alert_ids, fps, now)
            # 대기 중인 클립들에 이번 프레임을 추가하고, 인코딩+업로드가 완료되면 UI 갱신 예약
            if _append_pending_clips(cid, annotated_np, now):
                need_ui_refresh = True

            ss[f"result_{cid}"] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            time.sleep(0.005)

        if need_ui_refresh:
            st.rerun()

        if frames_processed == 0:
            break
    st.rerun()