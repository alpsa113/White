"""ui/log_tabs.py — 감지 기록 페이지의 조회/편집 탭 렌더링. 저장 로직은 services/log_management.py에 위임합니다."""
import pandas as pd
import streamlit as st

import s3_storage as s3
from config import PERSON_CLASSES
from services.log_management import save_log_edits
from utils.formatters import fmt_dt

# 클래스명이 사람인 행 강조 스타일
_PERSON_CLASS_BG = "background-color: rgba(248,81,73,0.18);"
_PERSON_CLASS_STYLE = _PERSON_CLASS_BG + "color: #f85149; font-weight: 700;"


def _highlight_person_class(val: str) -> str:
    """'클래스명' 컬럼에서 사람 클래스일 때만 배경색/글자색을 강조합니다."""
    return _PERSON_CLASS_STYLE if val in PERSON_CLASSES else ""


def _build_view_df(sorted_logs: list[dict]) -> pd.DataFrame:
    """조회 탭 DataFrame을 구성합니다(정렬은 호출 측에서 완료됨)."""
    df_data = []
    for a in sorted_logs:
        df_data.append({
            "탐지 ID":        a.get("id"),
            "카메라":         a.get("camera", ""),
            "탐지 일시":      fmt_dt(a),
            "클래스명":       a.get("class_name", ""),
            "신뢰도 (Score)": f"{float(a.get('score', a.get('confidence', 0))):.1%}",
            "이미지 URI":     a.get("uri", a.get("image_path", "")),
        })
    return pd.DataFrame(df_data)


def render_view_tab(sorted_logs: list[dict]) -> None:
    """조회 표 + 선택 행의 탐지 이미지 뷰어를 좌우로 배치합니다."""
    ss = st.session_state
    df = _build_view_df(sorted_logs)

    view_col, img_col = st.columns([6, 4])

    with view_col:
        styled_df = df.drop(columns=["이미지 URI"]).style.map(
            _highlight_person_class, subset=["클래스명"]
        )
        selection = st.dataframe(
            styled_df,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="log_viewer",
        )

        selected_rows = selection.selection.get("rows", [])
        if selected_rows:
            _sel_idx = selected_rows[0]
            if 0 <= _sel_idx < len(df):
                ss["selected_log_id"] = df.iloc[_sel_idx]["탐지 ID"]
        elif "selected_log_id" not in ss:
            ss["selected_log_id"] = None

    with img_col:
        sel_log_id = ss.get("selected_log_id")

        if sel_log_id is None:
            st.info("왼쪽 표에서 행을 클릭하면 해당 객체의 탐지 이미지가 표시됩니다.")
            return

        sel_log = next((a for a in ss.detection_logs if a.get("id") == sel_log_id), None)

        if sel_log is None:
            st.warning("선택된 로그를 찾을 수 없습니다.")
            ss["selected_log_id"] = None
            return

        snap = sel_log.get("snapshot")
        image_uri = sel_log.get("uri", sel_log.get("image_path", ""))
        content_type = sel_log.get("content_type", "image/jpeg")

        st.markdown(
            f"**카메라: {sel_log.get('camera', '-')}** &nbsp; | &nbsp; "
            f"클래스: `{sel_log.get('class_name', '')}` &nbsp; | &nbsp; "
            f"Score: **{float(sel_log.get('score', sel_log.get('confidence', 0))):.1%}**",
            unsafe_allow_html=True
        )
        st.caption(f"탐지시각: {fmt_dt(sel_log)}")
        st.divider()

        if content_type == "video/mp4" and ss.get("S3_ENABLED") and image_uri:
            clip_url = s3.get_presigned_url(image_uri)
            if clip_url:
                st.video(clip_url)
            else:
                st.warning("S3 클립을 불러올 수 없습니다. 경로를 확인하세요.")
        elif snap is not None:
            st.image(snap, use_container_width=True, caption="탐지 순간 캡처 (클립 준비 중)")
        elif ss.get("S3_ENABLED") and image_uri:
            with st.spinner("S3 저장소에서 이미지 불러오는 중..."):
                img_bytes = s3.download_snapshot(image_uri)
            if img_bytes:
                st.image(img_bytes, use_container_width=True, caption=f"탐지 이미지 ({image_uri})")
            else:
                st.warning("S3 이미지를 불러올 수 없습니다. 경로를 확인하세요.")
        else:
            st.info("저장된 이미지 URI가 없습니다.")


