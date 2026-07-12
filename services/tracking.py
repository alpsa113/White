"""services/tracking.py — 프레임 단위 탐지 결과를 트래킹해 로그/알람으로 연결합니다."""
import time

from PIL import Image

from config import PERSON_GAP_TOLERANCE, ANIMAL_TOAST_COOLDOWN, FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH
from services.detection import run_detection, draw_boxes, is_person
from services.alerts import create_detection_alert, update_detection_alert

# 같은 개체로 인정할 최소 겹침(IoU) — 이 값으로 프레임 간 같은 개체를 이어 하나의 트랙으로 봅니다.
IOU_MATCH_THRESHOLD = 0.25

# 사람 트랙을 한 카테고리로 묶어 관리하는 내부 키(class_name 표기가 여러 개여도 is_person()으로 통합).
PERSON_PLAN_KEY = "__person__"


def _iou(box_a: dict, box_b: dict) -> float:
    """두 박스의 IoU(교집합/합집합 비율)를 계산합니다."""
    ix1 = max(box_a["x1"], box_b["x1"])
    iy1 = max(box_a["y1"], box_b["y1"])
    ix2 = min(box_a["x2"], box_b["x2"])
    iy2 = min(box_a["y2"], box_b["y2"])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, box_a["x2"] - box_a["x1"]) * max(0.0, box_a["y2"] - box_a["y1"])
    area_b = max(0.0, box_b["x2"] - box_b["x1"]) * max(0.0, box_b["y2"] - box_b["y1"])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _match_detections_to_tracks(dets: list[dict], tracks: dict) -> dict[int, object]:
    """이번 프레임 탐지 결과를 기존 트랙에 위치(IoU) 기준으로 매칭합니다.
    반환값: {이번 프레임 det 인덱스: 매칭된 트랙 key} (매칭 실패한 det는 포함 안 됨)"""
    track_items = [(key, t) for key, t in tracks.items() if "box" in t]
    used_keys: set = set()
    matches: dict[int, object] = {}

    for i, det in enumerate(dets):
        best_key, best_iou = None, IOU_MATCH_THRESHOLD
        for key, t in track_items:
            if key in used_keys:
                continue
            iou = _iou(det["box"], t["box"])
            if iou > best_iou:
                best_key, best_iou = key, iou
        if best_key is not None:
            matches[i] = best_key
            used_keys.add(best_key)

    return matches


def _next_track_key(cam_state: dict, counter_name: str):
    """카테고리별로 계속 증가하는 트랙 순번을 발급합니다. video_analyzer.py가 클립 계획에서
    같은 순번의 클립을 찾아 붙이는 데 이 값을 그대로 씁니다."""
    n = cam_state.get(counter_name, 0)
    cam_state[counter_name] = n + 1
    return n


