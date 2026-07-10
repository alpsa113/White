"""
ui/outposts/editor.py — 설정 페이지: 초소 위치 지도(클릭 마킹) + 정보/영상 매핑 편집기

지도 "이미지"는 config.PRESET_MAP_IMAGE_PATH에 고정되어 있어 업로드하지
않습니다. 그 위의 초소(마커) "위치"는 관리자가 지도를 클릭해 직접 찍고
지울 수 있습니다 — **찍은 마커 개수가 곧 '실시간 감시'의 카메라 개수**입니다
(services/outposts.py → services/camera_registry.py).

지도 클릭으로 마커를 "추가"하는 것과, 이미 있는 마커를 "선택/해제"하는 것은
서로 다른 상호작용입니다. `streamlit_image_coordinates`는 이미지 위 클릭을
가로채 좌표를 돌려주는 컴포넌트라 그 위에 별도의 클릭 가능한 마커 버튼을
겹쳐 그릴 수 없습니다(클릭 우선순위가 애매해짐). 그래서 지도 미리보기에는
마커를 색칠된 원(PIL로 그려 넣음, 선택 여부에 따라 하늘색/빨간색)으로만
표시하고, 실제 선택/해제·삭제·영상 매핑은 그 아래 목록의 버튼으로 합니다.

각 초소 행에서 admin이 할 수 있는 일 (user는 초소 정보 조회만 가능 —
지도 클릭/영상 업로드/선택/삭제 버튼이 아예 보이지 않습니다):
  1) "초소 정보" 텍스트 수정 (입력 즉시 자동 저장됩니다)
  2) CCTV 영상을 EO(가시광)/TIR(열화상) 채널로 각각 매핑(업로드) — 우리
     탐지 모델이 두 영상을 함께 입력받는 RGB-IR 융합 모델이기 때문입니다.
     행 너비를 줄이기 위해 팝오버 버튼(🎬) 안에 몰아넣었습니다. 매핑해두면
     '실시간 감시' 페이지의 카메라 카드가 별도 업로드 없이 바로 재생합니다
     (기본은 EO 채널 — 카드 상단의 EO/TIR 탭으로 즉석 전환 가능,
     ui/camera/card.py 참고).
  3) "CCTV 화면 보기"로 선택/해제 (🔵/🔴 버튼) — 대시보드의 '카메라 화면'
     탭(선택된 카메라만 그리드로 필터링)과 '관제 지도' 탭(왼쪽 CCTV 요약·
     마커 색상) 양쪽 모두와 이 선택 상태를 공유합니다
     (ui/outposts/marker_overlay.toggle_selection).
  4) 마커 삭제 (🗑 버튼) — 그 초소의 재생 리소스도 함께 정리됩니다.
"""
import io

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

from config import VIDEO_EXTS
from services import outposts as outposts_service
from ui.outposts.marker_overlay import DEFAULT_COLOR, SELECTED_COLOR, selected_ids, toggle_selection


def _draw_markers(base_img: Image.Image, outposts: list[dict], selected: set) -> Image.Image:
    """프리셋 지도 이미지 위에 현재 마커들을 번호 매긴 원으로 그려 넣습니다
    (선택된 마커는 빨간색, 그 외는 하늘색 — §3.1 색상 규칙과 동일). 이 결과
    이미지는 클릭 좌표 캡처용(streamlit_image_coordinates)으로만 쓰이는
    미리보기이지, 마커 자체가 클릭 가능한 것은 아닙니다."""
    img = base_img.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size
    radius = max(11, min(w, h) // 45)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", max(12, int(radius * 1.1))
        )
    except Exception:
        font = ImageFont.load_default()

    for i, o in enumerate(outposts):
        cx, cy = o["x_ratio"] * w, o["y_ratio"] * h
        color = SELECTED_COLOR if o["id"] in selected else DEFAULT_COLOR
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                     fill=color, outline="white", width=2)
        label = str(i + 1)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), label, fill="white", font=font)

    return img


