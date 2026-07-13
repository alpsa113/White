"""services/video_analyzer.py — 영상을 두 단계로 처리합니다.

1단계(사전 분석): 영상을 지정하면 백그라운드에서 전체를 훑어 프레임별 탐지 결과를 타임라인으로
캐싱하고, 트랙 경계를 시뮬레이션해 트랙별 클립도 미리 전부 추출/업로드해둡니다(_build_clip_plan).
2단계(실시간 페이서): 탐지 기록이 실제 재생 속도로 쌓이도록, 캐시된 타임라인을 그 속도에 맞춰
다시 흘려보내며 트래킹/알림만 수행합니다. 새 트랙이 생기면 1단계에서 만들어둔 클립을 같은
순번으로 바로 붙입니다(실시간 추출 없음). <video loop>처럼 끝나면 처음부터 반복합니다.
"""
import bisect
import json
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

import db_rds as db
import s3_storage as s3
import state_store as store
from config import CLIP_PRE_SECONDS, CLIP_POST_SECONDS, MAX_CLIP_SECONDS, CLIP_EXTRACTION_WORKERS
from services import model_runtime
from services.detection import run_detection, draw_boxes
from services.tracking import process_frame, simulate_tracks_offline

# 클립 추출 작업 큐 — 분석 단계에서 트랙별 클립을 병렬로 미리 만들어둘 때 사용합니다.
_clip_executor = ThreadPoolExecutor(max_workers=CLIP_EXTRACTION_WORKERS, thread_name_prefix="clip-extract")

# 0.2초(초당 5회) 간격으로 샘플링합니다 — 캔버스에서 박스를 그릴 때 이 정도면 충분히 매끄럽게
# 보이고, 매 프레임을 다 도는 것보다 분석 시간을 크게 줄여줍니다.
SAMPLE_INTERVAL_MS = 200

_status: dict[str, dict] = {}  # key(f"{cid}_{channel}") -> {"status", "progress", "error"}
_pacer_stop_events: dict[str, threading.Event] = {}
# key(f"{cid}_{channel}") -> {카테고리(사람은 tracking.PERSON_PLAN_KEY, 동물은 class_name): [클립 S3 키 또는 None, ...]}
_clip_plans: dict[str, dict[str, list[str | None]]] = {}


def shutdown() -> None:
    """서버 종료(--reload 재시작 포함) 시 재생 페이서와 클립 추출 큐를 정리합니다."""
    for ev in list(_pacer_stop_events.values()):
        ev.set()
    _clip_executor.shutdown(wait=False, cancel_futures=True)


def get_status(key: str) -> dict:
    return _status.get(key, {"status": "idle", "progress": 0.0})


def _sidecar_path(video_path: str) -> str:
    return video_path + ".detections.json"


def get_timeline(video_path: str) -> list[dict] | None:
    """이미 분석이 끝난 영상이면 캐싱된 타임라인을 반환합니다(없으면 None)."""
    path = _sidecar_path(video_path)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if not isinstance(payload, list):
        return None  # 예전(데모 모드 태그 포함) 포맷 캐시 — 신뢰할 수 없으므로 재분석
    return payload


def start_analysis(cam: dict, channel: str, video_path: str, filename: str) -> None:
    """이미 분석돼 있으면 클립 계획만 다시 만들고, 아니면 분석부터 백그라운드로 시작합니다.
    클립 계획(_clip_plans)은 인메모리라 서버 재시작 시 사라지므로 매번 다시 준비합니다."""
    key = f"{cam['id']}_{channel}"
    cached = get_timeline(video_path)
    if cached is not None:
        _status[key] = {"status": "analyzing", "progress": 0.99}
        threading.Thread(
            target=_prepare_and_start_pacer, args=(cam, video_path, key, cached), daemon=True
        ).start()
        return
    _status[key] = {"status": "analyzing", "progress": 0.0}
    threading.Thread(target=_run_analysis, args=(cam, video_path, key), daemon=True).start()


def stop_analysis(cid: str, channel: str) -> None:
    """카메라/채널이 삭제되거나 영상이 바뀌면 실제 재생 속도 페이서를 멈춥니다."""
    key = f"{cid}_{channel}"
    ev = _pacer_stop_events.pop(key, None)
    if ev is not None:
        ev.set()
    _status.pop(key, None)
    _clip_plans.pop(key, None)


