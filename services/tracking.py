"""services/tracking.py — 프레임 단위 탐지 결과를 트래킹해 로그/알람으로 연결합니다."""
import time

import streamlit as st
from PIL import Image

from config import PERSON_GAP_TOLERANCE, ANIMAL_TOAST_COOLDOWN, FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH
from services.detection import run_detection, draw_boxes, is_person
from services.audio_alert import play_alert_sound
from services.alerts import create_detection_alert, update_detection_alert


def process_frame(cam: dict, image: Image.Image, source: str, single: bool, timestamp_ms: float = 0.0):
    """이미지/영상 프레임 1장을 분석하고 트래킹 상태를 갱신해 신규/갱신 알람을 처리합니다.

    Returns:
        tuple: (탐지 결과 리스트, 신규 알람 발생 여부, 이번에 새로 생성된 로그 ID 목록)
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

    new_alert_ids: list[int] = []

    if single:
        annotated = draw_boxes(image, dets)

        for person in persons:
            aid = create_detection_alert(sname, person["class_name"],
                                         person["confidence"],
                                         1, source, annotated, True,
                                         box=person["box"],
                                         timestamp_ms=timestamp_ms,
                                         latency_ms=latency_ms,
                                         conf_thresh=conf_thresh,
                                         nms_thresh=nms_thresh)
            new_alert_ids.append(aid)
            play_alert_sound()
        if persons:
            is_new_alert = True

    else:
        # 사람 트랙: {인덱스: {"id", "gap", "max", "frames"}}
        tracks = s.setdefault(f"person_tracks_{cid}", {})

        if persons:
            annotated = draw_boxes(image, dets)

            for i, person in enumerate(persons):
                pconf = person["confidence"]

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
                    play_alert_sound()
                else:
                    tracks[i]["gap"] = 0
                    tracks[i]["frames"] += 1
                    if pconf > tracks[i]["max"]:
                        tracks[i]["max"] = pconf
                        update_detection_alert(tracks[i]["id"], pconf, tracks[i]["frames"], annotated)
                    else:
                        update_detection_alert(tracks[i]["id"], tracks[i]["max"], tracks[i]["frames"], None)

            for i in list(tracks.keys()):
                if i >= len(persons):
                    tracks[i]["gap"] += 1
                    if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                        del tracks[i]

        elif tracks:
            for i in list(tracks.keys()):
                tracks[i]["gap"] += 1
                if tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del tracks[i]

        s[f"person_tracks_{cid}"] = tracks

    # 동물 탐지: 경보 패널 없이 토스트 + 로그만 기록
    now = time.time()
    last_toasts = s.setdefault(f"last_toasts_{cid}", {})
    toasted_classes = set()
    animals_list = [d for d in dets if not is_person(d["class_name"])]

    animal_tracks = s.setdefault(f"animal_tracks_{cid}", {})
    by_class: dict[str, list[dict]] = {}
    for det in animals_list:
        by_class.setdefault(det["class_name"], []).append(det)

    for cls_name, items in by_class.items():
        cls_tracks = animal_tracks.setdefault(cls_name, {})

        if now - last_toasts.get(cls_name, 0) > ANIMAL_TOAST_COOLDOWN and cls_name not in toasted_classes:
            st.toast(f"{cls_name} 탐지 — {sname}", icon="🐾")
            last_toasts[cls_name] = now
            toasted_classes.add(cls_name)

        if annotated is None:
            annotated = draw_boxes(image, dets)

        for i, det in enumerate(items):
            conf = det["confidence"]
            if i not in cls_tracks:
                aid = create_detection_alert(sname, cls_name, conf, 1, source, annotated, False,
                                             box=det["box"],
                                             timestamp_ms=timestamp_ms,
                                             latency_ms=latency_ms,
                                             conf_thresh=conf_thresh,
                                             nms_thresh=nms_thresh)
                cls_tracks[i] = {"id": aid, "gap": 0, "max": conf, "frames": 1}
                new_alert_ids.append(aid)
            else:
                cls_tracks[i]["gap"] = 0
                cls_tracks[i]["frames"] += 1
                if conf > cls_tracks[i]["max"]:
                    cls_tracks[i]["max"] = conf
                    update_detection_alert(cls_tracks[i]["id"], conf, cls_tracks[i]["frames"], annotated)
                else:
                    update_detection_alert(cls_tracks[i]["id"], cls_tracks[i]["max"], cls_tracks[i]["frames"], None)

        for i in list(cls_tracks.keys()):
            if i >= len(items):
                cls_tracks[i]["gap"] += 1
                if cls_tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del cls_tracks[i]

    for cls_name in list(animal_tracks.keys()):
        if cls_name not in by_class:
            for i in list(animal_tracks[cls_name].keys()):
                animal_tracks[cls_name][i]["gap"] += 1
                if animal_tracks[cls_name][i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del animal_tracks[cls_name][i]

    return dets, is_new_alert, new_alert_ids
