"""services/camera_registry.py — 초소 마커 목록을 카메라 목록으로 변환합니다."""
from config import build_camera_list
from services.outposts import get_outposts, to_camera_list


def get_active_cameras() -> list[dict]:
    """설정 페이지에서 찍은 초소 목록을 카메라 목록으로 변환해 반환합니다."""
    outposts = get_outposts()
    return to_camera_list(outposts) if outposts else build_camera_list(1)
