"""
ui/log_tabs.py — 탐지 데이터 로그 페이지의 두 탭(조회 / 편집) 렌더링

탭1(render_view_tab)은 표 + 선택한 행의 탐지 이미지를 보여주는 조회 전용 화면이고,
탭2(render_manage_tab)는 st.data_editor 기반으로 실제 수정/삭제가 가능한 편집 화면입니다.
저장 로직 자체는 services/log_management.py에 위임하고, 이 파일은 화면 구성과
사용자 입력 수집만 담당합니다.
"""
import pandas as pd
import streamlit as st

import s3_storage as s3
from services.log_management import save_log_edits
from utils.formatters import fmt_dt, fmt_src, fmt_bbox


def _build_view_df(sorted_logs: list[dict]) -> pd.DataFrame:
    """조회 탭에 표시할 DataFrame을 구성합니다. 정렬은 호출 측(views/logs.py)에서
    이미 끝난 상태로 넘어오므로, 여기서는 컬럼 매핑/포맷팅만 수행합니다."""
    df_data = []
    for a in sorted_logs:
        df_data.append({
            "탐지 ID":        a.get("id"),
            "카메라":         a.get("camera", ""),
            "탐지 일시":      fmt_dt(a),
            "클래스명":       a.get("class_name", ""),
            "신뢰도 (Score)": f"{float(a.get('score', a.get('confidence', 0))):.1%}",
            "이미지 URI":     a.get("uri", a.get("image_path", "")),  # 표에는 안 보이고 이미지 로딩용으로만 사용
        })
    return pd.DataFrame(df_data)


def render_view_tab(sorted_logs: list[dict]) -> None:
    """탭1 — 로그 조회 표 + 선택한 행의 탐지 이미지 뷰어를 좌우로 배치합니다."""
    ss = st.session_state
    df = _build_view_df(sorted_logs)

    view_col, img_col = st.columns([6, 4])

    with view_col:
        # 경로가 긴 이미지 URI는 표에서 숨겨 가독성을 확보 (이미지 열람 자체는 img_col에서 처리)
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
            # 인덱스가 아니라 탐지 ID를 저장해두는 이유: rerun 후 데이터가 재정렬되어도
            # ID 기준으로 다시 찾을 수 있어 "범위 초과" 오류를 피할 수 있습니다.
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

        # ID로 직접 로그를 찾으므로, 리스트 순서가 바뀌어도 항상 올바른 레코드를 가리킴
        sel_log = next((a for a in ss.detection_logs if a.get("id") == sel_log_id), None)
        _df_match = df[df["탐지 ID"] == sel_log_id]
        sel_row = _df_match.iloc[0] if not _df_match.empty else None

        if sel_log is None or sel_row is None:
            st.warning("선택된 로그를 찾을 수 없습니다.")
            ss["selected_log_id"] = None  # 삭제 등으로 무효해진 선택은 초기화
            return

        snap = sel_log.get("snapshot")
        image_uri = sel_log.get("uri", sel_log.get("image_path", ""))

        st.markdown(
            f"**카메라: {sel_log.get('camera', '-')}** &nbsp; | &nbsp; "
            f"클래스: `{sel_log.get('class_name', '')}` &nbsp; | &nbsp; "
            f"Score: **{float(sel_log.get('score', sel_log.get('confidence', 0))):.1%}**",
            unsafe_allow_html=True
        )
        st.caption(f"탐지시각: {fmt_dt(sel_log)}")
        st.divider()

        # 이미지 로딩 우선순위: 메모리 스냅샷(이번 세션 탐지) → S3 다운로드(과거 이력)
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
    """탭2 — st.data_editor로 로그를 직접 수정하거나 행을 삭제할 수 있는 관리 화면입니다.
    실제 저장(DB/S3/메모리 반영)은 이 함수가 아니라 save_log_edits()가 담당합니다."""
    ss = st.session_state

    st.caption(
        "셀을 직접 클릭하여 수정할 수 있습니다. "
        "삭제할 행은 왼쪽 체크박스로 선택한 뒤 우상단 **🗑️ 휴지통** 버튼을 누르세요. "
        "**변경사항 저장** 버튼을 누르면 수정·삭제가 RDS에 즉시 반영됩니다."
    )

    # ── 편집용 DataFrame 빌드 ──
    df_edit_data = []
    for a in sorted_logs:
        df_edit_data.append({
            "탐지 ID":    a.get("id"),                                    # PK — 수정 불가
            "탐지 일시":  fmt_dt(a),
            "카메라":     a.get("camera", ""),
            "클래스명":   a.get("class_name", ""),
            "신뢰도 (%)": round(float(a.get("score", a.get("confidence", 0))) * 100, 1),
            "이미지 경로": a.get("uri", a.get("image_path", "")),
            "상태":       a.get("status", "대기"),
            "비고":       a.get("remarks", ""),
        })
    df_edit_orig = pd.DataFrame(df_edit_data)

    # 클래스명 드롭다운 선택지: 기본 클래스 + 현재 로그에 실제로 존재하는 클래스를 합쳐서 구성
    known_classes = sorted(
        {"사람", "멧돼지", "고라니", "소형동물"} | set(df_edit_orig["클래스명"].dropna().unique())
    )

    # num_rows="dynamic" 옵션이 행 선택 체크박스와 우상단 휴지통(삭제) UI를 함께 활성화합니다.
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

    # ── 저장 버튼 ──
    btn_col, _ = st.columns([2, 8])
    with btn_col:
        save_clicked = st.button(
            "변경사항 저장", type="primary", use_container_width=True
        )

    if not save_clicked:
        return

    # 실제 비교/저장 로직은 전부 services 계층에 위임 — 이 함수는 결과만 받아 표시
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
