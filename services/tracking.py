"""
services/tracking.py — 프레임 단위 객체 탐지 결과의 사람/동물 트래킹 로직

process_frame()이 이 파일의 유일한 공개 함수입니다. 단일 이미지든 영상
프레임이든 이 함수 하나로 처리하며, 영상 모드에서는 프레임 간 지속성(같은
대상이 계속 화면에 있는지)을 추적해 같은 대상에 대한 중복 알람을 방지합니다.

영상 재생 자체(파일 읽기, 진행 위치 계산 등)는 이 파일의 관심사가 아니며
services/playback.py가 담당합니다 — 이 파일은 "프레임 1장이 주어졌을 때
그 안의 탐지 결과를 어떻게 로그/알람으로 연결할지"만 책임집니다.
"""
import time

import streamlit as st
from PIL import Image
from collections import deque

from config import PERSON_GAP_TOLERANCE, ANIMAL_TOAST_COOLDOWN, FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH
from services.detection import run_detection, draw_boxes, is_person
from services.audio_alert import play_alert_sound
from services.alerts import create_detection_alert, update_detection_alert

RECENT_ALERTS_MAX = 5  # 상단 배너에 보관할 최근 사람 탐지 개수

def _record_recent_alert(aid: int) -> None:
    """최근 사람 탐지 ID를 최대 RECENT_ALERTS_MAX개까지 보관합니다.
    탐지 일시/카메라/클래스 등 상세 정보는 이미 ss.detection_logs에 있으므로
    여기서는 ID만 기록하고, 표시할 때 로그에서 그대로 조회해 씁니다."""
    ss = st.session_state
    recent = ss.setdefault("recent_person_alert_ids", deque(maxlen=RECENT_ALERTS_MAX))
    recent.append(aid)

def process_frame(cam: dict, image: Image.Image, source: str, single: bool, timestamp_ms: float = 0.0):
    """단일 이미지나 영상 프레임 1장을 분석하고, 연속 등장/사라짐(트래킹) 상태를 계산하여
    적절한 알림 액션(신규 알람 생성 / 기존 알람 갱신 / 동물 토스트)을 수행합니다.

    Returns:
        tuple: (탐지 결과 리스트, 이번 프레임에서 신규 알람이 발생했는지 여부,
                이번 호출에서 새로 생성된 로그 ID 목록 — 탐지 전후 클립 녹화 대상)
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

    new_alert_ids: list[int] = []  # 이번 호출에서 새로 생성된 로그 ID (클립 녹화 대상)

    # ── 단일 이미지 처리: 트래킹 없이 탐지된 모든 객체를 즉시 로그에 기록 ──
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
            _record_recent_alert(aid)
        if persons:
            is_new_alert = True

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
                    play_alert_sound()
                    _record_recent_alert(aid)
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

    # 클래스별로 인스턴스를 분리 추적합니다: {"멧돼지": {0: {...}, 1: {...}}, "고라니": {...}}
    # 같은 클래스 안에서만 프레임별 탐지 순서(인덱스)로 동일 개체를 매칭합니다 — 사람 추적과 동일한 방식.
    animal_tracks = s.setdefault(f"animal_tracks_{cid}", {})
    by_class: dict[str, list[dict]] = {}
    for det in animals_list:
        by_class.setdefault(det["class_name"], []).append(det)

    for cls_name, items in by_class.items():
        cls_tracks = animal_tracks.setdefault(cls_name, {})

        # 토스트는 여전히 클래스당 쿨다운 적용 (도배 방지) — 트래킹과는 독립적으로 유지
        if now - last_toasts.get(cls_name, 0) > ANIMAL_TOAST_COOLDOWN and cls_name not in toasted_classes:
            st.toast(f"{cls_name} 탐지 — {sname}", icon="🐾")
            last_toasts[cls_name] = now
            toasted_classes.add(cls_name)

        if annotated is None:
            annotated = draw_boxes(image, dets)

        for i, det in enumerate(items):
            conf = det["confidence"]
            if i not in cls_tracks:
                # 새로운 개체 등장 → 신규 로그 1건 생성
                aid = create_detection_alert(sname, cls_name, conf, 1, source, annotated, False,
                                             box=det["box"],
                                             timestamp_ms=timestamp_ms,
                                             latency_ms=latency_ms,
                                             conf_thresh=conf_thresh,
                                             nms_thresh=nms_thresh)
                cls_tracks[i] = {"id": aid, "gap": 0, "max": conf, "frames": 1}
                new_alert_ids.append(aid)
            else:
                # 이미 추적 중인 개체 → 새 로그 없이 기존 로그의 신뢰도/프레임 수만 갱신
                cls_tracks[i]["gap"] = 0
                cls_tracks[i]["frames"] += 1
                if conf > cls_tracks[i]["max"]:
                    cls_tracks[i]["max"] = conf
                    update_detection_alert(cls_tracks[i]["id"], conf, cls_tracks[i]["frames"], annotated)
                else:
                    update_detection_alert(cls_tracks[i]["id"], cls_tracks[i]["max"], cls_tracks[i]["frames"], None)

        # 이번 프레임에서 사라진 개체 → gap 증가, 허용치를 넘으면 추적 종료
        for i in list(cls_tracks.keys()):
            if i >= len(items):
                cls_tracks[i]["gap"] += 1
                if cls_tracks[i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del cls_tracks[i]

    # 이번 프레임에 아예 등장하지 않은 클래스 → 해당 클래스의 모든 트랙 gap 증가
    for cls_name in list(animal_tracks.keys()):
        if cls_name not in by_class:
            for i in list(animal_tracks[cls_name].keys()):
                animal_tracks[cls_name][i]["gap"] += 1
                if animal_tracks[cls_name][i]["gap"] >= PERSON_GAP_TOLERANCE:
                    del animal_tracks[cls_name][i]

    return dets, is_new_alert, new_alert_ids