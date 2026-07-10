"""services/clip_recorder.py — 탐지 전후 짧은 클립을 녹화해 mp4로 인코딩, S3 업로드합니다."""
import os
import tempfile
import threading
from collections import deque

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

import imageio.v2 as imageio  # H.264 인코딩 (cv2.VideoWriter는 브라우저 호환 코덱을 못 만듦)

import db_rds as db
import s3_storage as s3
from config import CLIP_PRE_SECONDS, CLIP_POST_SECONDS, MAX_PENDING_CLIPS_PER_CAMERA


def push_frame_buffer(cid: str, frame_rgb, now: float) -> None:
    """최근 CLIP_PRE_SECONDS 분량만 유지하는 순환 버퍼에 프레임을 추가합니다."""
    ss = st.session_state
    buf = ss.setdefault(f"frame_buffer_{cid}", deque())
    buf.append((now, frame_rgb.copy()))
    cutoff = now - CLIP_PRE_SECONDS
    while buf and buf[0][0] < cutoff:
        buf.popleft()


def start_pending_clips(cam: dict, new_alert_ids: list[int], now: float) -> None:
    """새 탐지마다 버퍼의 '이전 N초'를 시작점으로 대기 클립을 등록합니다.
    카메라당 MAX_PENDING_CLIPS_PER_CAMERA를 넘으면 건너뜁니다(로그는 남고 클립만 생략)."""
    if not new_alert_ids:
        return
    ss = st.session_state
    cid = cam["id"]
    pending = ss.setdefault(f"pending_clips_{cid}", [])

    room = MAX_PENDING_CLIPS_PER_CAMERA - len(pending)
    if room <= 0:
        return
    ids_to_start = new_alert_ids[:room]

    buf = ss.get(f"frame_buffer_{cid}", deque())
    pre_entries = list(buf)

    for aid in ids_to_start:
        pending.append({
            "aid": aid,
            "camera_name": cam["name"],
            "entries": list(pre_entries),
            "capture_until": now + CLIP_POST_SECONDS,
        })


def append_pending_clips(cid: str, frame_rgb, now: float) -> None:
    """대기 클립에 프레임을 계속 채우고, 목표 시간에 도달하면 별도 스레드에서 인코딩합니다."""
    ss = st.session_state
    pending = ss.get(f"pending_clips_{cid}", [])
    if not pending:
        return

    still_pending = []
    for pc in pending:
        pc["entries"].append((now, frame_rgb.copy()))
        if now >= pc["capture_until"]:
            _finalize_clip_async(pc)
        else:
            still_pending.append(pc)
    ss[f"pending_clips_{cid}"] = still_pending


def _finalize_clip_async(pc: dict) -> None:
    """_finalize_clip()을 별도 스레드에서 실행하고, 완료되면 _clip_ready_flag를 올립니다."""
    ctx = get_script_run_ctx()

    def _run():
        try:
            _finalize_clip(pc)
        finally:
            st.session_state["_clip_ready_flag"] = st.session_state.get("_clip_ready_flag", 0) + 1

    thread = threading.Thread(target=_run, daemon=True)
    if ctx is not None:
        add_script_run_ctx(thread, ctx)
    thread.start()


def _finalize_clip(pc: dict) -> None:
    """모아둔 프레임을 mp4(H.264)로 인코딩해 S3에 올리고, 로그의 스냅샷 경로를 교체합니다.
    fps는 프레임 개수가 아니라 실제 경과 시간으로 역산해, 재생 시간이 항상 실제 시간과 맞도록 합니다."""
    entries = pc["entries"]
    if not entries:
        return
    frames = [f for _, f in entries]

    elapsed = entries[-1][0] - entries[0][0]
    fps = (len(frames) - 1) / elapsed if len(frames) > 1 and elapsed > 0 else 10.0
    fps = max(1.0, min(fps, 60.0))

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        clip_path = tmp.name

    try:
        writer = imageio.get_writer(clip_path, fps=fps, codec="libx264", format="FFMPEG")
        try:
            for f in frames:
                writer.append_data(f)
        finally:
            writer.close()

        if not st.session_state.get("S3_ENABLED"):
            return

        key = s3.upload_clip(clip_path, pc["camera_name"])
        if key:
            _apply_clip_to_log(pc["aid"], key)
    except Exception as e:
        st.session_state["db_write_warning"] = f"클립 인코딩 실패 (탐지 ID {pc.get('aid')}): {e}"
    finally:
        try:
            os.remove(clip_path)
        except Exception:
            pass


def _apply_clip_to_log(aid: int, s3_key: str) -> None:
    """해당 로그의 스냅샷 경로를 업로드한 클립으로 교체합니다(메모리+DB 모두)."""
    ss = st.session_state
    for a in ss.detection_logs:
        if a.get("id") == aid:
            a["image_path"] = s3_key
            a["uri"] = s3_key
            a["content_type"] = "video/mp4"
            a["snapshot"] = None
            if ss.get("DB_ENABLED"):
                try:
                    db.update_snapshot_uri(aid, s3_key, "video/mp4")
                except Exception as e:
                    ss["db_write_warning"] = f"클립 정보 저장 실패: {e}"
            break