def simulate_tracks_offline(timeline: list[dict]) -> dict[str, list[dict]]:
    """전체 타임라인을 미리 한 번 훑어 실시간 재생과 동일한 로직으로 트랙 경계(최초~마지막
    탐지 시각)를 계산합니다. DB/S3에 쓰지 않는 순수 시뮬레이션이며, video_analyzer.py가 클립을
    분석 단계에서 한 번만 만들어두는 데 씁니다.

    반환값: {카테고리(사람은 PERSON_PLAN_KEY, 동물은 class_name): [{"first_ts","last_ts"}, ...]}
    각 리스트는 트랙 생성 순서대로이며, process_frame()이 같은 카테고리에서 N번째로 만드는
    트랙은 항상 이 리스트의 N번째 항목과 대응합니다(같은 타임라인/알고리즘이라 결정론적)."""
    tracks_by_class: dict[str, dict] = {}
    plan: dict[str, list[dict]] = {}

    for entry in timeline:
        ts = entry["t"]
        persons = [d for d in entry["dets"] if is_person(d["class_name"])]
        animals = [d for d in entry["dets"] if not is_person(d["class_name"])]

        by_class: dict[str, list[dict]] = {}
        if persons:
            by_class[PERSON_PLAN_KEY] = persons
        for d in animals:
            by_class.setdefault(d["class_name"], []).append(d)

        for cls_name, items in by_class.items():
            tracks = tracks_by_class.setdefault(cls_name, {})
            matches = _match_detections_to_tracks(items, tracks)
            matched_keys = set(matches.values())

            for i, det in enumerate(items):
                key = matches.get(i)
                if key is None:
                    event = {"first_ts": ts, "last_ts": ts}
                    plan.setdefault(cls_name, []).append(event)
                    key = id(event)
                    tracks[key] = {"box": det["box"], "gap": 0, "event": event}
                    matched_keys.add(key)
                else:
                    t = tracks[key]
                    t["box"] = det["box"]
                    t["gap"] = 0
                    t["event"]["last_ts"] = ts

            for key in list(tracks.keys()):
                if key not in matched_keys:
                    tracks[key]["gap"] += 1
                    if tracks[key]["gap"] >= PERSON_GAP_TOLERANCE:
                        del tracks[key]

        for cls_name, tracks in tracks_by_class.items():
            if cls_name in by_class:
                continue
            for key in list(tracks.keys()):
                tracks[key]["gap"] += 1
                if tracks[key]["gap"] >= PERSON_GAP_TOLERANCE:
                    del tracks[key]

    return plan


