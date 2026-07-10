"""
services/outposts.py — 초소(지도 마커) 관리 및 카메라 목록 변환

지도 "이미지"는 config.PRESET_MAP_IMAGE_PATH에 고정되어 있어 관리자가
업로드하지 않습니다. 반면 그 위의 초소(마커) "위치"는 관리자가 설정 페이지
지도를 클릭해 직접 찍고 지울 수 있습니다 — **찍은 마커 개수가 곧 카메라
개수**입니다 (services/camera_registry.to_camera_list 경유). 이 파일은
- 마커를 추가/삭제하고,
- 각 마커의 "초소 정보"/"영상 소스" 텍스트를 수정하고,
- 각 마커에 CCTV 영상을 채널별(EO/TIR)로 매핑하고,
- 그 목록을 나머지 시스템(services/camera_registry.py 등)이 기존처럼 쓸 수
  있는 카메라 딕셔너리 리스트({"id", "name"})로 변환하는
역할을 담당하는 순수 상태 관리 계층입니다.

화면 렌더링(st.file_uploader, streamlit_image_coordinates 등)은 전혀
포함하지 않습니다 — README의 services/ 설계 원칙을 그대로 따릅니다.

우리 탐지 모델은 EO(가시광)·TIR(열화상) 두 영상을 함께 입력받는 RGB-IR
융합 모델이므로, 초소 1곳당 영상을 EO/TIR 두 채널로 각각 매핑해둘 수
있습니다. 매핑해두면 그중 "배경 채널"(기본 EO) 하나만 항상 백그라운드에서
재생·탐지됩니다(services/camera_registry._sync_preset_media가 대시보드
진입 시 자동 시작) — 두 채널을 항상 동시에 재생하면 카메라가 몇 대만
있어도 메모리 부족 크래시로 이어져(services/playback.py 모듈 docstring
참고), 지금은 필요할 때만 두 번째 채널을 켭니다. 카메라 카드(ui/camera/
card.py)의 EO/TIR 탭은 그리드에서는 배경 채널 자체를 전환하고, 스포트라이트
에서는 두 번째 채널의 재생을 필요할 때만 시작/중지해 2분할로 보여줍니다
(session_state.active_channel_{id}/active_channel_secondary_{id}).

현재는 세션(session_state) 메모리에만 보관됩니다(매핑한 영상 바이트 포함).
RDS에는 아직 초소 전용 테이블이 없어 앱 재시작/재로그인 시 초기화됩니다 —
영구 저장이 필요해지면 db_rds.py에 outposts 테이블(+ 영상은 S3)을 추가하고
이 파일의 CRUD 함수들만 연동으로 바꿔주면 됩니다.
"""
import streamlit as st

from config import PRESET_MAP_IMAGE_PATH


def _ensure_loaded() -> None:
    """세션에 초소 목록/id 카운터가 없으면 빈 상태로 초기화합니다."""
    ss = st.session_state
    ss.setdefault("outposts", [])
    ss.setdefault("_outpost_id_counter", 0)  # 마커 삭제 후에도 id가 재사용되지 않도록 하는 증가 카운터


def get_outposts() -> list[dict]:
    """현재 등록된 초소(마커) 목록을 반환합니다 (관리자가 지도에 찍은 순서)."""
    _ensure_loaded()
    return st.session_state["outposts"]


def get_map_image_bytes() -> bytes:
    """프리셋 지도 이미지 바이트를 반환합니다 (최초 1회만 디스크에서 읽고 세션에 캐시)."""
    ss = st.session_state
    if ss.get("_outpost_map_image_bytes") is None:
        with open(PRESET_MAP_IMAGE_PATH, "rb") as f:
            ss["_outpost_map_image_bytes"] = f.read()
    return ss["_outpost_map_image_bytes"]


