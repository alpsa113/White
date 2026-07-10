"""services/outposts.py — 초소(지도 마커) 관리 및 카메라 목록 변환. 화면 렌더링은 포함하지 않습니다."""
import streamlit as st

from config import PRESET_MAP_IMAGE_PATH


def _ensure_loaded() -> None:
    """세션에 초소 목록/id 카운터가 없으면 빈 상태로 초기화합니다."""
    ss = st.session_state
    ss.setdefault("outposts", [])
    ss.setdefault("_outpost_id_counter", 0)


def get_outposts() -> list[dict]:
    """현재 등록된 초소(마커) 목록을 반환합니다."""
    _ensure_loaded()
    return st.session_state["outposts"]


def get_map_image_bytes() -> bytes:
    """프리셋 지도 이미지 바이트를 반환합니다(최초 1회만 읽고 캐시)."""
    ss = st.session_state
    if ss.get("_outpost_map_image_bytes") is None:
        with open(PRESET_MAP_IMAGE_PATH, "rb") as f:
            ss["_outpost_map_image_bytes"] = f.read()
    return ss["_outpost_map_image_bytes"]


def add_marker(x_ratio: float, y_ratio: float) -> str:
    """지도 위 위치에 새 초소 마커를 추가하고 마커 id를 반환합니다."""
    ss = st.session_state
    _ensure_loaded()
    ss["_outpost_id_counter"] += 1
    marker_id = f"cam{ss['_outpost_id_counter']}"
    ss["outposts"].append({
        "id": marker_id,
        "x_ratio": x_ratio,
        "y_ratio": y_ratio,
        "info": "",
        "source": "",
        "video_eo_bytes": None, "video_eo_name": "",
        "video_tir_bytes": None, "video_tir_name": "",
    })
    return marker_id


def remove_marker(marker_id: str) -> None:
    """초소 마커 1개를 삭제하고, EO/TIR 재생 리소스와 선택 상태를 정리합니다."""
    from services.playback import reset_cam_state

    ss = st.session_state
    ss["outposts"] = [o for o in get_outposts() if o["id"] != marker_id]
    reset_cam_state(marker_id, state_suffix="_eo")
    reset_cam_state(marker_id, state_suffix="_tir")

    selected = set(ss.get("_map_selected_cam_ids", []))
    if marker_id in selected:
        selected.discard(marker_id)
        ss["_map_selected_cam_ids"] = list(selected)


def update_marker(marker_id: str, *, info: str | None = None, source: str | None = None) -> None:
    """마커의 초소정보/영상소스 텍스트를 갱신합니다."""
    for o in get_outposts():
        if o["id"] == marker_id:
            if info is not None:
                o["info"] = info
            if source is not None:
                o["source"] = source
            break


def set_marker_video(marker_id: str, channel: str, data: bytes, filename: str) -> None:
    """초소에 CCTV 영상을 채널별(EO/TIR)로 매핑합니다. 현재 재생 중인 채널이면 즉시 재초기화합니다."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"

    for o in get_outposts():
        if o["id"] == marker_id:
            o[f"video_{channel}_bytes"] = data
            o[f"video_{channel}_name"] = filename
            active = st.session_state.get(f"active_channel_{marker_id}", "eo")
            if channel == active:
                from services.playback import reset_cam_state
                reset_cam_state(marker_id, state_suffix=f"_{channel}")
            break


def get_marker_video(marker_id: str, channel: str) -> tuple[bytes, str] | None:
    """초소에 매핑된 채널별 영상(바이트, 파일명)을 반환합니다. 없으면 None."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"
    for o in get_outposts():
        if o["id"] == marker_id:
            data = o.get(f"video_{channel}_bytes")
            if data:
                return data, o.get(f"video_{channel}_name", "")
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
