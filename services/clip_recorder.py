"""
services/clip_recorder.py — 탐지 전후 짧은 클립 녹화

최근 CLIP_PRE_SECONDS 분량의 프레임을 카메라별로 순환 버퍼에 담아두다가,
새로운 탐지가 발생하면 그 버퍼를 시작점으로 CLIP_POST_SECONDS만큼 더 채운 뒤
mp4(H.264)로 인코딩해 S3에 올리고, 로그의 스냅샷 경로를 그 클립으로 교체합니다.

인코딩·업로드는 services/playback.py의 재생 루프를 막지 않도록 항상
별도 스레드에서 실행됩니다 — push_frame_buffer()/start_pending_clips()/
append_pending_clips() 세 함수가 이 파일의 공개 API입니다.

[메모리 관리 원칙] 이 파일이 다루는 프레임(순환 버퍼 + 대기 클립)은 메모리
사용량이 가장 크게 늘어날 수 있는 지점입니다 — 한 프레임이 축소 후에도
수백KB~수MB이고, 이게 카메라별로 최대 CLIP_PRE+POST_SECONDS(기본 6초) 분량
쌓입니다. 두 가지 안전장치를 둡니다: ① services/playback.py가 이 파일에
넘기는 프레임은 화면 표시용 해상도가 아니라 CLIP_STORAGE_MAX_WIDTH로 미리
축소된 프레임입니다. ② start_pending_clips()는 카메라 1대당 동시 대기 클립
개수를 MAX_PENDING_CLIPS_PER_CAMERA로 제한합니다 — 탐지가 몰릴 때 대기
클립이 무한정 늘어나는 것을 막습니다.
"""
import os
import tempfile
import threading
from collections import deque

import streamlit as st
from streamlit.runtime.scriptrunner import add_script_run_ctx, get_script_run_ctx

import imageio.v2 as imageio  # H.264 인코딩 전용 — cv2.VideoWriter는 브라우저 재생용 코덱을 못 만듦 (아래 _finalize_clip 참고)

import db_rds as db
import s3_storage as s3
from config import CLIP_PRE_SECONDS, CLIP_POST_SECONDS, MAX_PENDING_CLIPS_PER_CAMERA


def push_frame_buffer(cid: str, frame_rgb, now: float) -> None:
    """최근 CLIP_PRE_SECONDS 분량의 프레임(바운딩 박스가 그려진 RGB 배열)만
    유지하는 순환 버퍼에 프레임을 추가합니다. 오래된 프레임은 자동으로 버려집니다."""
    ss = st.session_state
    buf = ss.setdefault(f"frame_buffer_{cid}", deque())
    buf.append((now, frame_rgb.copy()))
    cutoff = now - CLIP_PRE_SECONDS
    while buf and buf[0][0] < cutoff:
        buf.popleft()


def start_pending_clips(cam: dict, new_alert_ids: list[int], fps: float, now: float) -> None:
    """새로 탐지된 로그마다, 지금까지 쌓인 '이전 N초' 프레임을 시작점으로 하는
    대기 클립을 등록합니다. 이후 프레임은 append_pending_clips()가 계속 채우다가,
    CLIP_POST_SECONDS가 지나면 자동으로 인코딩·업로드됩니다.

    [메모리 관리] 대기 클립 1개는 CLIP_PRE+POST_SECONDS(기본 6초) 분량의
    프레임을 통째로 들고 있습니다 — 짧은 시간에 새 탐지가 여러 건 연달아
    발생하면(예: 여러 사람이 잇따라 등장) 카메라 1대에서 대기 클립이 동시에
    여러 개 쌓일 수 있는데, 그만큼 메모리도 배로 늘어납니다.
    MAX_PENDING_CLIPS_PER_CAMERA를 넘어서는 요청은 건너뜁니다 — 로그 자체는
    그대로 남고(탐지를 놓치지 않음), 그 사건의 짧은 리뷰 클립만 생략됩니다."""
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
    pre_frames = [f for _, f in buf]  # 지금까지의 '이전 N초' 프레임 복사

    for aid in ids_to_start:
        pending.append({
            "aid": aid,
            "camera_name": cam["name"],
            "frames": list(pre_frames),
            "capture_until": now + CLIP_POST_SECONDS,
            "fps": fps,
        })


