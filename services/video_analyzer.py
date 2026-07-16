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

# 탐지 대상 없이 배경만 찍어둔 정적 이미지 카메라(예: config.py DEMO_VIDEOS의 "GOP배경")를
# 위한 확장자 목록 — 이 확장자면 cv2 분석/실시간 페이서를 건너뛰고 곧바로 "ready"로 표시합니다.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def is_image_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS

_status: dict[str, dict] = {}  # key(f"{cid}_{channel}") -> {"status", "progress", "error"}
_pacer_stop_events: dict[str, threading.Event] = {}
# key(f"{cid}_{channel}") -> {카테고리(사람은 tracking.PERSON_PLAN_KEY, 동물은 class_name): [클립 S3 키 또는 None, ...]}
_clip_plans: dict[str, dict[str, list[str | None]]] = {}
# 페이서가 지금 타임라인의 어느 지점을 흘려보내고 있는지 — 프론트엔드가 <video>를 이 위치로
# seek해서, "알림이 뜬 순간"과 "화면에 보이는 장면"이 실제로 일치하도록 맞추는 데 씁니다
# (get_pacer_position 참고). 브라우저의 duration 추정치에 기대는 대신, 페이서 스스로가
# 진행 중인 정확한 위치를 그때그때 보고합니다.
_pacer_cycle_start: dict[str, float] = {}  # key -> 이번 바퀴가 시작된 실제 시각(time.time())
_pacer_duration_sec: dict[str, float] = {}  # key -> 한 바퀴(루프)의 길이(초)
# cam_id -> 그 카메라의 EO/TIR 채널이 함께 공유하는 재생 루프의 "원점" 시각(time.time()).
# 늦게 끝난 채널이 혼자 뒤처져 t=0부터 다시 시작하지 않도록, 같은 카메라의 형제 채널들이
# _cam_expected에 적어둔 채널을 모두 준비 마칠 때까지 기다렸다가(_cam_pending_start) 다같이
# 이 원점에서 동시에 재생을 시작합니다(_prepare_then_wait_for_siblings 참고).
_cam_origin: dict[str, float] = {}
# cam_id -> 그 카메라에서 "같이 시작"을 맞춰야 하는 채널 집합(정적 이미지 채널은 제외 — 재생
# 루프 자체가 없으므로 대기 대상이 아님). 카메라에 영상 채널이 하나뿐이면 곧바로 시작합니다.
_cam_expected: dict[str, set[str]] = {}
# cam_id -> {channel: (cam, video_path, timeline)} — 분석/클립 준비는 끝났지만 형제 채널이
# 아직 준비되지 않아 대기 중인 채널들의 대기실.
_cam_pending_start: dict[str, dict[str, tuple]] = {}
_cam_barrier_lock = threading.Lock()


def shutdown() -> None:
    """서버 종료(--reload 재시작 포함) 시 재생 페이서와 클립 추출 큐를 정리합니다."""
    for ev in list(_pacer_stop_events.values()):
        ev.set()
    _clip_executor.shutdown(wait=False, cancel_futures=True)


def get_status(key: str) -> dict:
    return _status.get(key, {"status": "idle", "progress": 0.0})


def _get_cam_origin(cam_id: str) -> float:
    """카메라(EO/TIR 공통)의 재생 루프 원점을 반환합니다. 보통은 _prepare_then_wait_for_siblings가
    형제 채널이 모두 모인 순간에 이미 정해둔 값을 그대로 씁니다. 바리어를 거치지 않은 예외적인
    경로(형제가 없는 단일 채널 카메라 등)에서만 지금 이 순간을 새 원점으로 잡습니다."""
    origin = _cam_origin.get(cam_id)
    if origin is None:
        origin = time.time()
        _cam_origin[cam_id] = origin
    return origin


def get_pacer_position(key: str) -> float | None:
    """페이서가 지금 타임라인의 몇 ms 지점을 흘려보내고 있는지 실시간으로 계산합니다.
    아직 페이서가 시작되지 않았으면(분석 중이거나 이미지 카메라) None."""
    cycle_start = _pacer_cycle_start.get(key)
    duration_sec = _pacer_duration_sec.get(key)
    if cycle_start is None or not duration_sec:
        return None
    return ((time.time() - cycle_start) % duration_sec) * 1000.0


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


