"""
services/video_tracking.py — 영상 프레임 처리/트래킹 및 실시간 재생 루프

process_frame(): 단일 이미지 또는 영상 프레임 1장을 분석하고, 사람 객체의
연속 등장/사라짐(트래킹) 상태를 계산하여 신규 알람 생성/갱신을 결정합니다.
run_playback_loop(): 여러 카메라의 영상을 번갈아 읽어 화면에 그리는 메인 루프입니다.
reset_cam_state(): 카메라 채널의 업로드/재생 상태와 관련 리소스를 완전 정리합니다.
"""
import os
import time

import streamlit as st
from PIL import Image

# opencv-python이 설치되어 있지 않은 환경에서도 이미지 업로드 기능은 동작하도록 방어적으로 import
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from config import (
    PERSON_GAP_TOLERANCE, ANIMAL_TOAST_COOLDOWN, DETECT_INTERVAL,
    FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH,
)
from services.detection import run_detection, draw_boxes, is_person
from services.alerts import create_detection_alert, update_detection_alert


def reset_cam_state(cid: str):
    """새로운 영상이 업로드되거나 '비우기' 버튼을 눌렀을 때, 또는 그리드 축소로
    해당 카메라 슬롯이 사라졌을 때 호출됩니다. cv2.VideoCapture 핸들 해제, 임시파일
    삭제, 관련 session_state 키 전체 삭제까지 한 번에 처리하여 리소스 누수를 막습니다."""
    # 열려 있는 VideoCapture가 있으면 먼저 해제 (안 하면 파일 핸들이 계속 점유됨)
    if f"cap_{cid}" in st.session_state:
        cap = st.session_state[f"cap_{cid}"]
        if cap is not None:
            cap.release()

    # 업로드된 영상을 저장해둔 임시파일 삭제
    if f"tmp_path_{cid}" in st.session_state:
        try:
            os.remove(st.session_state[f"tmp_path_{cid}"])
        except Exception:
            pass

    # 이 카메라와 관련된 모든 session_state 키를 일괄 제거
    for k in ("cap", "tmp_path", "cursor", "total_frames", "playing", "finished",
              "result", "person_tracks", "animals_visible", "last_dets", "last_toasts", "fp"):
        st.session_state.pop(f"{k}_{cid}", None)


def process_frame(cam: dict, image: Image.Image, source: str, single: bool, timestamp_ms: float = 0.0):
    """단일 이미지나 영상 프레임 1장을 분석하고, 연속 등장/사라짐(트래킹) 상태를 계산하여
    적절한 알림 액션(신규 알람 생성 / 기존 알람 갱신 / 동물 토스트)을 수행합니다.

    Returns:
        tuple: (탐지 결과 리스트, 이번 프레임에서 신규 알람이 발생했는지 여부)
    """
    cid = cam["id"]
    sname = cam["name"]
    s = st.session_state

    # 추론 소요 시간(latency)을 측정하여 로그에 함께 기록 (성능 모니터링용)
    t0 = time.time()
    try:
        dets, conf_thresh, nms_thresh = run_detection(image)
    except Exception:
        # 백엔드 호출 실패 시에도 화면이 멈추지 않도록 빈 결과로 대체
        dets, conf_thresh, nms_thresh = [], FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH

    latency_ms = round((time.time() - t0) * 1000, 3)
    persons = [d for d in dets if is_person(d["class_name"])]
    is_new_alert = False
    annotated = None

    # ── 단일 이미지 처리: 트래킹 없이 탐지된 모든 객체를 즉시 로그에 기록 ──
    if single:
        annotated = draw_boxes(image, dets)

        for person in persons:
            create_detection_alert(sname, person["class_name"],
                                   person["confidence"],
                                   1, source, annotated, True,
                                   box=person["box"],
                                   timestamp_ms=timestamp_ms,
                                   latency_ms=latency_ms,
                                   conf_thresh=conf_thresh,
                                   nms_thresh=nms_thresh)
        if persons:
            is_new_alert = True

        # 개체 단위로 순회하여 같은 클래스가 여러 마리 탐지되어도 각각 별도 로그로 기록
        for animal_det in [d for d in dets if not is_person(d["class_name"])]:
            create_detection_alert(sname, animal_det["class_name"], animal_det["confidence"],
                                   1, source, annotated, False,
                                   box=animal_det["box"],
                                   timestamp_ms=timestamp_ms,
                                   latency_ms=latency_ms,
                                   conf_thresh=conf_thresh,
                                   nms_thresh=nms_thresh)

    # ── 영상 스트리밍 처리: 프레임 간 지속성을 추적하여 같은 사람에 대한 중복 알람을 방지 ──
    else:
        # 이 카메라의 사람 트랙 상태: {인덱스: {"id": 로그ID, "gap": 사라진 프레임 수, "max": 최고 신뢰도, "frames": 누적 프레임 수}}
        tracks = s.setdefault(f"person_tracks_{cid}", {})

        if persons:
            annotated = draw_boxes(image, dets)

            for i, person in enumerate(persons):
                pconf = person["confidence"]

                if i not in tracks:
                    # 케이스 1: 새로운 사람 등장 → 신규 알람 등록
                    aid = create_detection_alert(sname, person["class_name"],
                                                 pconf, 1, source, annotated, True,
                                                 box=person["box"],
                                                 timestamp_ms=timestamp_ms,
                                                 latency_ms=latency_ms,
                                                 conf_thresh=conf_thresh,
                                                 nms_thresh=nms_thresh)
                    tracks[i] = {"id": aid, "gap": 0, "max": pconf, "frames": 1}
                    is_new_alert = True

                else:
                    # 케이스 2: 이미 추적 중인 사람이 계속 탐지됨 → 기존 로그만 갱신 (신규 알람 없음)
                    tracks[i]["gap"] = 0
                    tracks[i]["frames"] += 1
                    if pconf > tracks[i]["max"]:
                        tracks[i]["max"] = pconf
                        update_detection_alert(tracks[i]["id"], pconf, tracks[i]["frames"], annotated)
                    else:
                        update_detection_alert(tracks[i]["id"], tracks[i]["max"], tracks[i]["frames"], None)

            # 케이스 3: 이번 프레임에서 사라진 트랙 → gap 증가, 허용치를 넘으면 추적 종료
            for i in list(tracks.keys()):
                if i >= len(persons):
                    tracks[i]["gap"] += 1
                    if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                        del tracks[i]

        elif tracks:
            # 케이스 4: 이번 프레임에 사람이 아무도 없음 → 모든 트랙의 gap 증가
            for i in list(tracks.keys()):
                tracks[i]["gap"] += 1
                if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del tracks[i]

        s[f"person_tracks_{cid}"] = tracks

    # ── 동물 탐지 처리: 경보 패널 없이 토스트 알림 + 로그만 기록, 쿨다운으로 도배 방지 ──
    now = time.time()
    last_toasts = s.setdefault(f"last_toasts_{cid}", {})
    toasted_classes = set()  # 이번 프레임에서 이미 토스트를 띄운 클래스 (같은 프레임 내 중복 토스트 방지)
    animals_list = [d for d in dets if not is_person(d["class_name"])]

    for animal_det in animals_list:
        animal = animal_det["class_name"]
        if now - last_toasts.get(animal, 0) > ANIMAL_TOAST_COOLDOWN:
            if animal not in toasted_classes:
                st.toast(f"{animal} 탐지 — {sname}", icon="🐾")
                last_toasts[animal] = now
                toasted_classes.add(animal)

            if annotated is None:
                annotated = draw_boxes(image, dets)
            # 로그는 토스트 여부와 무관하게 탐지된 개체마다 각각 생성
            create_detection_alert(sname, animal, animal_det["confidence"],
                                   1, source, annotated, False,
                                   box=animal_det["box"],
                                   timestamp_ms=timestamp_ms,
                                   latency_ms=latency_ms,
                                   conf_thresh=conf_thresh,
                                   nms_thresh=nms_thresh)

    return dets, is_new_alert


