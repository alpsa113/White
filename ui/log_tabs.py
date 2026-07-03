"""
ui/log_tabs.py — 탐지 데이터 로그 페이지의 두 탭(조회 / 편집) 렌더링

탭1(render_view_tab)은 표+이미지 뷰어, 탭2(render_manage_tab)는 data_editor
기반 편집/삭제 UI를 담당합니다. 실제 저장 로직은 services/log_management.py에
위임합니다.
"""
import pandas as pd
import streamlit as st

import s3_storage as s3
from services.log_management import save_log_edits
from utils.formatters import fmt_dt, fmt_src, fmt_bbox


def _build_view_df(sorted_logs: list[dict]) -> pd.DataFrame:
    """조회 탭용 DataFrame 컬럼 매핑."""
    df_data = []
    for a in sorted_logs:
        df_data.append({
            "탐지 ID":        a.get("id"),
            "카메라":         a.get("camera", ""),
            "탐지 일시":      fmt_dt(a),
            "입력 소스":      fmt_src(a),
            "클래스명":       a.get("class_name", ""),
            "신뢰도 (Score)": f"{float(a.get('score', a.get('confidence', 0))):.1%}",
            "BBox 좌표":      fmt_bbox(a),
            "이미지 URI":     a.get("uri", a.get("image_path", "")),
        })
    return pd.DataFrame(df_data)


def render_view_tab(sorted_logs: list[dict]) -> None:
    """탭1 — 로그 조회 + 이미지 뷰어."""
    ss = st.session_state
    df = _build_view_df(sorted_logs)

    view_col, img_col = st.columns([6, 4])

    with view_col:
        # 뷰어에서는 경로가 긴 URI를 표에서 숨김 처리하여 가독성을 확보합니다.
        selection = st.dataframe(
            df.drop(columns=["이미지 URI"]),
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="log_viewer",
        )

        selected_rows = selection.selection.get("rows", [])
        if selected_rows:
            # 선택된 행의 탐지 ID를 저장 (인덱스 대신 ID 기반으로 추적하여 rerun 후 범위 초과 방지)
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

        # ID로 직접 로그를 찾으므로 DataFrame 인덱스 범위 초과 오류가 발생하지 않습니다.
        sel_log = next((a for a in ss.detection_logs if a.get("id") == sel_log_id), None)
        _df_match = df[df["탐지 ID"] == sel_log_id]
        sel_row = _df_match.iloc[0] if not _df_match.empty else None

        if sel_log is None or sel_row is None:
            st.warning("선택된 로그를 찾을 수 없습니다.")
            ss["selected_log_id"] = None  # 무효 선택 초기화
            return

        snap = sel_log.get("snapshot")
        image_uri = sel_log.get("uri", sel_log.get("image_path", ""))

        st.markdown(
            f"**카메라: {sel_log.get('camera', '-')}** &nbsp; | &nbsp; "
            f"클래스: `{sel_log.get('class_name', '')}` &nbsp; | &nbsp; "
            f"Score: **{float(sel_log.get('score', sel_log.get('confidence', 0))):.1%}**",
            unsafe_allow_html=True
        )
        st.caption(f"🕒 {fmt_dt(sel_log)} &nbsp;·&nbsp; BBox: {sel_row['BBox 좌표']}")
        st.divider()

        # 이미지 렌더링 순위: 메모리 스냅샷(세션 중) -> S3 다운로드
        if snap is not None:
            st.image(snap, use_container_width=True, caption="탐지 순간 캡처")
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
    """탭2 — 로그 편집 및 삭제 관리."""
    ss = st.session_state

    st.caption(
        "셀을 직접 클릭하여 수정할 수 있습니다. "
        "삭제할 행은 왼쪽 체크박스로 선택한 뒤 우상단 **🗑️ 휴지통** 버튼을 누르세요. "
        "**💾 변경사항 저장** 버튼을 누르면 수정·삭제가 RDS에 즉시 반영됩니다."
    )

    # ── 편집용 DataFrame 빌드 ──
    df_edit_data = []
    for a in sorted_logs:
        df_edit_data.append({
            "탐지 ID":    a.get("id"),                                    # PK — 수정 불가
            "탐지 일시":  fmt_dt(a),
            "카메라":     a.get("camera", ""),
            "입력 소스":  fmt_src(a),
            "클래스명":   a.get("class_name", ""),
            "신뢰도 (%)": round(float(a.get("score", a.get("confidence", 0))) * 100, 1),
            "BBox 좌표":  fmt_bbox(a),                                     # 수정 불가
            "이미지 경로": a.get("uri", a.get("image_path", "")),
            "상태":       a.get("status", "대기"),
            "비고":       a.get("remarks", ""),
        })
    df_edit_orig = pd.DataFrame(df_edit_data)

    # 클래스명 풀: DB에 존재하는 고유값 + 기본값 병합
    known_classes = sorted(
        {"사람", "멧돼지", "고라니"} | set(df_edit_orig["클래스명"].dropna().unique())
    )

    # num_rows="dynamic" → 기본 행 선택 체크박스 + 우상단 휴지통 UI 활성화
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
            "입력 소스": st.column_config.SelectboxColumn(
                "입력 소스", options=["video", "image"], required=True
            ),
            "클래스명": st.column_config.SelectboxColumn(
                "클래스명", options=known_classes, required=True
            ),
            "신뢰도 (%)": st.column_config.NumberColumn(
                "신뢰도 (%)",
                min_value=0.0, max_value=100.0,
                step=0.1, format="%.1f%%",
            ),
            "BBox 좌표": st.column_config.TextColumn(
                "BBox 좌표", help="수정 불가 (x1, y1, x2, y2)"
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

    # ── 저장 버튼 ──
    btn_col, _ = st.columns([2, 8])
    with btn_col:
        save_clicked = st.button(
            "💾 변경사항 저장", type="primary", use_container_width=True
        )

    if not save_clicked:
        return

    result = save_log_edits(df_edit_orig, edited_df)
    updated_count = result["updated_count"]
    removed_ids = result["removed_ids"]
    rds_errors = result["rds_errors"]

    # ── 결과 메시지 ──
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
