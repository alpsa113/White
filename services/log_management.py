"""services/log_management.py — 로그 편집/삭제 저장 처리. 원본과 비교해 변경분만 반영합니다."""
import pandas as pd
import streamlit as st

import db_rds as db
import s3_storage as s3


def _safe_int(val):
    """값을 안전하게 int로 변환합니다. 실패하면 None."""
    try:
        return int(val) if val is not None and not pd.isna(val) else None
    except (ValueError, TypeError):
        return None


def save_log_edits(df_edit_orig: pd.DataFrame, edited_df: pd.DataFrame) -> dict:
    """편집 탭 저장 시 변경/삭제된 행만 session_state·RDS·S3에 반영합니다.

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

    for _, row in edited_df.iterrows():
        rid = _safe_int(row.get("탐지 ID"))
        if rid is None or rid not in orig_id_set:
            continue

        orig_rows = df_edit_orig[df_edit_orig["탐지 ID"].apply(_safe_int) == rid]
        if orig_rows.empty:
            continue
        orig = orig_rows.iloc[0]

        changed = any(
            str(row[col]) != str(orig[col])
            for col in [
                "탐지 일시", "카메라",
                "클래스명", "신뢰도 (%)", "상태", "비고",
            ]
        )
        if not changed:
            continue

        for a in ss.detection_logs:
            if a.get("id") != rid:
                continue
            a["created_at"] = str(row["탐지 일시"])
            a["camera"]     = str(row["카메라"])
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
