"""services/log_management.py — 로그 편집/삭제 저장 처리.

카메라 워커가 별도 프로세스로 분리되면서 각자 RDS에 직접 기록하므로, 메인 프로세스의
메모리 리스트(state_store.detection_logs)는 더 이상 신뢰할 수 있는 원본이 아닙니다.
RDS가 켜져 있으면 항상 RDS를 직접 조회·수정합니다."""
import db_rds as db
import s3_storage as s3
import state_store as store


def save_log_edits(updates: list[dict], deletes: list[int]) -> dict:
    """로그 편집 탭 저장 시 변경/삭제된 행만 반영합니다.

    updates: [{"id": int, "class_name"?, "score"?(0~1), "camera"?, "status"?, "remarks"?}]
    deletes: [id, ...]

    Returns:
        dict: {"updated_count": int, "removed_ids": list[int], "rds_errors": list[str]}
    """
    DB_ENABLED = store.status.get("db_enabled", False)
    S3_ENABLED = store.status.get("s3_enabled", False)

    updated_count = 0
    removed_ids: list[int] = []
    rds_errors: list[str] = []

    if DB_ENABLED:
        try:
            current = {row["id"]: row for row in db.fetch_all_logs()}
        except Exception as e:
            rds_errors.append(f"RDS 조회 실패: {e}")
            current = {}

        for upd in updates:
            rid = upd.get("id")
            row = current.get(rid)
            if rid is None or row is None:
                continue
            merged = {
                "class_name": upd.get("class_name", row["class_name"]),
                "score": upd.get("score", row["score"]),
                "camera": upd.get("camera", row["camera"]),
                "input_type": row["input_type"],
                "status": upd.get("status", row["status"]),
                "remarks": upd.get("remarks", row["remarks"]),
                "job_id": row["job_id"],
            }
            try:
                db.update_log(rid, merged)
                updated_count += 1
            except Exception as e:
                rds_errors.append(f"ID {rid}: {e}")

        removed_ids = [i for i in deletes if i in current]
        if removed_ids:
            removed_keys = [current[i].get("uri", "") for i in removed_ids]
            if S3_ENABLED:
                s3.delete_snapshots(removed_keys)
            try:
                db.delete_logs(removed_ids)
            except Exception as e:
                rds_errors.append(f"RDS 삭제 오류: {e}")

    else:
        # DB 미사용(메모리 전용) 데모 모드 — 정지 이미지 등 메인 프로세스에서 직접 처리한
        # 항목만 이 리스트에 쌓입니다.
        for upd in updates:
            rid = upd.get("id")
            if rid is None:
                continue
            for a in store.detection_logs:
                if a.get("id") != rid:
                    continue
                for field in ("class_name", "camera", "status", "remarks"):
                    if field in upd:
                        a[field] = upd[field]
                if "score" in upd:
                    a["score"] = float(upd["score"])
                updated_count += 1
                break

        removed_ids = [i for i in deletes if any(a.get("id") == i for a in store.detection_logs)]
        if removed_ids:
            removed_keys = [
                a.get("uri", a.get("image_path", ""))
                for a in store.detection_logs
                if a.get("id") in removed_ids
            ]
            if S3_ENABLED:
                s3.delete_snapshots(removed_keys)
            store.detection_logs[:] = [a for a in store.detection_logs if a.get("id") not in removed_ids]

    return {
        "updated_count": updated_count,
        "removed_ids": removed_ids,
        "rds_errors": rds_errors,
    }
