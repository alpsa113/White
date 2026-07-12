"""services/outposts.py — 초소(지도 마커) 관리 및 카메라 목록 변환. FastAPI 상태(state_store) 기반."""
import os
import uuid

import state_store as store
from config import PRESET_MAP_IMAGE_PATH, DEMO_VIDEOS
from services import video_analyzer

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "outpost_videos")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def clear_uploads() -> None:
    """업로드 디렉터리를 비웁니다(초소 목록은 인메모리라 재시작 시 어차피 참조가 끊기므로)."""
    for name in os.listdir(UPLOAD_DIR):
        _remove_file(os.path.join(UPLOAD_DIR, name))


def get_outposts() -> list[dict]:
    """현재 등록된 초소(마커) 목록을 반환합니다."""
    return store.outposts


def get_map_image_bytes() -> bytes:
    """프리셋 지도 이미지 바이트를 반환합니다."""
    with open(PRESET_MAP_IMAGE_PATH, "rb") as f:
        return f.read()


def add_marker(x_ratio: float, y_ratio: float) -> dict:
    """지도 위 클릭 좌표에 새 초소 마커를 추가합니다. config.DEMO_VIDEOS가 설정돼 있으면
    찍는 순서대로 그 목록의 영상을 자동 배정합니다(업로드 없이 로컬 경로만 참조)."""
    marker_id = store.next_outpost_id()
    marker = {
        "id": marker_id,
        "x_ratio": x_ratio,
        "y_ratio": y_ratio,
        "info": "",
        "source": "",
        "video_eo_path": None, "video_eo_name": "", "video_eo_seeded": False,
        "video_tir_path": None, "video_tir_name": "", "video_tir_seeded": False,
        "active_channel": "eo",
    }
    _apply_next_demo_video(marker)
    store.outposts.append(marker)
    return marker


def _apply_next_demo_video(marker: dict) -> None:
    """DEMO_VIDEOS에서 현재 마커 개수(=이 마커의 순번)에 해당하는 항목을 붙입니다. 별도 커서 없이
    실제 마커 개수로 계산하므로, 마커를 지웠다가 다시 찍어도 처음 순번부터 재배정됩니다."""
    index = len(store.outposts)
    if index >= len(DEMO_VIDEOS):
        return
    entry = DEMO_VIDEOS[index]
    marker["info"] = entry.get("info", "")
    marker["source"] = entry.get("source", "")
    for channel, key in (("eo", "eo_path"), ("tir", "tir_path")):
        path = entry.get(key)
        if not path:
            continue
        if not os.path.isfile(path):
            print(f"[demo-video] 영상 파일을 찾을 수 없어 건너뜁니다: {path}")
            continue
        marker[f"video_{channel}_path"] = path
        marker[f"video_{channel}_name"] = os.path.basename(path)
        marker[f"video_{channel}_seeded"] = True


def remove_marker(marker_id: str) -> None:
    """초소 마커를 삭제하고 재생 페이서를 정리합니다. seed된(DEMO_VIDEOS 원본) 영상 파일은
    앱이 소유한 게 아니므로 지우지 않습니다."""
    target = next((o for o in store.outposts if o["id"] == marker_id), None)
    store.outposts[:] = [o for o in store.outposts if o["id"] != marker_id]
    video_analyzer.stop_analysis(marker_id, "eo")
    video_analyzer.stop_analysis(marker_id, "tir")
    if target:
        for ch in ("eo", "tir"):
            if not target.get(f"video_{ch}_seeded"):
                _remove_file(target.get(f"video_{ch}_path"))


def update_marker(marker_id: str, *, info: str | None = None, source: str | None = None) -> dict | None:
    """마커의 초소정보/영상소스 텍스트를 갱신합니다."""
    for o in store.outposts:
        if o["id"] == marker_id:
            if info is not None:
                o["info"] = info
            if source is not None:
                o["source"] = source
            return o
    return None


def _remove_file(path: str | None) -> None:
    if path:
        try:
            os.remove(path)
        except Exception:
            pass


def set_marker_video(marker_id: str, channel: str, data: bytes, filename: str) -> dict | None:
    """초소에 CCTV 영상을 채널별(EO/TIR)로 업로드해 매핑합니다. 기존 경로가 seed 파일이면
    지우지 않고, 이후로는 일반 업로드 파일로 취급합니다."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4"
    new_path = os.path.join(UPLOAD_DIR, f"{marker_id}_{channel}_{uuid.uuid4().hex[:8]}.{ext}")
    with open(new_path, "wb") as f:
        f.write(data)

    for o in store.outposts:
        if o["id"] == marker_id:
            video_analyzer.stop_analysis(marker_id, channel)
            if not o.get(f"video_{channel}_seeded"):
                _remove_file(o.get(f"video_{channel}_path"))
            o[f"video_{channel}_path"] = new_path
            o[f"video_{channel}_name"] = filename
            o[f"video_{channel}_seeded"] = False
            return o
    _remove_file(new_path)
    return None


def get_marker_video(marker_id: str, channel: str) -> tuple[str, str] | None:
    """초소에 매핑된 채널별 영상(파일 경로, 파일명)을 반환합니다. 없으면 None."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"
    for o in store.outposts:
        if o["id"] == marker_id:
            path = o.get(f"video_{channel}_path")
            if path:
                return path, o.get(f"video_{channel}_name", "")
    return None


def cctv_no(idx: int) -> str:
    """표시 순서(0-based)를 "CCTV1", "CCTV2" ... 형태로 변환합니다."""
    return f"CCTV{idx + 1}"


def to_camera_list(outposts: list[dict] | None = None) -> list[dict]:
    """초소 마커 목록을 {"id", "name"} 카메라 딕셔너리 리스트로 변환합니다."""
    outposts = get_outposts() if outposts is None else outposts
    cameras = []
    for i, o in enumerate(outposts):
        no = cctv_no(i)
        info = (o.get("info") or "").strip()
        name = f"{no} ({info})" if info else no
        cameras.append({"id": o["id"], "name": name})
    return cameras
