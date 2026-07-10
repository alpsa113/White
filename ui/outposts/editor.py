"""ui/outposts/editor.py — 설정 페이지: 초소 위치 지도(클릭 마킹) + 정보/영상 매핑 편집기.
지도 이미지는 고정 파일이며, 그 위의 초소(마커) 위치만 관리자가 클릭으로 찍고 지울 수 있습니다."""
import io

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

from config import VIDEO_EXTS
from services import outposts as outposts_service
from ui.outposts.marker_overlay import DEFAULT_COLOR, SELECTED_COLOR, selected_ids


def _draw_markers(base_img: Image.Image, outposts: list[dict], selected: set) -> Image.Image:
    """지도 이미지 위에 번호 매긴 원으로 마커를 그려 넣습니다(선택된 마커는 빨간색)."""
    img = base_img.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size
    radius = max(16, min(w, h) // 32)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(18, int(radius * 1.3))
        )
    except Exception:
        font = ImageFont.load_default()

    for i, o in enumerate(outposts):
        cx, cy = o["x_ratio"] * w, o["y_ratio"] * h
        color = SELECTED_COLOR if o["id"] in selected else DEFAULT_COLOR
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     fill=color, outline="white", width=3)
        label = str(i + 1)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), label, fill="white", font=font)

    return img


def _handle_map_click(coords: dict | None) -> None:
    """지도 클릭 좌표를 새 마커로 추가합니다(중복 반영 방지)."""
    ss = st.session_state
    if coords is None:
        return
    sig = (coords.get("x"), coords.get("y"))
    if ss.get("_outpost_last_click") == sig:
        return
    ss["_outpost_last_click"] = sig
    w, h = coords.get("width"), coords.get("height")
    if not w or not h:
        return
    outposts_service.add_marker(coords["x"] / w, coords["y"] / h)
    st.rerun()


def _save_info(cid: str) -> None:
    """초소 정보 입력창의 on_change 콜백 — 입력 즉시 자동 저장합니다."""
    outposts_service.update_marker(cid, info=st.session_state[f"_op_info_{cid}"])


def render_outpost_editor() -> None:
    """초소 위치 지도 + 정보/영상 매핑 편집기를 렌더링합니다(user는 조회만 가능)."""
    ss = st.session_state
    is_admin = ss.get("role") == "admin"

    st.markdown("### 초소 위치 상황판")
    if not is_admin:
        st.caption("현재 등록된 초소 위치와 정보를 조회할 수 있습니다 (조회 전용).")

    outposts = outposts_service.get_outposts()
    cam_name_by_id = {c["id"]: c["name"] for c in outposts_service.to_camera_list(outposts)}
    selected = selected_ids()

    map_col, list_col = st.columns([3, 2])

    with map_col:
        map_bytes = outposts_service.get_map_image_bytes()
        base_img = Image.open(io.BytesIO(map_bytes))
        preview = _draw_markers(base_img, outposts, selected)

        if is_admin:
            st.markdown("**지도 미리보기** (클릭하여 마커 추가)")
            coords = streamlit_image_coordinates(
                preview, key="outpost_map_click", use_column_width="always",
            )
            _handle_map_click(coords)
        else:
            st.markdown("**지도 미리보기** (조회 전용)")
            st.image(preview, use_container_width=True)

    with list_col:
        st.markdown("**초소 정보** · 영상 매핑" if is_admin else "**초소 정보**")
        if not outposts:
            st.caption("등록된 초소가 없습니다" + (" — 왼쪽 지도를 클릭해 추가하세요." if is_admin else "."))
            return

        for i, m in enumerate(outposts):
            cid = m["id"]
            cam_name = cam_name_by_id.get(cid, cid)

            if is_admin:
                _render_row_admin(i, m, cid, cam_name)
            else:
                _render_row_readonly(i, m)


def _render_row_admin(i: int, m: dict, cid: str, cam_name: str) -> None:
    """admin용 초소 1행 — 정보 수정 + 영상 매핑(EO/TIR) + 삭제."""
    name_col, info_col, popover_col, delete_col = st.columns(
        [1, 3, 0.6, 0.6]
    )

    with name_col:
        st.markdown(f"**{outposts_service.cctv_no(i)}**")

    with info_col:
        st.text_input(
            "초소 정보", value=m.get("info", ""), key=f"_op_info_{cid}",
            on_change=_save_info, args=(cid,), label_visibility="collapsed",
        )

    with popover_col:
        with st.popover("🎬"):
            st.caption(f"{outposts_service.cctv_no(i)} 영상 매핑")

            source = st.text_input(
                "영상 소스 (메모)", value=m.get("source", ""), key=f"_op_source_{cid}",
            )

            eo_video = outposts_service.get_marker_video(cid, "eo")
            st.caption(f"EO(가시광): {'✅ ' + eo_video[1] if eo_video else '⚠️ 매핑된 영상 없음'}")
            eo_upload = st.file_uploader(
                "EO 영상 업로드", type=list(VIDEO_EXTS), key=f"_op_eo_{cid}",
            )

            tir_video = outposts_service.get_marker_video(cid, "tir")
            st.caption(f"TIR(열화상): {'✅ ' + tir_video[1] if tir_video else '⚠️ 매핑된 영상 없음'}")
            tir_upload = st.file_uploader(
                "TIR 영상 업로드", type=list(VIDEO_EXTS), key=f"_op_tir_{cid}",
            )

            if st.button("저장", key=f"_op_save_{cid}", use_container_width=True):
                outposts_service.update_marker(cid, source=source)
                if eo_upload is not None:
                    outposts_service.set_marker_video(cid, "eo", eo_upload.getvalue(), eo_upload.name)
                if tir_upload is not None:
                    outposts_service.set_marker_video(cid, "tir", tir_upload.getvalue(), tir_upload.name)
                st.success("저장되었습니다.")
                st.rerun()

    with delete_col:
        if st.button("🗑", key=f"_op_delete_{cid}", help=f"{cam_name} — 마커 삭제"):
            outposts_service.remove_marker(cid)
            st.rerun()


def _render_row_readonly(i: int, m: dict) -> None:
    """user용 초소 1행 — 정보 조회만 가능."""
    name_col, info_col = st.columns([1, 4])
    with name_col:
        st.markdown(f"**{outposts_service.cctv_no(i)}**")
    with info_col:
        st.text_input(
            "초소 정보", value=m.get("info", "") or "(정보 없음)",
            key=f"_op_info_ro_{m['id']}", disabled=True, label_visibility="collapsed",
        )
