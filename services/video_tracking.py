"""
services/video_tracking.py — 영상 프레임 처리/트래킹 및 실시간 재생 루프

process_frame(): 단일 이미지 또는 영상 프레임 1장을 분석하고, 사람 객체의
연속 등장/사라짐(트래킹) 상태를 계산하여 신규 알람 생성/갱신을 결정합니다.
run_playback_loop(): 여러 카메라의 영상을 번갈아 읽어 화면에 그리는 메인 루프입니다.
reset_cam_state(): 카메라 채널의 업로드/재생 상태를 완전 초기화합니다.
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

from config import (
    PERSON_GAP_TOLERANCE, ANIMAL_TOAST_COOLDOWN, DETECT_INTERVAL,
    FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH,
)
from services.detection import run_detection, draw_boxes, is_person
from services.alerts import create_detection_alert, update_detection_alert


def reset_cam_state(cid: str):
    """새로운 영상이 업로드되거나 비우기 버튼을 눌렀을 때 해당 CCTV 채널의 메모리 및 상태를 완전 초기화합니다."""
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
              "result", "person_tracks", "animals_visible", "last_dets", "last_toasts", "fp"):
        st.session_state.pop(f"{k}_{cid}", None)


def process_frame(cam: dict, image: Image.Image, source: str, single: bool, timestamp_ms: float = 0.0):
    """
    단일 이미지나 영상 프레임을 분석하고, 연속 등장/사라짐(트래킹) 상태를 계산하여 적절한 알림 액션을 취합니다.
    """
    cid = cam["id"]
    sname = cam["name"]
    s = st.session_state

    t0 = time.time()
    try:
        dets, conf_thresh, nms_thresh = run_detection(image)
    except Exception:
        dets, conf_thresh, nms_thresh = [], FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH

    latency_ms = round((time.time() - t0) * 1000, 3)
    persons = [d for d in dets if is_person(d["class_name"])]
    is_new_alert = False
    annotated = None

    # 단순 이미지 처리 로직
    if single:
        annotated = draw_boxes(image, dets)

        # 탐지된 모든 사람 루프 처리, box 전달
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

        # 개체 단위 list로 순회 → 같은 클래스 다수 객체 각각 로그
        for animal_det in [d for d in dets if not is_person(d["class_name"])]:
            create_detection_alert(sname, animal_det["class_name"], animal_det["confidence"],
                                   1, source, annotated, False,
                                   box=animal_det["box"],
                                   timestamp_ms=timestamp_ms,
                                   latency_ms=latency_ms,
                                   conf_thresh=conf_thresh,
                                   nms_thresh=nms_thresh)

    # 영상 스트리밍 처리 로직 (프레임 간 지속성 판단)
    else:
        # 인덱스별 tracks 딕셔너리
        tracks = s.setdefault(f"person_tracks_{cid}", {})

        if persons:
            annotated = draw_boxes(image, dets)

            for i, person in enumerate(persons):
                pconf = person["confidence"]

                # 케이스 1: i번 사람이 최초 등장 → 신규 알림 등록
                if i not in tracks:
                    aid = create_detection_alert(sname, person["class_name"],
                                                 pconf, 1, source, annotated, True,
                                                 box=person["box"],
                                                 timestamp_ms=timestamp_ms,
                                                 latency_ms=latency_ms,
                                                 conf_thresh=conf_thresh,
                                                 nms_thresh=nms_thresh)
                    tracks[i] = {"id": aid, "gap": 0, "max": pconf, "frames": 1}
                    is_new_alert = True

                # 케이스 2: i번 사람이 계속 탐지됨 → 기존 로그 갱신
                else:
                    tracks[i]["gap"] = 0
                    tracks[i]["frames"] += 1
                    if pconf > tracks[i]["max"]:
                        tracks[i]["max"] = pconf
                        update_detection_alert(tracks[i]["id"], pconf, tracks[i]["frames"], annotated)
                    else:
                        update_detection_alert(tracks[i]["id"], tracks[i]["max"], tracks[i]["frames"], None)

            # 케이스 3: 이번 프레임에서 사라진 인덱스 → gap 증가 또는 추적 종료
            for i in list(tracks.keys()):
                if i >= len(persons):
                    tracks[i]["gap"] += 1
                    if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                        del tracks[i]

        # 케이스 4: 프레임에 사람이 아무도 없음 → 모든 트랙 gap 증가
        elif tracks:
            for i in list(tracks.keys()):
                tracks[i]["gap"] += 1
                if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del tracks[i]

        s[f"person_tracks_{cid}"] = tracks

    # 동물 탐지는 알림 패널에 띄우지 않고 토스트(Toast) 메시지로만 알리며 쿨다운을 적용합니다.
    # 개체 단위 list로 순회하여 같은 클래스 여러 객체를 각각 로그에 저장합니다.
    # 토스트(알림음)는 클래스당 1번만 울리도록 toasted_classes로 중복을 제어합니다.
    now = time.time()
    last_toasts = s.setdefault(f"last_toasts_{cid}", {})
    toasted_classes = set()
    animals_list = [d for d in dets if not is_person(d["class_name"])]

    for animal_det in animals_list:
        animal = animal_det["class_name"]
        if now - last_toasts.get(animal, 0) > ANIMAL_TOAST_COOLDOWN:
            # 토스트는 같은 클래스에서 1번만 표시
            if animal not in toasted_classes:
                st.toast(f"{animal} 탐지 — {sname}", icon="🐾")
                last_toasts[animal] = now
                toasted_classes.add(animal)

            if annotated is None:
                annotated = draw_boxes(image, dets)
            # 로그는 탐지된 개체마다 각각 생성
            create_detection_alert(sname, animal, animal_det["confidence"],
                                   1, source, annotated, False,
                                   box=animal_det["box"],
                                   timestamp_ms=timestamp_ms,
                                   latency_ms=latency_ms,
                                   conf_thresh=conf_thresh,
                                   nms_thresh=nms_thresh)

    return dets, is_new_alert


def run_playback_loop(active_cams: list[dict], video_slots: dict, progress_slots: dict) -> None:
    """
    활성화된 여러 카메라 피드의 프레임을 번갈아 처리하며 화면을 그리는 메인 재생 루프입니다.
    새로운 알림 이벤트가 생긴 경우에만 전체 페이지 강제 새로고침 (우측 패널 업데이트 용도).
    """
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

            ts_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            ret, frame = cap.read()
            if not ret:
                ss[f"playing_{cid}"] = False
                ss[f"finished_{cid}"] = True
                continue

            frames_processed += 1
            cursor = ss.get(f"cursor_{cid}", 0)
            ss[f"cursor_{cid}"] = cursor + 1

            # 영상 해상도 규격 최적화 (UI 깨짐 방지)
            height, width = frame.shape[:2]
            if width > 1080:
                height = int(height * 1080 / width)
                frame = cv2.resize(frame, (1080, height))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            # 최적화 핵심: 설정된 DETECT_INTERVAL 주기마다 한 번만 추론하고, 평소엔 이전 박스 재사용
            if cursor % DETECT_INTERVAL == 0:
                dets, is_new_alert = process_frame(cam, pil_img, "영상", single=False, timestamp_ms=ts_ms)
                ss[f"last_dets_{cid}"] = dets
                if is_new_alert:
                    need_ui_refresh = True
            else:
                dets = ss.get(f"last_dets_{cid}", [])

            # 비디오 슬롯에 처리된 이미지 바로 덮어쓰기
            annotated = draw_boxes(pil_img, dets)
            ss[f"result_{cid}"] = annotated
            if cid in video_slots:
                video_slots[cid].image(annotated, use_container_width=True)

            total = ss.get(f"total_frames_{cid}", 0)
            if cid in progress_slots and total > 0 and cursor % 10 == 0:
                progress_slots[cid].progress(min(cursor / total, 1.0), text=f"실시간 분석 중 {cursor}/{total} 프레임")

            # CPU 점유를 완화하여 스레드가 멈추는 것을 방지
            time.sleep(0.005)

        if need_ui_refresh:
            st.rerun()

        if frames_processed == 0:
            break

    st.rerun()
