"""
ui/outposts/viewer.py — 관제 지도(초소 마커 + 점멸) 렌더링

과거에는 대시보드에 독립된 "관제 지도" 탭이 있었지만 제거되었습니다. 설정
페이지에서 지정한 마커 찍힌 지도 이미지 자체는 그대로 살려서, '카메라 화면'
탭이 집중 보기(스포트라이트) 모드일 때 우측 패널에 끼워 넣는 용도로만
사용합니다 (ui/camera/spotlight.py 참고) — 그 화면에서 "지금 포커스 중인
카메라가 지도 어디에 있는지", "다른 곳에서 사람이 탐지되고 있는지"를 함께
보여주기 위함입니다.

마커를 클릭하면 여전히 "CCTV 화면 보기" 선택 상태(session_state.
_map_selected_cam_ids)를 토글합니다 — 이 상태는 설정 페이지의 초소 위치
지도(ui/outposts/editor.py) 및 '카메라 화면' 탭의 그리드 필터링과
공유됩니다(ui/outposts/marker_overlay.py, views/dashboard.py). 즉 이
지도에서 마커를 선택해도 다음 렌더에서 그 카메라들만 그리드로 필터링해
볼 수 있습니다.

사람이 탐지된 카메라의 마커는 점멸(blink)합니다. 점멸 마커를 클릭하면(=마커
본체) 선택 토글만 될 뿐 점멸은 멈추지 않습니다 — 점멸을 멈추려면 마커 옆에
별도로 붙는 작은 "⏹" 정지 아이콘을 클릭해야 합니다. 정지 상태는 추적이
끊겨(person_tracks가 비어) 자동 해제되면 다음 탐지부터 다시 점멸합니다.
"""
import io

import streamlit as st
from PIL import Image

from services import outposts as outposts_service
from ui.outposts.marker_overlay import BLINK_CSS, MAP_WRAP_KEY, render_marker, render_stop_icon, selected_ids


def render_map(cameras: list[dict]) -> None:
    """지도 이미지 위에 초소 마커를 겹쳐 그립니다. 마커를 클릭하면 "CCTV 화면
    보기" 선택 상태가 토글되고(다중 선택 가능), 점멸 중인 마커는 옆에 별도
    "⏹" 정지 아이콘이 함께 붙습니다.

    지도 래퍼 div는 이미지의 실제 가로:세로 비율에 `aspect-ratio`로 고정됩니다
    — 마커 좌표(x_ratio/y_ratio)는 이 래퍼의 크기를 기준으로 한 0~1 비율
    퍼센트 위치이므로, 래퍼가 이미지와 정확히 같은 비율이어야만 마커가 항상
    이미지 위 정확한 위치에 겹쳐집니다. (예전엔 래퍼 크기가 브라우저가 이미지
    로딩 후 계산하는 값에 맡겨져 있어, 컬럼 폭이 아주 좁아지는 스포트라이트
    레이아웃에서 래퍼와 실제 이미지 표시 영역이 어긋나 마커가 이미지 바깥에
    찍히는 문제가 있었습니다.)"""
    ss = st.session_state

    # 삭제된 카메라가 선택 목록에 남아있지 않도록 정리 (마커 삭제 등 예외 상황 대응)
    valid_ids = {c["id"] for c in cameras}
    stale = [cid for cid in ss.get("_map_selected_cam_ids", []) if cid not in valid_ids]
    if stale:
        ss["_map_selected_cam_ids"] = [cid for cid in ss["_map_selected_cam_ids"] if cid not in stale]

    map_bytes = outposts_service.get_map_image_bytes()
    outposts = outposts_service.get_outposts()
    if not outposts:
        st.info("등록된 초소가 없습니다 — '설정' 페이지에서 지도를 클릭해 초소를 추가하세요.")
        return

    img = Image.open(io.BytesIO(map_bytes))
    img_w, img_h = img.size

    cam_name_by_id = {c["id"]: c["name"] for c in cameras}
    st.markdown(BLINK_CSS, unsafe_allow_html=True)
    st.markdown(f"""
    <style>
    div[class*="st-key-{MAP_WRAP_KEY}"] {{
        position: relative;
        width: 100%;
        aspect-ratio: {img_w} / {img_h};
        overflow: hidden;
        border-radius: 4px;
    }}
    div[class*="st-key-{MAP_WRAP_KEY}"] img {{
        width: 100% !important;
        height: 100% !important;
        object-fit: contain;
        display: block;
    }}
    </style>
    """, unsafe_allow_html=True)

    with st.container(key=MAP_WRAP_KEY):
        st.image(img, use_container_width=True)

        for i, o in enumerate(outposts):
            cid = o["id"]
            cam_name = cam_name_by_id.get(cid, cid)
            tracks = ss.get(f"person_tracks_{cid}")
            is_blinking = bool(tracks) and not ss.get(f"blink_stopped_{cid}", False)
            # 추적이 끊기면(더 이상 사람이 없으면) 정지 상태를 해제해 다음 탐지 때 다시 점멸하도록 함
            if not tracks:
                ss.pop(f"blink_stopped_{cid}", None)

            is_selected = cid in selected_ids()
            render_marker(cid, o["x_ratio"], o["y_ratio"], number=i + 1,
                          selected=is_selected, blinking=is_blinking, label=cam_name)

            # 점멸 중일 때만 별도 정지 아이콘 노출
            if is_blinking:
                render_stop_icon(cid, label=cam_name)
