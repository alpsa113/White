from __future__ import annotations

from dataclasses import dataclass


def _area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _iou(box_a: list[float], box_b: list[float]) -> float:
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = _area(box_a) + _area(box_b) - inter
    return inter / union if union > 0 else 0.0


def _smooth_box(
    previous: list[float],
    current: list[float],
    alpha: float,
) -> list[float]:
    return [
        alpha * curr + (1.0 - alpha) * prev
        for prev, curr in zip(previous, current)
    ]


@dataclass
class Track:
    track_id: int
    class_id: int
    class_name: str
    bbox: list[float]
    score: float
    hits: int = 1
    missing_frames: int = 0


class SimpleByteTracker:
    """DualYOLO detection dict에 맞춘 최소 ByteTrack-style IoU tracker.

    낮은 confidence detection은 새 track을 만들지 않고 기존 track 복구에만 사용한다.
    """

    def __init__(
        self,
        track_high_thresh: float = 0.25,
        track_low_thresh: float = 0.10,
        match_thresh: float = 0.35,
        track_buffer: int = 8,
        smooth_alpha: float = 0.7,
        min_area_ratio: float = 0.4,
        max_area_ratio: float = 2.5,
        min_hits: int = 1,
    ):
        if not 0.0 <= track_low_thresh <= track_high_thresh <= 1.0:
            raise ValueError("track threshold는 0 <= low <= high <= 1 범위여야 합니다.")
        if not 0.0 <= match_thresh <= 1.0:
            raise ValueError("match_thresh는 0~1 범위여야 합니다.")
        if track_buffer < 0:
            raise ValueError("track_buffer는 0 이상이어야 합니다.")
        if not 0.0 <= smooth_alpha <= 1.0:
            raise ValueError("smooth_alpha는 0~1 범위여야 합니다.")
        if min_area_ratio <= 0 or max_area_ratio < min_area_ratio:
            raise ValueError("area ratio 범위가 올바르지 않습니다.")
        if min_hits < 1:
            raise ValueError("min_hits는 1 이상이어야 합니다.")

        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.match_thresh = match_thresh
        self.track_buffer = track_buffer
        self.smooth_alpha = smooth_alpha
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.min_hits = min_hits
        self.tracks: list[Track] = []
        self._next_track_id = 1

    def update(self, detections: list[dict]) -> list[dict]:
        high = [
            det for det in detections
            if float(det["score"]) >= self.track_high_thresh
        ]
        low = [
            det for det in detections
            if self.track_low_thresh <= float(det["score"]) < self.track_high_thresh
        ]

        matched_tracks: set[int] = set()
        matched_high: set[int] = set()
        self._match_detections(high, matched_tracks, matched_high)

        matched_low: set[int] = set()
        self._match_detections(
            low,
            matched_tracks,
            matched_low,
        )

        kept_tracks: list[Track] = []
        for idx, track in enumerate(self.tracks):
            if idx not in matched_tracks:
                track.missing_frames += 1
            if track.missing_frames <= self.track_buffer:
                kept_tracks.append(track)
        self.tracks = kept_tracks

        for idx, det in enumerate(high):
            if idx not in matched_high:
                self._start_track(det)

        return [self._track_to_detection(track) for track in self.tracks if track.hits >= self.min_hits]

    def _match_detections(
        self,
        detections: list[dict],
        matched_tracks: set[int],
        matched_detections: set[int],
    ):
        candidates: list[tuple[float, int, int]] = []
        for track_idx, track in enumerate(self.tracks):
            if track_idx in matched_tracks:
                continue
            for det_idx, det in enumerate(detections):
                if det_idx in matched_detections:
                    continue
                iou = _iou(track.bbox, det["bbox"])
                if iou >= self.match_thresh:
                    candidates.append((iou, track_idx, det_idx))

        candidates.sort(reverse=True, key=lambda item: item[0])
        for _, track_idx, det_idx in candidates:
            if track_idx in matched_tracks or det_idx in matched_detections:
                continue
            self._update_track(self.tracks[track_idx], detections[det_idx])
            matched_tracks.add(track_idx)
            matched_detections.add(det_idx)

    def _start_track(self, det: dict):
        self.tracks.append(
            Track(
                track_id=self._next_track_id,
                class_id=int(det["class_id"]),
                class_name=str(det["class_name"]),
                bbox=[float(v) for v in det["bbox"]],
                score=float(det["score"]),
            )
        )
        self._next_track_id += 1

    def _update_track(self, track: Track, det: dict):
        current_box = [float(v) for v in det["bbox"]]
        previous_area = _area(track.bbox)
        current_area = _area(current_box)
        if previous_area > 0 and current_area > 0:
            ratio = current_area / previous_area
            if ratio < self.min_area_ratio or ratio > self.max_area_ratio:
                current_box = track.bbox

        track.bbox = _smooth_box(track.bbox, current_box, self.smooth_alpha)
        track.class_id = int(det["class_id"])
        track.class_name = str(det["class_name"])
        track.score = float(det["score"])
        track.hits += 1
        track.missing_frames = 0

    @staticmethod
    def _track_to_detection(track: Track) -> dict:
        return {
            "class_id": track.class_id,
            "class_name": track.class_name,
            "score": round(track.score, 5),
            "bbox": [round(float(v), 2) for v in track.bbox],
            "track_id": track.track_id,
            "missing_frames": track.missing_frames,
            "hits": track.hits,
        }
