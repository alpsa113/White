"""ui/outposts/viewer.py — 관제 지도(초소 마커 + 점멸) 미니맵 렌더링. 마커 클릭으로 CCTV 화면 보기 선택을 토글합니다."""
import io

import streamlit as st
from PIL import Image

from services import outposts as outposts_service
from ui.outposts.marker_overlay import (
    BLINK_CSS, MAP_WRAP_KEY, render_marker, render_stop_icon, selected_ids, visible_camera_ids,
)
from ui.styles import MAP_WRAP_CSS_TEMPLATE


def render_map(cameras: list[dict]) -> None:
    """지도 이미지 위에 초소 마커를 겹쳐 그립니다. 사람이 탐지된 카메라의 마커는 점멸합니다."""
    ss = st.session_state

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
    st.markdown(
        MAP_WRAP_CSS_TEMPLATE.format(wrap_key=MAP_WRAP_KEY, img_w=img_w, img_h=img_h),
        unsafe_allow_html=True,
    )

    visible_ids = visible_camera_ids(cameras)

    with st.container(key=MAP_WRAP_KEY):
        st.image(img, use_container_width=True)

        for i, o in enumerate(outposts):
            cid = o["id"]
            cam_name = cam_name_by_id.get(cid, cid)
            # 사람 추적 상태는 현재 선택된 채널(EO/TIR) 기준
            active_channel = ss.get(f"active_channel_{cid}", "eo")
            tracks = ss.get(f"person_tracks_{cid}_{active_channel}")
            is_blinking = bool(tracks) and not ss.get(f"blink_stopped_{cid}", False)
            if not tracks:
                ss.pop(f"blink_stopped_{cid}", None)

            is_selected = cid in selected_ids()
            render_marker(cid, o["x_ratio"], o["y_ratio"], number=i + 1,
                          selected=is_selected, checked=cid in visible_ids,
                          blinking=is_blinking, label=cam_name)

            if is_blinking:
                render_stop_icon(cid, label=cam_name)
