"""
ui/outposts/editor.py — 설정 페이지: 지도 업로드 + 초소 위치 마킹 편집기

관리자가 지도 이미지를 업로드하고, streamlit-image-coordinates로 그 위를
클릭하여 초소(카메라) 위치를 마킹합니다. 마킹된 좌표는 원본 이미지 기준
0~1 비율(x_ratio/y_ratio)로 저장되어(services/outposts.py), 대시보드의
"관제 지도" 탭(ui/outposts/viewer.py)이 다른 화면 크기에서도 항상 같은
상대 위치에 마커를 그릴 수 있습니다.

카메라 개수/이름은 이 편집기가 유일한 출처입니다 — 마커를 추가하면 카메라가
늘고, 삭제하면 그 카메라가 쓰던 재생/추적 리소스도 함께 정리됩니다
(services/outposts.py의 remove_markers()/reset_all() 참고). 기존 "카메라
개수 +/- 스텝퍼"가 하던 역할을 이제 이 화면이 대신합니다.
"""
import io

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates

from config import MAX_CAMERAS
from services import outposts as outposts_service

MAP_DISPLAY_WIDTH = 640  # 클릭 좌표 계산의 기준이 되는 표시 폭(px). 원본 비율은 유지됩니다.
MARKER_RADIUS = 9


def _draw_markers(img: Image.Image, markers: list[dict]) -> Image.Image:
    """현재까지 마킹된 초소 위치를 이미지 위에 번호와 함께 그려 반환합니다
    (원본 이미지는 건드리지 않고 복사본에 그립니다)."""
    out = img.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for i, m in enumerate(markers):
        cx, cy = m["x_ratio"] * w, m["y_ratio"] * h
        r = MARKER_RADIUS
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#f85149", outline="white", width=2)
        draw.text((cx - 4, cy - 7), str(i + 1), fill="white")
    return out


def render_outpost_editor() -> None:
    """설정 페이지 상단에 삽입되는 지도 업로드 + 초소 마킹 편집기 전체를 렌더링합니다."""
    ss = st.session_state
    st.markdown("### 초소 위치 설정")
    st.caption(
        "지도 이미지를 업로드한 뒤 이미지를 클릭해 초소(카메라) 위치를 마킹하세요. "
        "마킹한 개수만큼 '실시간 감시' 페이지의 카메라가 자동으로 생성됩니다."
    )

    map_col, table_col = st.columns([3, 2])

    with map_col:
        st.markdown("**지도 이미지 업로드**")
        uploaded = st.file_uploader(
            "지도 이미지", type=["jpg", "jpeg", "png"], key="_outpost_map_uploader",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            # 파일명+크기 조합으로 "새로 업로드된 파일인지"를 판별 — 동일 파일이면
            # 재처리(=마커 초기화)하지 않음 (ui/camera/card.py의 업로드 판별 패턴과 동일)
            fp = (uploaded.name, uploaded.size)
            if ss.get("_outpost_map_uploaded_fp") != fp:
                ss["_outpost_map_uploaded_fp"] = fp
                outposts_service.set_map_image_bytes(uploaded.getvalue())
                st.rerun()

        map_bytes = outposts_service.get_map_image_bytes()
        if map_bytes is None:
            st.info("지도 이미지를 업로드하면 클릭으로 초소 위치를 마킹할 수 있습니다.")
            return

        markers = outposts_service.get_outposts()
        base_img = Image.open(io.BytesIO(map_bytes))
        display_img = _draw_markers(base_img, markers)

        st.caption(f"지도를 클릭해 초소를 추가하세요 ({len(markers)}/{MAX_CAMERAS}개 마킹됨)")
        coords = streamlit_image_coordinates(
            display_img, width=MAP_DISPLAY_WIDTH, key="_outpost_map_click",
        )
        if coords is not None:
            # 같은 클릭 이벤트가 rerun마다 반복 접수되는 것을 막기 위해 마지막으로
            # 처리한 클릭의 시각(unix_time)을 기억해두고, 새 클릭일 때만 마커를 추가합니다.
            if ss.get("_outpost_last_click_time") != coords["unix_time"]:
                ss["_outpost_last_click_time"] = coords["unix_time"]
                if len(markers) < MAX_CAMERAS:
                    x_ratio = coords["x"] / coords["width"]
                    y_ratio = coords["y"] / coords["height"]
                    outposts_service.add_marker(x_ratio, y_ratio)
                    st.rerun()
                else:
                    st.warning(f"초소는 최대 {MAX_CAMERAS}개까지 마킹할 수 있습니다.")

    with table_col:
        st.markdown("**초소 정보 편집**")
        markers = outposts_service.get_outposts()
        if not markers:
            st.caption("아직 마킹된 초소가 없습니다. 왼쪽 지도를 클릭해 추가하세요.")
            return

        df = pd.DataFrame([
            {
                "CCTV 번호": outposts_service.cctv_no(i),
                "초소 정보": m.get("info", ""),
                "영상 소스": m.get("source", ""),
                "x_ratio": m["x_ratio"],
                "y_ratio": m["y_ratio"],
            }
            for i, m in enumerate(markers)
        ])
        # 행 추가/삭제는 지도 클릭·아래 삭제 위젯으로만 이뤄지고, 이 표에서는
        # 초소정보/영상소스만 직접 고쳐 쓸 수 있습니다 (num_rows="fixed").
        edited = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            disabled=["CCTV 번호", "x_ratio", "y_ratio"],
            num_rows="fixed",
            key="_outpost_table_editor",
        )

        save_col, reset_col = st.columns(2)
        with save_col:
            if st.button("저장", type="primary", use_container_width=True, key="_outpost_save_btn"):
                for i, row in edited.iterrows():
                    outposts_service.update_marker(i, str(row["초소 정보"]), str(row["영상 소스"]))
                st.success("초소 정보가 저장되었습니다.")
                st.rerun()
        with reset_col:
            if st.button("전체 초기화", use_container_width=True, key="_outpost_reset_btn"):
                outposts_service.reset_all()
                st.rerun()

        st.caption("특정 초소만 지우려면 아래에서 선택 후 삭제하세요.")
        remove_options = {
            f"{outposts_service.cctv_no(i)} ({m.get('info') or '정보 없음'})": m["id"]
            for i, m in enumerate(markers)
        }
        to_remove = st.multiselect(
            "삭제할 초소 선택", options=list(remove_options.keys()), key="_outpost_remove_select",
        )
        if to_remove and st.button("선택 삭제", key="_outpost_remove_btn"):
            outposts_service.remove_markers([remove_options[label] for label in to_remove])
            st.rerun()