def _handle_map_click(coords: dict | None) -> None:
    """지도 클릭 좌표를 새 마커로 추가합니다. 같은 클릭이 재실행마다 중복
    반영되지 않도록 마지막으로 처리한 좌표와 비교합니다.

    streamlit_image_coordinates가 돌려주는 x/y는 화면에 "실제로 그려진"
    크기 기준입니다(원본 이미지의 자연 해상도가 아님) — 컴포넌트가 같이
    돌려주는 width/height(그 순간의 렌더링 크기)로 나눠야 컨테이너 폭이나
    화면 크기가 달라져도 항상 정확한 0~1 비율 좌표가 나옵니다."""
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
    """설정 페이지 상단에 삽입되는 초소 위치 지도 + 정보/영상 매핑 편집기를 렌더링합니다.

    admin은 마커 추가(지도 클릭)/정보 수정/영상 매핑/선택/삭제를 모두 할 수
    있고, user는 지도와 초소 정보를 조회만 할 수 있습니다(마커 추가/영상
    업로드/선택/삭제 버튼이 아예 보이지 않습니다)."""
    ss = st.session_state
    is_admin = ss.get("role") == "admin"

    st.markdown("### 초소 위치 상황판")
    if is_admin:
        st.caption(
            "지도를 클릭해 초소 마커를 추가하세요 — 찍은 마커 개수만큼 '실시간 감시'의 "
            "카메라가 자동으로 생성됩니다. 아래 목록에서 각 초소의 정보를 수정하거나 "
            "EO/TIR 영상을 매핑해두면, '실시간 감시' 페이지에서 별도 업로드 없이 바로 재생됩니다."
        )
    else:
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
            # user는 마커를 추가할 수 없으므로, 클릭을 가로채는 컴포넌트 대신
            # 순수 읽기 전용 이미지로 보여줍니다.
            st.markdown("**지도 미리보기** (조회 전용)")
            st.image(preview, use_container_width=True)

        st.caption("🔵 기본 · 🔴 CCTV 화면 보기로 선택됨"
                   + (" — 선택/해제는 아래 목록의 버튼을 사용하세요 "
                      "('카메라 화면'·'관제 지도' 탭과 선택 상태가 함께 반영됩니다)." if is_admin else "."))

    with list_col:
        st.markdown("**초소 정보** · 영상 매핑" if is_admin else "**초소 정보**")
        if not outposts:
            st.caption("등록된 초소가 없습니다" + (" — 왼쪽 지도를 클릭해 추가하세요." if is_admin else "."))
            return

        for i, m in enumerate(outposts):
            cid = m["id"]
            cam_name = cam_name_by_id.get(cid, cid)
            is_selected = cid in selected

            if is_admin:
                _render_row_admin(i, m, cid, cam_name, is_selected)
            else:
                _render_row_readonly(i, m)


def _render_row_admin(i: int, m: dict, cid: str, cam_name: str, is_selected: bool) -> None:
    """admin용 초소 1행 — 정보 수정 + 영상 매핑(EO/TIR) + 선택/삭제."""
    name_col, info_col, popover_col, select_col, delete_col = st.columns(
        [1, 2.4, 0.6, 0.6, 0.6]
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

    with select_col:
        icon = "🔴" if is_selected else "🔵"
        help_txt = f"{cam_name} — 클릭하여 선택 해제" if is_selected else f"{cam_name} — 클릭하여 CCTV 화면 보기로 선택"
        if st.button(icon, key=f"_op_select_{cid}", help=help_txt):
            toggle_selection(cid)

    with delete_col:
        if st.button("🗑", key=f"_op_delete_{cid}", help=f"{cam_name} — 마커 삭제"):
            outposts_service.remove_marker(cid)
            st.rerun()


def _render_row_readonly(i: int, m: dict) -> None:
    """user용 초소 1행 — 정보 조회만 가능(입력/업로드/선택/삭제 버튼 없음)."""
    name_col, info_col = st.columns([1, 4])
    with name_col:
        st.markdown(f"**{outposts_service.cctv_no(i)}**")
    with info_col:
        st.text_input(
            "초소 정보", value=m.get("info", "") or "(정보 없음)",
            key=f"_op_info_ro_{m['id']}", disabled=True, label_visibility="collapsed",
        )