def process_frame(cam: dict, image: Image.Image, source: str, cam_state: dict, timestamp_ms: float = 0.0,
                   precomputed_dets: list[dict] | None = None, precomputed_latency_ms: float = 0.0):
    """영상 프레임 1장을 분석하고 트래킹 상태를 갱신해 신규/갱신 알람을 처리합니다.

    precomputed_dets: 사전 분석(1단계)에서 이미 계산해둔 탐지 결과 — 있으면 모델을 다시
    호출하지 않고 트래킹/알림만 실제 영상 속도에 맞춰 흘려보냅니다. precomputed_latency_ms는
    그때 실측한 추론 시간으로, 안 넘기면 RDS의 latency_ms가 0으로 기록됩니다.

    Returns:
        tuple: (탐지 결과 리스트, 신규 알람 발생 여부, 이번에 새로 생성된 로그 ID 목록,
                새로 토스트할 클래스명 목록,
                이번에 새로 생성된 트랙 정보 [(로그 ID, 카테고리, 생성 순번), ...] —
                video_analyzer.py가 클립 계획에서 같은 순번의 클립을 찾아 붙이는 데 씀)
    """
    sname = cam["name"]

    if precomputed_dets is not None:
        dets, conf_thresh, nms_thresh = precomputed_dets, FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH
        latency_ms = precomputed_latency_ms
    else:
        try:
            dets, conf_thresh, nms_thresh, latency_ms = run_detection(image)
        except Exception:
            dets, conf_thresh, nms_thresh, latency_ms = [], FALLBACK_CONF_THRESH, FALLBACK_NMS_THRESH, 0.0

    persons = [d for d in dets if is_person(d["class_name"])]
    is_new_alert = False
    annotated = None

    new_alert_ids: list[int] = []
    new_toasts: list[str] = []
    new_track_infos: list[tuple[int, str, int]] = []

    tracks = cam_state.setdefault("person_tracks", {})

    if persons:
        annotated = draw_boxes(image, dets)
        matches = _match_detections_to_tracks(persons, tracks)
        matched_keys = set(matches.values())

        for i, person in enumerate(persons):
            pconf = person["confidence"]
            key = matches.get(i)

            if key is None:
                aid = create_detection_alert(sname, person["class_name"],
                                             pconf, 1, source, annotated, True,
                                             box=person["box"],
                                             timestamp_ms=timestamp_ms,
                                             latency_ms=latency_ms,
                                             conf_thresh=conf_thresh,
                                             nms_thresh=nms_thresh)
                new_key = _next_track_key(cam_state, "_person_track_counter")
                tracks[new_key] = {"id": aid, "gap": 0, "max": pconf, "frames": 1, "box": person["box"]}
                matched_keys.add(new_key)
                is_new_alert = True
                new_track_infos.append((aid, PERSON_PLAN_KEY, new_key))
            else:
                t = tracks[key]
                t["gap"] = 0
                t["frames"] += 1
                t["box"] = person["box"]
                if pconf > t["max"]:
                    t["max"] = pconf
                    update_detection_alert(t["id"], pconf, t["frames"], annotated)
                else:
                    update_detection_alert(t["id"], t["max"], t["frames"], None)

        for key in list(tracks.keys()):
            if key not in matched_keys:
                tracks[key]["gap"] += 1
                if tracks[key]["gap"] >= PERSON_GAP_TOLERANCE:
                    del tracks[key]

    elif tracks:
        for key in list(tracks.keys()):
            tracks[key]["gap"] += 1
            if tracks[key]["gap"] >= PERSON_GAP_TOLERANCE:
                del tracks[key]

    # 동물 탐지: 경보 패널 없이 토스트 + 로그만 기록
    now = time.time()
    last_toasts = cam_state.setdefault("last_toasts", {})
    toasted_classes = set()
    animals_list = [d for d in dets if not is_person(d["class_name"])]

    animal_tracks = cam_state.setdefault("animal_tracks", {})
    by_class: dict[str, list[dict]] = {}
    for det in animals_list:
        by_class.setdefault(det["class_name"], []).append(det)

    for cls_name, items in by_class.items():
        cls_tracks = animal_tracks.setdefault(cls_name, {})

        if now - last_toasts.get(cls_name, 0) > ANIMAL_TOAST_COOLDOWN and cls_name not in toasted_classes:
            new_toasts.append(cls_name)
            last_toasts[cls_name] = now
            toasted_classes.add(cls_name)

        if annotated is None:
            annotated = draw_boxes(image, dets)

        matches = _match_detections_to_tracks(items, cls_tracks)
        matched_keys = set(matches.values())

        for i, det in enumerate(items):
            conf = det["confidence"]
            key = matches.get(i)

            if key is None:
                aid = create_detection_alert(sname, cls_name, conf, 1, source, annotated, False,
                                             box=det["box"],
                                             timestamp_ms=timestamp_ms,
                                             latency_ms=latency_ms,
                                             conf_thresh=conf_thresh,
                                             nms_thresh=nms_thresh)
                new_key = _next_track_key(cam_state, f"_animal_track_counter_{cls_name}")
                cls_tracks[new_key] = {"id": aid, "gap": 0, "max": conf, "frames": 1, "box": det["box"]}
                matched_keys.add(new_key)
                new_alert_ids.append(aid)
                new_track_infos.append((aid, cls_name, new_key))
            else:
                t = cls_tracks[key]
                t["gap"] = 0
                t["frames"] += 1
                t["box"] = det["box"]
                if conf > t["max"]:
                    t["max"] = conf
                    update_detection_alert(t["id"], conf, t["frames"], annotated)
                else:
                    update_detection_alert(t["id"], t["max"], t["frames"], None)

        for key in list(cls_tracks.keys()):
            if key not in matched_keys:
                cls_tracks[key]["gap"] += 1
                if cls_tracks[key]["gap"] >= PERSON_GAP_TOLERANCE:
                    del cls_tracks[key]

    for cls_name in list(animal_tracks.keys()):
        if cls_name not in by_class:
            for key in list(animal_tracks[cls_name].keys()):
                animal_tracks[cls_name][key]["gap"] += 1
                if animal_tracks[cls_name][key]["gap"] >= PERSON_GAP_TOLERANCE:
                    del animal_tracks[cls_name][key]

    return dets, is_new_alert, new_alert_ids, new_toasts, new_track_infos
