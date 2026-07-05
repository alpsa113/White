"""
services/log_management.py — 로그 편집/삭제 저장 처리

관리자 로그 화면의 data_editor에서 수정된 내용을 원본(df_edit_orig)과
비교하여 실제로 변경된 부분만 session_state·RDS·S3에 반영합니다.
UI(ui/log_tabs.py)는 이 모듈이 반환한 결과 딕셔너리를 화면에 표시만 하고,
DB/S3 관련 판단과 처리는 전부 이 모듈이 담당합니다.
"""
import pandas as pd
import streamlit as st

import db_rds as db
import s3_storage as s3


def _safe_int(val):
    """탐지 ID를 안전하게 int로 변환합니다. NaN/None 등 변환 불가한 값은 None을 반환합니다."""
    try:
        return int(val) if val is not None and not pd.isna(val) else None
    except (ValueError, TypeError):
        return None


def save_log_edits(df_edit_orig: pd.DataFrame, edited_df: pd.DataFrame) -> dict:
    """편집 탭에서 '변경사항 저장' 클릭 시 호출됩니다.

    삭제된 행 판별 방법: 휴지통으로 삭제된 행은 edited_df에서 사라지므로,
    원본 ID 집합에서 현재(수정 후) ID 집합을 빼면 삭제된 ID만 남습니다.
    수정된 행 판별 방법: 각 행을 원본과 컬럼별로 비교하여 하나라도 다르면 갱신 대상으로 처리합니다.

    Returns:
        dict: {"updated_count": int, "removed_ids": list[int], "rds_errors": list[str]}
    """
    ss = st.session_state
    DB_ENABLED = ss.get("DB_ENABLED", False)
    S3_ENABLED = ss.get("S3_ENABLED", False)

    updated_count = 0
    rds_errors: list[str] = []

    orig_id_set = {
        _safe_int(v) for v in df_edit_orig["탐지 ID"] if _safe_int(v) is not None
    }
    remaining_id_set = {
        _safe_int(v) for v in edited_df["탐지 ID"] if _safe_int(v) is not None
    }
    removed_ids = list(orig_id_set - remaining_id_set)

    # ── 수정 처리: edited_df에 남아 있는 행만 순회 ──
    for _, row in edited_df.iterrows():
        rid = _safe_int(row.get("탐지 ID"))
        # 원본에 없는 ID(예: 사용자가 새로 추가한 빈 행)는 저장 대상에서 제외
        if rid is None or rid not in orig_id_set:
            continue

        orig_rows = df_edit_orig[df_edit_orig["탐지 ID"].apply(_safe_int) == rid]
        if orig_rows.empty:
            continue
        orig = orig_rows.iloc[0]

        # 편집 가능한 컬럼들 중 하나라도 값이 달라졌으면 갱신 대상으로 판단
        changed = any(
            str(row[col]) != str(orig[col])
            for col in [
                "탐지 일시", "카메라", "입력 소스",
                "클래스명", "신뢰도 (%)", "상태", "비고",
            ]
        )
        if not changed:
            continue

        # 메모리(session_state)의 실제 로그 레코드를 찾아 갱신
        for a in ss.detection_logs:
            if a.get("id") != rid:
                continue
            a["created_at"] = str(row["탐지 일시"])
            a["camera"]     = str(row["카메라"])
            a["input_type"] = str(row["입력 소스"])
            a["class_name"] = str(row["클래스명"])
            a["score"]      = float(row["신뢰도 (%)"]) / 100.0
            a["status"]     = str(row["상태"])
            a["remarks"]    = str(row["비고"])
            if DB_ENABLED:
                try:
                    db.update_log(rid, a)
                except Exception as e:
                    rds_errors.append(f"ID {rid}: {e}")
            updated_count += 1
            break

    # ── 삭제 일괄 처리: RDS/S3/메모리 세 곳 모두에서 제거 ──
    if removed_ids:
        removed_keys = [
            a.get("uri", a.get("image_path", ""))
            for a in ss.detection_logs
            if a.get("id") in removed_ids
        ]
        if S3_ENABLED:
            s3.delete_snapshots(removed_keys)
        ss.detection_logs = [
            a for a in ss.detection_logs
            if a.get("id") not in removed_ids
        ]
        if DB_ENABLED:
            try:
                db.delete_logs(removed_ids)
            except Exception as e:
                rds_errors.append(f"RDS 삭제 오류: {e}")

    return {
        "updated_count": updated_count,
        "removed_ids": removed_ids,
        "rds_errors": rds_errors,
    }