def render_manage_tab(sorted_logs: list[dict]) -> None:
    """st.data_editor로 로그를 수정/삭제하는 관리 화면입니다. 저장은 save_log_edits()가 담당합니다."""
    ss = st.session_state

    st.caption(
        "셀을 직접 클릭하여 수정할 수 있습니다. "
        "삭제할 행은 왼쪽 체크박스로 선택한 뒤 우상단 **🗑️ 휴지통** 버튼을 누르세요. "
        "**변경사항 저장** 버튼을 누르면 수정·삭제가 RDS에 즉시 반영됩니다."
    )

    df_edit_data = []
    for a in sorted_logs:
        df_edit_data.append({
            "탐지 ID":    a.get("id"),
            "탐지 일시":  fmt_dt(a),
            "카메라":     a.get("camera", ""),
            "클래스명":   a.get("class_name", ""),
            "신뢰도 (%)": round(float(a.get("score", a.get("confidence", 0))) * 100, 1),
            "이미지 경로": a.get("uri", a.get("image_path", "")),
            "상태":       a.get("status", "대기"),
            "비고":       a.get("remarks", ""),
        })
    df_edit_orig = pd.DataFrame(df_edit_data)

    known_classes = sorted(
        {"사람", "멧돼지", "고라니", "소형동물"} | set(df_edit_orig["클래스명"].dropna().unique())
    )

    edited_df = st.data_editor(
        df_edit_orig,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        disabled=["탐지 ID"],
        column_config={
            "탐지 ID": st.column_config.NumberColumn(
                "탐지 ID", help="고유 식별자 (수정 불가)", width="small"
            ),
            "탐지 일시": st.column_config.TextColumn(
                "탐지 일시", help="YYYY-MM-DD HH:MM:SS"
            ),
            "카메라": st.column_config.TextColumn("카메라"),
            "클래스명": st.column_config.SelectboxColumn(
                "클래스명", options=known_classes, required=True
            ),
            "신뢰도 (%)": st.column_config.NumberColumn(
                "신뢰도 (%)",
                min_value=0.0, max_value=100.0,
                step=0.1, format="%.1f%%",
            ),
            "이미지 경로": st.column_config.TextColumn(
                "이미지 경로", help="S3 이미지 경로"
            ),
            "상태": st.column_config.SelectboxColumn(
                "상태",
                options=["대기", "오탐", "사람탐지(경보)", "동물탐지"],
                required=True,
            ),
            "비고": st.column_config.TextColumn("비고"),
        },
        key="log_editor_manage",
    )

    btn_col, _ = st.columns([2, 8])
    with btn_col:
        save_clicked = st.button(
            "변경사항 저장", type="primary", use_container_width=True
        )

    if not save_clicked:
        return

    result = save_log_edits(df_edit_orig, edited_df)
    updated_count = result["updated_count"]
    removed_ids = result["removed_ids"]
    rds_errors = result["rds_errors"]

    msgs = []
    if removed_ids:
        msgs.append(f"{len(removed_ids)}개 행 삭제")
    if updated_count:
        msgs.append(f"{updated_count}개 행 수정")

    if msgs:
        suffix = " (RDS 반영)" if ss.get("DB_ENABLED") else " (메모리 모드)"
        st.success("✅ " + " / ".join(msgs) + " 완료" + suffix)
    else:
        st.info("변경된 내용이 없습니다.")

    if rds_errors:
        st.warning("일부 RDS 갱신/삭제 실패:\n" + "\n".join(rds_errors))

    st.rerun()