def _run_analysis(cam: dict, video_path: str, key: str) -> None:
    """1단계: 모델을 최대한 빠르게 돌려 프레임별 탐지 결과만 계산합니다(트래킹/알림 없음 —
    같은 개체를 여러 번 세는지는 신경 쓰지 않고 순수 탐지 결과만 필요합니다)."""
    try:
        if not HAS_CV2:
            raise RuntimeError("cv2가 설치되어 있지 않습니다.")
        if not model_runtime.is_loaded():
            model_runtime.load_model()

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError("영상을 열 수 없습니다.")

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_ms = (total_frames / fps) * 1000 if fps else 0
        frame_interval = max(1, round(fps * SAMPLE_INTERVAL_MS / 1000))

        timeline: list[dict] = []
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % frame_interval == 0:
                ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)
                try:
                    dets, _conf, _nms, latency_ms = run_detection(pil_img)
                except Exception:
                    dets, latency_ms = [], 0.0
                timeline.append({"t": ts_ms, "dets": dets, "latency_ms": latency_ms})
                if duration_ms:
                    _status[key] = {"status": "analyzing", "progress": min(0.99, ts_ms / duration_ms)}
            idx += 1
        cap.release()

        with open(_sidecar_path(video_path), "w", encoding="utf-8") as f:
            json.dump(timeline, f)

        _prepare_and_start_pacer(cam, video_path, key, timeline)
    except Exception as e:
        _status[key] = {"status": "error", "progress": 0.0, "error": str(e)}


def _prepare_and_start_pacer(cam: dict, video_path: str, key: str, timeline: list[dict]) -> None:
    """클립 계획을 만든 뒤 "ready"로 전환하고 재생 페이서를 시작합니다(재생 시작 전에 클립까지 준비 완료)."""
    _build_clip_plan(video_path, cam, key, timeline)
    _status[key] = {"status": "ready", "progress": 1.0}
    _start_pacer(cam, video_path, key, timeline)


def _build_clip_plan(video_path: str, cam: dict, key: str, timeline: list[dict]) -> None:
    """타임라인을 시뮬레이션해(simulate_tracks_offline) 트랙 경계를 계산하고, 트랙마다 클립을
    미리 추출/업로드해 계획을 만듭니다. 실시간 재생은 이 계획에서 클립을 찾아 붙이기만 합니다."""
    if not store.status.get("s3_enabled"):
        _clip_plans[key] = {}
        return
    track_events = simulate_tracks_offline(timeline)
    plan: dict[str, list[str | None]] = {}
    for cls_name, events in track_events.items():
        futures = [
            _clip_executor.submit(
                _extract_clip_to_s3, video_path, cam["name"], ev["first_ts"], ev["last_ts"], timeline
            )
            for ev in events
        ]
        plan[cls_name] = [f.result() for f in futures]
    _clip_plans[key] = plan


def _start_pacer(cam: dict, video_path: str, key: str, timeline: list[dict]) -> None:
    """이미 실행 중이면 그대로 두고, 아니면 2단계(실제 재생 속도 재생) 스레드를 시작합니다."""
    if key in _pacer_stop_events:
        return
    stop_event = threading.Event()
    _pacer_stop_events[key] = stop_event
    threading.Thread(target=_run_pacer, args=(cam, video_path, key, timeline, stop_event), daemon=True).start()


def _open_capture(video_path: str, retries: int = 5, delay: float = 0.5):
    """cv2.VideoCapture를 엽니다. 같은 영상 파일을 여러 초소/채널 페이서가 동시에 여는
    경우(데모 영상을 재사용하는 설정) 드물게 첫 open이 실패할 수 있어 재시도합니다."""
    for _ in range(retries):
        cap = cv2.VideoCapture(video_path)
        if cap.isOpened():
            return cap
        cap.release()
        time.sleep(delay)
    return None


def _run_pacer(cam: dict, video_path: str, key: str, timeline: list[dict], stop_event: threading.Event) -> None:
    """2단계: 캐시된 탐지 결과를 실제 재생 속도에 맞춰 흘려보내며 트래킹/알림만 수행합니다.
    <video loop>처럼 끝나면 처음부터 반복합니다."""
    if not timeline:
        return
    cap = _open_capture(video_path) if HAS_CV2 else None
    if HAS_CV2 and cap is None:
        print(f"[video_analyzer] {key} 영상을 열지 못해 실시간 알림 기록을 시작하지 못했습니다: {video_path}")
        return
    cam_state = {"person_tracks": {}, "animal_tracks": {}, "last_toasts": {}, "last_dets": []}
    consecutive_grab_failures = 0

    while not stop_event.is_set():
        cycle_start_wall = time.time()
        for entry in timeline:
            if stop_event.is_set():
                break
            target_wall = cycle_start_wall + entry["t"] / 1000.0
            sleep_for = target_wall - time.time()
            if sleep_for > 0:
                stop_event.wait(sleep_for)
            if not entry["dets"]:
                continue

            pil_img = _grab_frame(cap, entry["t"])
            if pil_img is None:
                # 프레임을 못 읽는 상태가 이어지면(핸들이 끊긴 경우 등) 재시도 없이는
                # 이 채널의 알림이 영원히 쌓이지 않으므로, 일정 횟수 실패 시 캡처를 재오픈합니다.
                consecutive_grab_failures += 1
                if consecutive_grab_failures >= 10:
                    consecutive_grab_failures = 0
                    cap.release()
                    reopened = _open_capture(video_path)
                    if reopened is not None:
                        cap = reopened
                continue
            consecutive_grab_failures = 0

            try:
                _dets, _is_new, _new_alert_ids, toasts, new_track_infos = process_frame(
                    cam, pil_img, "영상", cam_state=cam_state,
                    timestamp_ms=entry["t"], precomputed_dets=entry["dets"],
                    precomputed_latency_ms=entry.get("latency_ms", 0.0),
                )
                for cls_name in toasts:
                    store.add_toast_event(cam["name"], cls_name)
            except Exception as e:
                print(f"[video_analyzer] {key} 실시간 페이스 기록 실패: {e}")
                continue

            _attach_planned_clips(key, new_track_infos)

        # 한 바퀴 다 돌았으면 트랙을 리셋하고 처음부터 다시(<video loop>와 동일).
        cam_state["person_tracks"] = {}
        cam_state["animal_tracks"] = {}

    if cap is not None:
        cap.release()


