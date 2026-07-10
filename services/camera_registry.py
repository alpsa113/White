"""services/camera_registry.py — 대시보드에 표시할 카메라 목록의 순서/개수/정리를 관리합니다."""
import math

import streamlit as st

from config import build_camera_list
from services.playback import reset_cam_state, start_camera_media
from services.outposts import get_outposts, to_camera_list


def get_active_cameras() -> list[dict]:
    """설정 페이지에서 찍은 초소 목록을 카메라 목록으로 변환해 반환합니다."""
    outposts = get_outposts()
    cameras = to_camera_list(outposts) if outposts else build_camera_list(1)
    _cleanup_removed_cameras(cameras)
    _sync_preset_media(outposts, cameras)
    return cameras


def _sync_preset_media(outposts: list[dict], cameras: list[dict]) -> None:
    """매핑된 영상을 각 카메라의 현재 선택 채널에 자동 반영합니다(이미 반영된 채널은 건너뜀)."""
    ss = st.session_state
    cam_by_id = {c["id"]: c for c in cameras}
    for o in outposts:
        cid = o["id"]
        cam = cam_by_id.get(cid)
        if not cam:
            continue
        channel = ss.get(f"active_channel_{cid}", "eo")
        if ss.get(f"fp_{cid}_{channel}") is not None:
            continue
        data = o.get(f"video_{channel}_bytes")
        if not data:
            continue
        start_camera_media(cam, data, o.get(f"video_{channel}_name") or "preset",
                            state_suffix=f"_{channel}")


def _cleanup_removed_cameras(cameras: list[dict]) -> None:
    """이번 목록에서 사라진 카메라의 EO/TIR 재생 리소스를 정리합니다."""
    ss = st.session_state
    prev_ids = set(ss.get("_prev_camera_ids", []))
    curr_ids = {c["id"] for c in cameras}
    for cid in prev_ids - curr_ids:
        reset_cam_state(cid, state_suffix="_eo")
        reset_cam_state(cid, state_suffix="_tir")
    ss["_prev_camera_ids"] = list(curr_ids)


def compute_grid_columns(total: int) -> int:
    """총 카메라 개수를 정사각형에 가깝게 배치할 열 수를 계산합니다."""
    return math.ceil(math.sqrt(total))


def get_valid_area_options(cameras: list[dict]) -> list[str]:
    """구역 선택 옵션 목록을 만들고, 선택값이 무효해지면 '전체 구역'으로 되돌립니다."""
    ss = st.session_state
    options = ["전체 구역"] + [c["name"] for c in cameras]
    if ss.get("selected_cam") not in options:
        ss["selected_cam"] = "전체 구역"
    return options