def append_pending_clips(cid: str, frame_rgb, now: float) -> None:
    """대기 중인 클립들에 현재 프레임(바운딩 박스가 그려진 RGB 배열)을 계속
    추가하고, 목표 시간(탐지 이후 CLIP_POST_SECONDS)에 도달한 클립은 별도
    스레드에서 mp4로 인코딩해 S3에 업로드합니다.

    인코딩+업로드를 메인 루프 안에서 동기적으로 하면 몇 초씩 걸릴 수 있어,
    그 사이 모든 카메라의 화면 갱신이 멈춰버립니다(다른 페이지에 다녀왔을 때
    "영상이 사라진 것처럼" 보이는 증상의 원인). 백그라운드 스레드로 넘겨
    메인 루프는 끊김 없이 계속 진행되도록 합니다."""
    ss = st.session_state
    pending = ss.get(f"pending_clips_{cid}", [])
    if not pending:
        return

    still_pending = []
    for pc in pending:
        pc["frames"].append(frame_rgb.copy())
        if now >= pc["capture_until"]:
            _finalize_clip_async(pc)
        else:
            still_pending.append(pc)
    ss[f"pending_clips_{cid}"] = still_pending


def _finalize_clip_async(pc: dict) -> None:
    """_finalize_clip()을 별도 스레드에서 실행합니다. add_script_run_ctx로
    현재 세션의 컨텍스트를 넘겨줘야, 스레드 안에서도 session_state를 안전하게
    읽고 쓸 수 있습니다. 완료되면 _clip_ready_flag를 증가시켜, 재생 루프가
    다음 반복에서 이를 감지해 화면을 갱신하도록 신호를 남깁니다."""
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
    """모아둔 프레임을 mp4(H.264) 파일로 인코딩하고 S3에 업로드한 뒤, 해당 로그
    레코드의 스냅샷 경로를 이 클립으로 교체합니다.

    cv2.VideoWriter(fourcc='mp4v')는 이름과 달리 MPEG-4 Part 2라는 구형
    코덱으로 인코딩하는데, 이건 대부분의 브라우저 <video> 태그가 지원하지
    않아 "재생 시도하다가 조용히 멈추는" 증상이 납니다. imageio-ffmpeg는
    pip 설치만으로 실제 H.264(avc1) 인코딩이 가능해 웹에서 확실히 재생됩니다."""
    frames = pc["frames"]
    if not frames:
        return

    fps = pc.get("fps") or 10.0

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        clip_path = tmp.name

    try:
        writer = imageio.get_writer(clip_path, fps=fps, codec="libx264", format="FFMPEG")
        try:
            for f in frames:
                # 버퍼에는 이미 바운딩 박스가 그려진 RGB(PIL 기반) 프레임이 저장되어 있으므로
                # 별도 색공간 변환 없이 그대로 씁니다.
                writer.append_data(f)
        finally:
            writer.close()

        if not st.session_state.get("S3_ENABLED"):
            return  # S3 미설정 시 클립을 만들 이유가 없음 (스냅샷 이미지 그대로 유지)

        key = s3.upload_clip(clip_path, pc["camera_name"])
        if key:
            _apply_clip_to_log(pc["aid"], key)
        # upload_clip 실패 시(내부에서 s3_write_warning은 이미 채워짐) 해당 로그는
        # 이미지 상태로 계속 남습니다 — 원인은 상단 경고 배너에서 확인 가능
    except Exception as e:
        # 인코딩 자체가 실패한 경우 — 재생 루프를 죽이지 않고 화면 상단에 경고로 노출
        st.session_state["db_write_warning"] = f"클립 인코딩 실패 (탐지 ID {pc.get('aid')}): {e}"
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
            a["snapshot"] = None        # [메모리 관리] 클립(S3)이 준비됐으니 메모리 스냅샷은 더 이상 불필요
            if ss.get("DB_ENABLED"):
                try:
                    db.update_snapshot_uri(aid, s3_key, "video/mp4")
                except Exception as e:
                    ss["db_write_warning"] = f"클립 정보 저장 실패: {e}"
            break
