"""
services/outposts.py — 초소(지도 마커) 관리 및 카메라 목록 변환

설정 페이지(ui/outposts/editor.py)에서 관리자가 지도 이미지 위에 클릭으로
초소 위치를 마킹하면, 그 마커 하나하나가 곧 카메라 1대가 됩니다. 이 파일은
"카메라 개수 +/- 스텝퍼"를 대체하는 단일 출처(source of truth)로, 마커
목록(session_state.outposts)의 추가/수정/삭제와, 그 목록을 나머지 시스템
(services/camera_registry.py 등)이 기존처럼 쓸 수 있는 카메라 딕셔너리
리스트({"id", "name"})로 변환하는 역할을 함께 담당합니다.

화면 렌더링(st.file_uploader, streamlit_image_coordinates 등)은 전혀 포함하지
않는 순수 상태 관리 계층입니다 — README의 services/ 설계 원칙을 그대로 따릅니다.

현재는 세션(session_state) 메모리에만 보관됩니다. RDS에는 아직 초소 전용
테이블이 없어 앱 재시작/재로그인 시 초기화됩니다 — 이는 기존 "카메라 개수"
설정도 동일하게 세션 한정이었던 것과 같은 수준의 동작이며, 영구 저장이
필요해지면 db_rds.py에 outposts 테이블을 추가하고 이 파일의 CRUD 함수들만
DB 연동으로 바꿔주면 됩니다.
"""
import streamlit as st

from config import MAX_CAMERAS


def get_outposts() -> list[dict]:
    """현재 등록된 초소(마커) 목록을 반환합니다."""
    return st.session_state.get("outposts", [])


def get_map_image_bytes() -> bytes | None:
    """업로드된 지도 원본 이미지 바이트를 반환합니다 (미업로드 시 None)."""
    return st.session_state.get("_outpost_map_image_bytes")


def set_map_image_bytes(data: bytes) -> None:
    """새 지도 이미지를 업로드하면 기존 마커 배치가 새 지도 기준으로는 의미가
    없으므로, 지도를 교체할 때는 항상 마커 목록도 함께 초기화합니다."""
    ss = st.session_state
    ss["_outpost_map_image_bytes"] = data
    reset_all()


def add_marker(x_ratio: float, y_ratio: float) -> dict | None:
    """지도 클릭 좌표(0~1로 정규화된 비율)로 새 초소 마커를 추가합니다.

    비율로 저장하는 이유: 설정 페이지와 대시보드 지도 탭에서 이미지가 서로
    다른 크기로 표시되더라도(반응형 레이아웃), 항상 원본 이미지 기준 동일한
    상대 위치에 마커가 그려지도록 하기 위함입니다.

    이미 MAX_CAMERAS개가 등록되어 있으면 추가하지 않고 None을 반환합니다.
    """
    ss = st.session_state
    outposts = ss.setdefault("outposts", [])
    if len(outposts) >= MAX_CAMERAS:
        return None

    ss["_outpost_id_counter"] = ss.get("_outpost_id_counter", 0) + 1
    marker = {
        "id": f"cam{ss['_outpost_id_counter']}",   # 세션 내 영구 고유 id — 삭제돼도 재사용되지 않음
        "info": "",     # 초소 정보 (관리자가 직접 편집)
        "source": "",   # 영상 소스 (관리자가 직접 편집, 참고용 메타데이터)
        "x_ratio": round(float(x_ratio), 4),
        "y_ratio": round(float(y_ratio), 4),
    }
    outposts.append(marker)
    return marker


def update_marker(idx: int, info: str, source: str) -> None:
    """표시 순서(idx, 0-based)에 해당하는 마커의 초소정보/영상소스만 갱신합니다.
    좌표(x_ratio/y_ratio)는 지도 재클릭이 아니면 바뀌지 않으므로 여기서 건드리지 않습니다."""
    outposts = st.session_state.get("outposts", [])
    if 0 <= idx < len(outposts):
        outposts[idx]["info"] = info
        outposts[idx]["source"] = source


def remove_markers(ids: list[str]) -> None:
    """지정한 id들의 마커를 목록에서 제거하고, 해당 카메라가 쓰던 재생/추적
    리소스도 함께 정리합니다 (그리드 축소 시 정리하던 방식과 동일)."""
    from services.playback import reset_cam_state  # 지연 import: services 내부 순환참조 방지

    ss = st.session_state
    outposts = ss.get("outposts", [])
    ss["outposts"] = [o for o in outposts if o["id"] not in ids]
    for cid in ids:
        reset_cam_state(cid)


def reset_all() -> None:
    """모든 초소 마커를 삭제합니다 ('전체 초기화' 버튼)."""
    from services.playback import reset_cam_state

    ss = st.session_state
    for o in ss.get("outposts", []):
        reset_cam_state(o["id"])
    ss["outposts"] = []


def cctv_no(idx: int) -> str:
    """표시 순서(0-based)를 "CCTV1", "CCTV2" ... 형태의 표시용 번호로 변환합니다.
    삭제/추가로 순서가 바뀌어도 항상 현재 목록 순서 기준으로 다시 매겨집니다."""
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