def add_marker(x_ratio: float, y_ratio: float) -> str:
    """지도 위 (x_ratio, y_ratio)(0~1 비율 좌표) 위치에 새 초소 마커를 추가하고
    새로 생성된 마커 id를 반환합니다."""
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
    """초소 마커 1개를 삭제하고, EO/TIR 두 채널의 재생 리소스와 선택 상태를
    함께 정리합니다."""
    from services.playback import reset_cam_state  # 지연 import: services 내부 순환참조 방지

    ss = st.session_state
    ss["outposts"] = [o for o in get_outposts() if o["id"] != marker_id]
    reset_cam_state(marker_id, state_suffix="_eo")
    reset_cam_state(marker_id, state_suffix="_tir")
    ss.pop(f"active_channel_secondary_{marker_id}", None)

    selected = set(ss.get("_map_selected_cam_ids", []))
    if marker_id in selected:
        selected.discard(marker_id)
        ss["_map_selected_cam_ids"] = list(selected)


def update_marker(marker_id: str, *, info: str | None = None, source: str | None = None) -> None:
    """마커의 초소정보/영상소스(메모) 텍스트를 갱신합니다. None으로 넘긴 값은 그대로 둡니다."""
    for o in get_outposts():
        if o["id"] == marker_id:
            if info is not None:
                o["info"] = info
            if source is not None:
                o["source"] = source
            break


def set_marker_video(marker_id: str, channel: str, data: bytes, filename: str) -> None:
    """설정 페이지에서 특정 초소에 CCTV 영상을 채널별(EO/TIR)로 매핑(업로드)합니다.

    매핑한 채널의 재생 상태를 항상 정리해둡니다 — 그 채널이 지금 "배경
    채널"(session_state.active_channel_{marker_id})이면 services/
    camera_registry._sync_preset_media가 다음 렌더에서 새 영상으로 자동으로
    다시 재생을 시작합니다. 배경 채널이 아니면(재생 중이 아니었거나
    스포트라이트 보조 채널이었던 경우) 그냥 재생 상태만 비워둡니다 — 필요할
    때 ui/camera/card.py의 EO/TIR 버튼으로 다시 켜면 새 영상이 반영됩니다."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"

    for o in get_outposts():
        if o["id"] == marker_id:
            o[f"video_{channel}_bytes"] = data
            o[f"video_{channel}_name"] = filename
            from services.playback import reset_cam_state
            reset_cam_state(marker_id, state_suffix=f"_{channel}")
            break


def get_marker_video(marker_id: str, channel: str) -> tuple[bytes, str] | None:
    """초소에 매핑된 채널별(EO/TIR) 영상(바이트, 파일명)을 반환합니다. 없으면 None."""
    assert channel in ("eo", "tir"), f"알 수 없는 채널: {channel}"
    for o in get_outposts():
        if o["id"] == marker_id:
            data = o.get(f"video_{channel}_bytes")
            if data:
                return data, o.get(f"video_{channel}_name", "")
    return None


def cctv_no(idx: int) -> str:
    """표시 순서(0-based)를 "CCTV1", "CCTV2" ... 형태의 표시용 번호로 변환합니다."""
    return f"CCTV{idx + 1}"


def to_camera_list(outposts: list[dict] | None = None) -> list[dict]:
    """초소 마커 목록을 나머지 시스템(camera_registry, playback, tracking 등)이
    기존과 동일하게 소비할 수 있는 {"id", "name"} 카메라 딕셔너리 리스트로 변환합니다.

    표시 이름(name)은 관리자가 초소 정보를 입력했으면 "CCTV1 (초소 정보)",
    아직 입력 전이면 "CCTV1"만 사용합니다.
    """
    outposts = get_outposts() if outposts is None else outposts
    cameras = []
    for i, o in enumerate(outposts):
        no = cctv_no(i)
        info = (o.get("info") or "").strip()
        name = f"{no} ({info})" if info else no
        cameras.append({"id": o["id"], "name": name})
    return cameras
