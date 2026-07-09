"""
services/camera_registry.py — 대시보드에 표시할 카메라 목록의 순서/개수/정리 관리

화면 렌더링 로직이 아니라, "지금 어떤 카메라를 몇 개, 어떤 순서로 보여줘야
하는지"를 결정하는 순수 상태 관리 계층입니다. views/dashboard.py는 이 모듈의
함수만 호출해서 최종 카메라 목록을 얻습니다.
"""
import math

import streamlit as st

from config import build_camera_list
from services.playback import reset_cam_state, start_camera_media
from services.outposts import get_outposts, to_camera_list


def get_active_cameras() -> list[dict]:
    """설정 페이지에서 지도에 찍은 초소(services/outposts.py) 목록을 카메라
    목록으로 변환해 반환합니다. 관리자가 아직 초소를 하나도 찍지 않은 초기
    상태에서는 화면이 완전히 비어 보이지 않도록 기본 카메라 1개로
    폴백합니다 (build_camera_list(1)).

    카메라 개수/이름은 이 함수로 직접 조절하지 않고, 설정 페이지에서 지도에
    찍은 초소(마커) 개수로 자동 결정됩니다."""
    outposts = get_outposts()
    cameras = to_camera_list(outposts) if outposts else build_camera_list(1)
    _cleanup_removed_cameras(cameras)
    _sync_preset_media(outposts, cameras)
    return cameras


def _sync_preset_media(outposts: list[dict], cameras: list[dict]) -> None:
    """설정 페이지에서 초소에 매핑해둔 영상을, 아직 반영되지 않은 카메라
    채널에 자동으로 반영합니다 (ui/camera/card.py의 자체 업로드 버튼을
    대체). 어느 채널(EO/TIR)을 반영할지는 session_state.active_channel_{cid}
    를 따르며, 아직 카드에서 전환한 적이 없으면 기본값인 EO를 사용합니다.
    이미 반영된 채널(fp_{cid} 존재 — 카드의 EO/TIR 수동 전환 포함)은 매
    실행마다 재초기화되지 않도록 건너뜁니다."""
    ss = st.session_state
    cam_by_id = {c["id"]: c for c in cameras}
    for o in outposts:
        cid = o["id"]
        if ss.get(f"fp_{cid}") is not None:
            continue
        channel = ss.get(f"active_channel_{cid}", "eo")
        data = o.get(f"video_{channel}_bytes")
        if not data:
            continue
        cam = cam_by_id.get(cid)
        if cam:
            start_camera_media(cam, data, o.get(f"video_{channel}_name") or "preset")


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
