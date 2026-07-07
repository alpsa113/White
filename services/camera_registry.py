"""
services/camera_registry.py — 대시보드에 표시할 카메라 목록의 순서/개수/정리 관리

화면 렌더링 로직이 아니라, "지금 어떤 카메라를 몇 개, 어떤 순서로 보여줘야
하는지"를 결정하는 순수 상태 관리 계층입니다. views/dashboard.py는 이 모듈의
함수만 호출해서 최종 카메라 목록을 얻습니다.
"""
import math

import streamlit as st

from config import build_camera_list, MAX_CAMERAS
from services.playback import reset_cam_state


def get_active_cameras() -> list[dict]:
    """session_state.grid_count에 맞춰 카메라 목록을 만들고, 저장된 표시 순서를
    적용한 뒤, 그리드 축소로 사라진 카메라의 리소스를 정리하고, 최종 목록을 반환합니다."""
    ss = st.session_state
    total = max(1, min(ss.get("grid_count", 4), MAX_CAMERAS))
    cameras = build_camera_list(total)
    _cleanup_removed_cameras(cameras)
    return cameras


def _cleanup_removed_cameras(cameras: list[dict]) -> None:
    """그리드 축소 등으로 이번 목록에서 사라진 카메라의 업로드/재생 리소스를 정리합니다."""
    ss = st.session_state
    prev_ids = set(ss.get("_prev_camera_ids", []))
    curr_ids = {c["id"] for c in cameras}
    for cid in prev_ids - curr_ids:  # 예: 9칸 → 4칸으로 줄여 사라진 cam5~cam9만 골라 정리
        reset_cam_state(cid)
    ss["_prev_camera_ids"] = list(curr_ids)  # 다음 렌더에서 비교할 수 있도록 현재 목록을 저장해둠


def compute_grid_columns(total: int) -> int:
    """총 카메라 개수를 정사각형에 가깝게 배치할 열 수를 계산합니다 (예: 5개 → 3열, 9개 → 3x3)."""
    return math.ceil(math.sqrt(total))


def get_valid_area_options(cameras: list[dict]) -> list[str]:
    """구역 선택 드롭다운에 쓸 옵션 목록('전체 구역' + 카메라 이름들)을 만듭니다."""
    ss = st.session_state
    options = ["전체 구역"] + [c["name"] for c in cameras]
    if ss.get("selected_cam") not in options:
        # 그리드 축소로 집중 보기 중이던 카메라가 사라진 경우 — 무효한 선택값이 selectbox에
        # 남으면 에러가 나므로 안전하게 '전체 구역'으로 되돌림
        ss["selected_cam"] = "전체 구역"
    return options