def start_analysis(
    cam: dict, channel: str, video_path: str, filename: str, expected_channels: set[str] | None = None
) -> None:
    """이미 분석돼 있으면 클립 계획만 다시 만들고, 아니면 분석부터 백그라운드로 시작합니다.
    클립 계획(_clip_plans)은 인메모리라 서버 재시작 시 사라지므로 매번 다시 준비합니다.
    정적 이미지(탐지 대상 없는 배경 컷)는 분석/실시간 페이서 없이 곧바로 표시만 합니다.

    expected_channels: 이 카메라에서 재생을 함께 맞춰야 하는(=영상인) 채널 집합. EO/TIR처럼
    쌍을 이루는 카메라는 호출하는 쪽(routers/outposts.py)에서 두 채널 모두에 같은 집합을
    넘겨줍니다 — 준비가 먼저 끝난 채널이 있어도 이 집합이 전부 준비될 때까지 재생을 미루고,
    다 모이면 그 순간을 공동 원점으로 삼아 동시에 시작합니다."""
    key = f"{cam['id']}_{channel}"
    if expected_channels:
        _cam_expected[str(cam["id"])] = set(expected_channels)
    if is_image_path(video_path):
        _status[key] = {"status": "ready", "progress": 1.0, "kind": "image"}
        return
    cached = get_timeline(video_path)
    if cached is not None:
        _status[key] = {"status": "analyzing", "progress": 0.99}
        threading.Thread(
            target=_prepare_then_wait_for_siblings, args=(cam, video_path, key, cached), daemon=True
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
    _pacer_cycle_start.pop(key, None)
    _pacer_duration_sec.pop(key, None)
    with _cam_barrier_lock:
        pending = _cam_pending_start.get(cid)
        if pending is not None:
            pending.pop(channel, None)
            if not pending:
                _cam_pending_start.pop(cid, None)
    # 이 카메라의 마지막 채널까지 다 멈췄으면 공유 원점/대기 집합도 정리합니다 — 남은 채널이
    # 없으므로 다음에 다시 시작할 때 새로 바리어를 잡아도 아무도 어긋나지 않습니다.
    if not any(k.startswith(f"{cid}_") for k in _pacer_stop_events):
        _cam_origin.pop(cid, None)
        _cam_expected.pop(cid, None)


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

        _prepare_then_wait_for_siblings(cam, video_path, key, timeline)
    except Exception as e:
        _status[key] = {"status": "error", "progress": 0.0, "error": str(e)}


def _prepare_then_wait_for_siblings(cam: dict, video_path: str, key: str, timeline: list[dict]) -> None:
    """클립 계획을 만들어 이 채널의 재생 준비를 마친 뒤, 같은 카메라의 형제 채널(EO/TIR)이 모두
    준비될 때까지 대기실(_cam_pending_start)에 들어갑니다. 먼저 끝난 채널은 여기서 멈춰 서서
    혼자 앞서 재생을 시작하지 않고, 마지막 채널까지 도착하는 순간 다같이 "ready"로 바뀌며
    바로 그 순간을 공동 원점으로 페이서를 동시에 시작합니다."""
    _build_clip_plan(video_path, cam, key, timeline)
    cam_id = str(cam["id"])
    channel = key.rsplit("_", 1)[-1]

    with _cam_barrier_lock:
        pending = _cam_pending_start.setdefault(cam_id, {})
        pending[channel] = (cam, video_path, timeline)
        expected = _cam_expected.get(cam_id) or {channel}
        if not expected.issubset(pending.keys()):
            return  # 아직 형제 채널이 준비되지 않음 — 대기실에서 기다립니다.
        ready_group = pending
        _cam_pending_start.pop(cam_id, None)

    # 여기 도달했다는 건 기대하던 채널이 모두 모였다는 뜻 — 지금 이 순간을 공동 원점으로 삼아
    # 전부 동시에 "ready" + 페이서 시작으로 전환합니다.
    _cam_origin[cam_id] = time.time()
    for ch, (c, vpath, tl) in ready_group.items():
        k = f"{cam_id}_{ch}"
        _status[k] = {"status": "ready", "progress": 1.0}
        _start_pacer(c, vpath, k, tl)


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
    # 한 바퀴(루프)의 길이 — 타임라인의 마지막 타임스탬프를 기준으로 삼습니다(get_pacer_position이
    # "지금 몇 ms 지점인지" 계산할 때 씁니다).
    duration_sec = max(timeline[-1]["t"] / 1000.0, 0.001)
    _pacer_duration_sec[key] = duration_sec
    # 이 카메라의 다른 채널과 공유하는 원점 — 늦게 시작해도 처음(t=0)부터가 아니라 원점 기준
    # 현재 위치에서 합류합니다.
    origin = _get_cam_origin(str(cam["id"]))
    # 합류 시점에 이미 지나간 항목들은 처리하지 않고 조용히 건너뜁니다(그렇지 않으면 시작하자마자
    # "이미 지난" 알림들이 한꺼번에 몰려서 뜨게 됨). 한 바퀴를 다 돈 뒤에는 항상 처음부터이므로
    # 더 이상 건너뛸 필요가 없습니다.
    catching_up = True

    while not stop_event.is_set():
        now = time.time()
        elapsed_cycles = int((now - origin) // duration_sec)
        cycle_start_wall = origin + elapsed_cycles * duration_sec
        _pacer_cycle_start[key] = cycle_start_wall
        for entry in timeline:
            if stop_event.is_set():
                break
            target_wall = cycle_start_wall + entry["t"] / 1000.0
            if catching_up and target_wall < time.time():
                continue
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
        catching_up = False
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