def _attach_planned_clips(key: str, new_track_infos: list[tuple[int, str, int]]) -> None:
    """새로 생성된 트랙마다 클립 계획에서 같은 순번의 클립을 찾아 곧바로 붙입니다."""
    plan = _clip_plans.get(key)
    if not plan:
        return
    for aid, cls_name, idx in new_track_infos:
        uris = plan.get(cls_name)
        if not uris:
            continue
        clip_uri = uris[idx % len(uris)]
        if clip_uri:
            _attach_clip(aid, clip_uri)


def _attach_clip(aid: int, clip_uri: str) -> None:
    """미리 만들어둔 클립의 S3 키를 탐지 기록(RDS 및 메모리 캐시)에 곧바로 연결합니다."""
    db.update_snapshot_uri(aid, clip_uri, "video/mp4")
    for a in store.detection_logs:
        if a.get("id") == aid:
            a["image_path"] = clip_uri
            a["uri"] = clip_uri
            a["content_type"] = "video/mp4"
            break


def _grab_frame(cap, ts_ms: float) -> Image.Image | None:
    if cap is None:
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, ts_ms)
    ret, frame = cap.read()
    if not ret:
        return None
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _nearest_dets(timeline: list[dict], t_values: list[float], ts_ms: float) -> list[dict]:
    """타임라인에서 ts_ms에 가장 가까운 항목의 탐지 결과를 반환합니다(정렬된 리스트 이진 탐색)."""
    if not timeline:
        return []
    i = bisect.bisect_left(t_values, ts_ms)
    if i <= 0:
        return timeline[0]["dets"]
    if i >= len(timeline):
        return timeline[-1]["dets"]
    before, after = timeline[i - 1], timeline[i]
    return before["dets"] if (ts_ms - before["t"]) <= (after["t"] - ts_ms) else after["dets"]


def _extract_clip_to_s3(video_path: str, camera_name: str, first_ts_ms: float, last_ts_ms: float,
                        timeline: list[dict]) -> str | None:
    """[최초~마지막 탐지 시각](+전후 여유) 구간을 원본 영상에서 잘라 박스를 그린 뒤 mp4로
    인코딩해 S3에 올리고 객체 키를 반환합니다(실패 시 None). 구간 탐색은 CAP_PROP_POS_MSEC
    대신 프레임 번호(CAP_PROP_POS_FRAMES) 기준으로 합니다(코덱에 따라 POS_MSEC seek이
    부정확해 클립이 비거나 깨지는 경우가 있었음)."""
    import imageio.v2 as imageio

    try:
        if not HAS_CV2:
            return None
        start_sec = max(0.0, first_ts_ms / 1000.0 - CLIP_PRE_SECONDS)
        end_sec = last_ts_ms / 1000.0 + CLIP_POST_SECONDS
        end_sec = min(end_sec, start_sec + MAX_CLIP_SECONDS)
        t_values = [e["t"] for e in timeline]

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start_frame = max(0, int(round(start_sec * fps)))
        end_frame = max(start_frame, int(round(end_sec * fps)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        frames = []
        for frame_idx in range(start_frame, end_frame + 1):
            ret, frame = cap.read()
            if not ret:
                break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)
            cur_ms = frame_idx / fps * 1000.0
            dets = _nearest_dets(timeline, t_values, cur_ms)
            annotated = draw_boxes(pil_img, dets)
            frames.append(np.array(annotated))
        cap.release()

        if not frames:
            print(f"[video_analyzer] 클립 프레임을 하나도 읽지 못함: {start_sec:.1f}s~{end_sec:.1f}s")
            return None

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            clip_path = tmp.name
        try:
            writer = imageio.get_writer(clip_path, fps=fps, codec="libx264", format="FFMPEG")
            try:
                for f in frames:
                    writer.append_data(f)
            finally:
                writer.close()
            return s3.upload_clip(clip_path, camera_name)
        finally:
            try:
                os.remove(clip_path)
            except Exception:
                pass
    except Exception as e:
        print(f"[video_analyzer] 클립 추출 실패: {e}")
        return None