def run_playback_loop(active_cams: list[dict], video_slots: dict, progress_slots: dict) -> None:
    """활성화된(재생 중인) 여러 카메라 피드의 프레임을 번갈아 처리하며 화면을 갱신하는
    메인 재생 루프입니다. 새로운 알람이 발생했을 때만 전체 페이지를 rerun하여
    우측 경보 패널을 갱신합니다 (그 외에는 비디오 슬롯만 직접 갱신하여 오버헤드를 줄임)."""
    ss = st.session_state
    need_ui_refresh = False

    while True:
        frames_processed = 0

        for cam in active_cams:
            cid = cam["id"]
            if not ss.get(f"playing_{cid}"):
                continue

            cap = ss[f"cap_{cid}"]
            if cap is None or not cap.isOpened():
                ss[f"playing_{cid}"] = False
                continue

            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)  # DB 기록용 — 영상 내 실제 재생 시점(ms)
            ret, frame = cap.read()
            if not ret:
                # 더 읽을 프레임이 없으면 재생 종료 상태로 전환
                ss[f"playing_{cid}"] = False
                ss[f"finished_{cid}"] = True
                continue

            frames_processed += 1
            cursor = ss.get(f"cursor_{cid}", 0)
            ss[f"cursor_{cid}"] = cursor + 1

            # 화면 렌더링 성능을 위해 가로 해상도를 1080px로 제한 (원본 비율 유지)
            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # 성능 최적화 핵심: DETECT_INTERVAL 주기마다 한 번만 실제 추론하고,
            # 나머지 프레임은 직전 탐지 결과의 박스를 그대로 재사용
            if cursor % DETECT_INTERVAL == 0:
                dets, is_new_alert = process_frame(cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                ss[f"last_dets_{cid}"] = dets
                if is_new_alert:
                    need_ui_refresh = True
            else:
                dets = ss.get(f"last_dets_{cid}", [])

            # 처리된 프레임을 해당 카메라의 비디오 슬롯에 즉시 반영
            annotated = draw_boxes(pil_img, dets)
            ss[f"result_{cid}"] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            # 10프레임마다 한 번씩만 진행률 바 갱신 (매 프레임 갱신 시 불필요한 렌더링 부하 발생)
            total = ss.get(f"total_frames_{cid}", 0)
            if cid in progress_slots and total > 0 and cursor % 10 == 0:
                progress_slots[cid].progress(min(cursor / total, 1.0), text=f"실시간 분석 중 {cursor}/{total} 프레임")

            time.sleep(0.005)  # CPU 점유율을 완화하여 다른 스레드/상호작용이 밀리지 않도록 함

        # 신규 알람이 있었다면 경보 패널 갱신을 위해 전체 페이지 rerun
        if need_ui_refresh:
            st.rerun()

        # 이번 루프에서 처리된 프레임이 하나도 없으면(모든 영상 재생 종료) 루프 탈출
        if frames_processed == 0:
            break

    st.rerun()
