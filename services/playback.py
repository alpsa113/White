"""
services/playback.py — 영상 재생 제어 (업로드 상태 정리, 다중 카메라 재생 루프)

reset_cam_state(): 카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
run_playback_loop(): 여러 카메라의 영상을 하나의 반복문 안에서 함께 재생하며,
                    프레임마다 탐지(services/tracking.py)와 클립 녹화
                    (services/clip_recorder.py)를 호출합니다. 실제 인코딩·
                    업로드 로직은 clip_recorder.py에 위임되어 있습니다.

[EO/TIR 채널] 카메라 1대는 EO/TIR 두 채널을 각각 독립적인 "가상 카메라"처럼
취급합니다 — 이 세 함수 모두 `state_suffix` 매개변수를 받고, 모든
session_state 키를 `f"{키이름}_{cid}{state_suffix}"` 형태로 네임스페이스
하므로, "_eo"/"_tir"를 주면 같은 카메라(cid)에 대해 완전히 독립된 재생 상태
(캡처 객체·커서·재생 여부·탐지 트래킹 등)를 만들 수 있습니다.

[메모리 관리 — 왜 두 채널을 항상 동시에 재생하지 않는가] 카메라 1대당
"배경 채널"(session_state.active_channel_{cid}, 기본 EO) 하나만 페이지와
무관하게 항상 재생·탐지됩니다(services/camera_registry._sync_preset_media).
한때는 매핑된 EO/TIR을 둘 다 항상 동시에 재생했지만, cv2.VideoCapture로
프레임 하나를 디코딩할 때마다 원본 해상도 RGB 버퍼(1280x720만 해도 약
2.7MB)를 새로 할당하는데, 카메라가 여러 대인 상태에서 채널까지 배로 늘어나니
디코딩·리사이즈·박스 그리기·클립 버퍼링이 전부 동시에 두 배로 돌면서
프로세스 메모리 사용량이 감당 못 할 정도로 치솟았고, 결국 OpenCV가 이
버퍼조차 할당하지 못해(`cv::OutOfMemoryError`) 크래시하는 문제가 있었습니다.
그래서 두 번째 채널(스포트라이트 2분할의 보조 화면)은 ui/camera/card.py가
사용자가 실제로 그 화면을 켰을 때만 재생을 시작하고, 껐을 때(또는 다른
카메라로 전환할 때, ui/camera/toolbar.consume_pending_camera_switch) 바로
멈춰 리소스를 반납합니다 — 화면에 보이지 않는 채널은 탐지/로그/클립 녹화도
되지 않습니다.
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

from config import DETECT_EVERY_SECONDS, IMAGE_EXTS, VIDEO_EXTS, CLIP_STORAGE_MAX_WIDTH
from services.detection import draw_boxes
from services.tracking import process_frame
from services.clip_recorder import push_frame_buffer, start_pending_clips, append_pending_clips


# ------------------------------------------------------------------ #
# 카메라 상태 정리
# ------------------------------------------------------------------ #
def reset_cam_state(cid: str, state_suffix: str = ""):
    """카메라 채널 하나(state_suffix로 지정된 EO 또는 TIR)의 업로드/재생
    상태와 관련 리소스를 완전 정리합니다. 새 영상 업로드, 마커 삭제, 그리드
    축소로 카메라 자체가 사라질 때 등에 호출됩니다.

    EO/TIR는 서로 독립된 채널이라 한쪽을 정리해도 다른 쪽에는 영향이 없습니다
    — 카메라(마커) 자체를 완전히 제거할 때는 호출부가 "_eo"/"_tir" 양쪽을
    각각 호출해야 합니다(예: services/outposts.remove_marker)."""
    key = lambda name: f"{name}_{cid}{state_suffix}"

    if key("cap") in st.session_state:
        cap = st.session_state[key("cap")]
        if cap is not None:
            cap.release()

    if key("tmp_path") in st.session_state:
        try:
            os.remove(st.session_state[key("tmp_path")])
        except Exception:
            pass

    for k in ("cap", "tmp_path", "cursor", "total_frames", "playing", "finished",
              "result", "person_tracks", "animal_tracks", "animals_visible", "last_dets", "last_toasts", "fp",
              "fps", "play_start_wall", "play_start_frame", "last_detect_time", "progress",
              "frame_buffer", "pending_clips"):
        st.session_state.pop(key(k), None)


# ------------------------------------------------------------------ #
# 미디어 반영 (설정 페이지의 사전 업로드 + 카메라 최초 로딩 시 자동 반영 공용)
# ------------------------------------------------------------------ #
def start_camera_media(cam: dict, data: bytes, filename: str, state_suffix: str = "", detect: bool = True) -> str:
    """카메라 채널(cam)에 미디어 바이트(data)를 반영합니다 — 영상이면 재생을
    시작하고, 이미지면 1회 분석 결과를 저장합니다.

    설정 페이지에서 초소에 영상을 매핑할 때(services/outposts.set_marker_video)와,
    대시보드 진입 시 그 매핑을 카메라에 자동으로 반영할 때(services/camera_registry.
    get_active_cameras) 양쪽에서 공용으로 사용됩니다 — 기존 ui/camera/card.py의
    자체 업로드 버튼이 하던 일을 대체합니다.

    state_suffix — "_eo"/"_tir" 중 이 미디어가 어느 채널 상태로 반영될지
    지정합니다(모듈 docstring 참고). detect=False를 주면(이미지 전용 경로)
    탐지 없이 원본 이미지를 그대로 저장합니다 — 영상 재생 자체는 detect
    여부와 무관하게 항상 동작하고, 탐지/트래킹/클립 녹화는 run_playback_loop의
    detect 인자가 따로 결정합니다.

    이 함수는 st.rerun()을 직접 호출하지 않습니다 — 호출부가 언제 다시 그릴지를
    결정합니다(예: 설정 페이지 저장 버튼은 저장 후 한 번만, 카메라 목록 계산 시
    자동 반영은 같은 스크립트 실행 안에서 바로 이어서 그려지므로 별도 rerun 불필요).

    반환값: "video" | "image" | "unchanged" | "unsupported" | "no_cv2"
    """
    ss = st.session_state
    cid = cam["id"]
    key = lambda name: f"{name}_{cid}{state_suffix}"

    # 파일명+크기 조합으로 "이미 반영된 미디어인지"를 판별 — 동일하면 재처리하지 않음
    fp = (filename, len(data))
    if ss.get(key("fp")) == fp:
        return "unchanged"

    reset_cam_state(cid, state_suffix)
    ss[key("fp")] = fp
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in VIDEO_EXTS:
        if not HAS_CV2:
            return "no_cv2"
        # cv2.VideoCapture는 파일 경로가 필요하므로, 바이트를 임시파일로 먼저
        # 저장한 뒤 그 경로를 열어 재생을 시작합니다.
        with tempfile.NamedTemporaryFile(suffix="." + ext, delete=False) as tmp:
            tmp.write(data)
            ss[key("tmp_path")] = tmp.name

        cap = cv2.VideoCapture(ss[key("tmp_path")])
        ss[key("cap")] = cap
        ss[key("total_frames")] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # 영상 자체의 FPS를 읽어서 재생 속도를 실제 영상 속도에 맞춥니다.
        # 일부 영상은 FPS 값을 못 읽어오는 경우가 있어 0 이하면 30fps로 대체합니다.
        fps = cap.get(cv2.CAP_PROP_FPS)
        ss[key("fps")] = fps if fps and fps > 0 else 30.0
        ss[key("cursor")] = 0
        ss[key("playing")] = True
        ss[key("finished")] = False
        return "video"

    elif ext in IMAGE_EXTS:
        image = Image.open(io.BytesIO(data)).convert("RGB")
        if detect:
            dets, _, _ = process_frame(cam, image, "이미지", single=True)
            ss[key("result")] = draw_boxes(image, dets)
        else:
            ss[key("result")] = image
        return "image"

    else:
        return "unsupported"


# ------------------------------------------------------------------ #
# 클립/버퍼 저장용 프레임 축소
# ------------------------------------------------------------------ #
def _downscale_for_clip(frame_rgb: np.ndarray) -> np.ndarray:
    """클립/순환 버퍼에 저장할 프레임을 CLIP_STORAGE_MAX_WIDTH 이하로 축소합니다.
    화면 표시용 프레임(annotated)은 그대로 두고, 저장용으로만 별도 축소본을
    만듭니다 — 카메라가 여러 대일 때 이 저장용 프레임의 메모리 사용량이
    지배적이므로, 화면 해상도와 분리해서 관리합니다."""
    height, width = frame_rgb.shape[:2]
    if width <= CLIP_STORAGE_MAX_WIDTH:
        return frame_rgb
    new_height = int(height * CLIP_STORAGE_MAX_WIDTH / width)
    return cv2.resize(frame_rgb, (CLIP_STORAGE_MAX_WIDTH, new_height))


# ------------------------------------------------------------------ #
# 다중 카메라 재생 루프
# ------------------------------------------------------------------ #
def run_playback_loop(active_cams: list[dict], video_slots: dict, *,
                       state_suffix: str = "", detect: bool = True) -> None:
    """활성화된(재생 중인) 여러 카메라 피드를 하나의 반복문 안에서 함께 재생합니다.

    state_suffix — "_eo"/"_tir" 중 어느 채널을 돌릴지 지정합니다(모듈
    docstring 참고). app.py는 이 함수를 채널당 한 번씩(총 두 번) 호출해
    EO/TIR을 완전히 독립적으로, 항상 동시에 재생·탐지합니다. 탐지/트래킹/
    클립 녹화에 쓰는 세션 키(person_tracks, animal_tracks, last_toasts 등)도
    카메라 id 대신 "{cid}{state_suffix}"를 키로 써서 두 채널이 서로의 추적
    상태를 덮어쓰지 않도록 격리합니다 — 실제 로그에 남는 카메라 이름은
    cam["name"]을 그대로 쓰므로 이 격리는 로그 내용에 영향을 주지 않습니다.

    detect=False를 주면 탐지/트래킹/클립 녹화를 전부 건너뛰고 원본 프레임만
    그립니다(현재는 실제로 쓰이지 않지만, 순수 미리보기가 필요해지면 재사용
    가능하도록 남겨둡니다).

    이 함수는 st.rerun()을 전혀 직접 호출하지 않습니다 — 호출부(app.py)가
    EO/TIR 루프를 모두 실행한 뒤 한 번만 rerun합니다. [중요] 예전에는 새
    알람이나 클립 완성 시 이 함수 내부에서 즉시 st.rerun()을 호출했는데,
    st.rerun()은 예외를 던져 그 자리에서 스크립트 전체를 즉시 중단시킵니다
    — app.py가 EO 루프를 먼저 호출하므로, EO 쪽에서 이 조건이 걸리면(사람이
    자주 탐지되거나 클립이 자주 완성될수록 자주 걸림) TIR 루프 호출문 자체가
    같은 스크립트 실행에서 아예 실행되지 못하고 건너뛰어집니다. 그 결과
    TIR 채널이 사실상 거의 진행되지 못해 "2분할 시 왼쪽만 재생"되고, 만약
    사람이 등장하는 실제 테스트 영상이 TIR 쪽에 있었다면 그 채널 자체가
    거의 실행되지 않아 탐지 로그도 전혀 쌓이지 않는 결과로 이어졌습니다.
    지금은 새 알람/클립 완성 시 while 루프만 즉시 break하고 함수는 정상
    반환합니다 — 그러면 app.py가 이어서 다음 채널 루프를 반드시 호출한
    뒤에야 마지막에 한 번 rerun하므로, 두 채널이 매 스크립트 실행마다
    번갈아 굶는 일 없이 항상 함께 진행됩니다."""
    ss = st.session_state
    key = lambda name, cid: f"{name}_{cid}{state_suffix}"
    need_ui_refresh = False

    for cam in active_cams:
        cid = cam["id"]
        if ss.get(key("play_start_wall", cid)) is None:
            ss[key("play_start_wall", cid)] = time.time()
            ss[key("play_start_frame", cid)] = ss.get(key("cursor", cid), 0)

    while True:
        frames_processed = 0

        for cam in active_cams:
            cid = cam["id"]
            if not ss.get(key("playing", cid)):
                continue

            cap = ss.get(key("cap", cid))
            if cap is None or not cap.isOpened():
                ss[key("playing", cid)] = False
                continue

            fps = ss.get(key("fps", cid), 30.0)
            total_frames = ss.get(key("total_frames", cid), 0)

            now = time.time()
            start_wall = ss[key("play_start_wall", cid)]
            start_frame = ss[key("play_start_frame", cid)]
            target_frame = start_frame + int((now - start_wall) * fps)

            cursor = ss.get(key("cursor", cid), 0)
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
                ss[key("cursor", cid)] = cursor

            # 탐지/트래킹/클립 녹화 상태를 채널별로 격리하기 위한 키 — "카메라 id +
            # 채널 접미사" 하나를 이 채널 전용 가상 카메라 id처럼 사용합니다.
            channel_cid = f"{cid}{state_suffix}"

            def _restart_loop(cid=cid, cap=cap, channel_cid=channel_cid):
                """영상 처음으로 되돌아가 반복 재생을 이어갑니다 (24시간
                끊김없이 도는 실제 CCTV를 업로드 영상 1개로 시뮬레이션)."""
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ss[key("cursor", cid)] = 0
                ss[key("play_start_wall", cid)] = time.time()
                ss[key("play_start_frame", cid)] = 0
                if detect:
                    ss.pop(f"person_tracks_{channel_cid}", None)
                    ss.pop(f"animal_tracks_{channel_cid}", None)
                    ss.pop(f"last_dets_{channel_cid}", None)

            if total_frames and target_frame >= total_frames:
                _restart_loop()
                target_frame = 0

            frames_to_advance = min(max(1, target_frame - cursor), 30)

            # [메모리 부족 방어] 시스템 메모리가 바닥나면 cv2.VideoCapture.read()가
            # 프레임 버퍼(예: 1280x720 RGB ≈ 2.7MB)를 할당하지 못해 OpenCV 내부에서
            # OutOfMemoryError를 던지는데, 이게 C 확장 함수 호출 도중 발생하면
            # 깔끔한 ret=False가 아니라 SystemError로 새어나와 이 카메라 하나가
            # 아니라 스크립트 전체(=모든 카메라·모든 페이지)를 죽였습니다. try/except로
            # 감싸 이 카메라의 재생만 중단시키고 나머지는 계속 돌게 합니다.
            frame = None
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
                        break
            except (cv2.error, SystemError, MemoryError):
                frame = None

            if frame is None:
                ss[key("playing", cid)] = False
                ss[key("finished", cid)] = True
                continue

            frames_processed += 1
            ss[key("cursor", cid)] = cursor
            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)

            # 화면 렌더링 성능을 위해 가로 해상도를 1080px로 제한 (원본 비율 유지)
            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            if detect:
                # cam 대신 channel_cid를 id로 쓰는 가상 카메라 — person_tracks_* 등
                # 트래킹/클립 상태가 EO/TIR 사이에 서로 덮어써지지 않게 격리합니다.
                # name은 실제 카메라 이름 그대로라 로그의 "카메라" 필드는 영향받지 않습니다.
                tracking_cam = {**cam, "id": channel_cid}

                # DETECT_EVERY_SECONDS 주기마다 한 번만 실제 추론, 나머지는 직전 박스를 재사용
                last_detect = ss.get(f"last_detect_time_{channel_cid}", 0)
                if now - last_detect >= DETECT_EVERY_SECONDS:
                    ss[f"last_detect_time_{channel_cid}"] = now
                    dets, is_new_alert, new_alert_ids = process_frame(tracking_cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                    ss[f"last_dets_{channel_cid}"] = dets
                    if is_new_alert:
                        need_ui_refresh = True
                        # 사람이 새로 탐지되면 그 카메라로 자동 전환
                        # 위젯이 그려지기 전에 반영되도록 예약 방식(_pending_selected_cam)을 재사용
                        ss["_pending_selected_cam"] = cam["name"]
                else:
                    dets = ss.get(f"last_dets_{channel_cid}", [])
                    new_alert_ids = []

                annotated = draw_boxes(pil_img, dets)

                # 클립/버퍼에는 바운딩 박스가 그려진 화면(annotated)을 저장해야 합니다 —
                # 박스를 그리기 전의 원본 프레임을 저장하면 클립 재생 시 박스가 보이지 않습니다.
                # 다만 클립은 화면 표시(최대 1080px)만큼 고해상도일 필요가 없으므로,
                # CLIP_STORAGE_MAX_WIDTH로 한 번 더 축소한 별도 사본을 만들어 넘깁니다 —
                # 카메라 여러 대가 동시에 버퍼/대기 클립을 들고 있는 상황에서 메모리
                # 사용량을 몇 배 줄여주는 핵심 조치입니다(§services/clip_recorder.py
                # 모듈 docstring의 "메모리 관리 원칙" 참고). 버퍼/대기 클립도
                # channel_cid로 격리해 EO/TIR의 클립이 서로 섞이지 않게 합니다.
                clip_frame = _downscale_for_clip(np.array(annotated))  # PIL(RGB) → numpy 배열 (imageio도 RGB를 기대함)
                push_frame_buffer(channel_cid, clip_frame, now)                # 최근 N초 순환 버퍼에 추가
                start_pending_clips(tracking_cam, new_alert_ids, now)          # 새 탐지가 있으면 클립 녹화 시작 (tracking_cam.id == channel_cid — frame_buffer/pending_clips 키가 push/append와 일치해야 함)
                append_pending_clips(channel_cid, clip_frame, now)             # 대기 중인 클립에 이번 프레임 추가
            else:
                # 탐지 없는 순수 미리보기 채널 — 박스/클립 녹화 없이 원본 프레임만 표시합니다.
                annotated = pil_img

            ss[key("result", cid)] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            time.sleep(0.005)

        # 백그라운드에서 완성된 클립이 있으면(플래그 변화 감지) 다음 반복에서 화면을 갱신
        if detect and ss.get("_clip_ready_flag", 0) != ss.get("_clip_seen_flag", 0):
            ss["_clip_seen_flag"] = ss.get("_clip_ready_flag", 0)
            need_ui_refresh = True

        # st.rerun()은 여기서 호출하지 않습니다 — 그 자리에서 스크립트를 즉시
        # 중단시켜 app.py가 아직 호출하지 않은 다른 채널의 run_playback_loop를
        # 영영 건너뛰게 만들기 때문입니다(위 docstring 참고). 대신 while
        # 루프만 즉시 빠져나와 함수가 정상적으로 반환되게 하고, 실제 rerun은
        # app.py가 양쪽 채널을 모두 호출한 뒤 한 번만 수행합니다.
        if need_ui_refresh or frames_processed == 0:
            break
