"""
db_rds.py — GOP 탐지 로그 데이터베이스 연동 모듈

탐지 이벤트의 영구 저장을 위해 AWS RDS(MySQL)와 통신합니다.
추론 작업(jobs), 프레임(frames), 저장소(storage), 탐지 객체(detections)로
세분화된 관계형 테이블 구조에 맞춰 트랜잭션을 안전하게 관리합니다.

conf_thresh, latency_ms 등 추론 시점에 결정되는 값은 이 모듈이 직접 계산하지 않고,
프론트엔드가 backend.py의 응답을 그대로 전달해준 값을 받아 저장만 합니다.
"""

import pandas as pd
import streamlit as st
from sqlalchemy import text, event


# ------------------------------------------------------------------ #
# 클래스명 ↔ class_id 매핑 (insert_log, update_log 공용)
# ------------------------------------------------------------------ #
# 한글(데모 모드 시뮬레이션)과 영어(실제 모델 출력) 라벨을 모두 지원합니다.
# 정의되지 않은 클래스가 들어오면 기존 클래스(0/1/2/3)와 절대 섞이지 않도록
# 별도의 UNKNOWN_CLASS_ID로 격리합니다.
UNKNOWN_CLASS_ID = 99
CLASS_ID_MAP = {
    "사람": 0, "person": 0,
    "멧돼지": 1, "boar": 1,
    "고라니": 2, "deer": 2,
    "소형동물": 3, "small_animal": 3,
}


def resolve_class_id(class_name: str) -> int:
    """class_name 문자열을 class_id로 변환합니다. 매핑에 없으면 UNKNOWN_CLASS_ID를 반환합니다."""
    return CLASS_ID_MAP.get(class_name, CLASS_ID_MAP.get(class_name.lower(), UNKNOWN_CLASS_ID))


# ------------------------------------------------------------------ #
# 데이터베이스 연결 엔진 관리
# ------------------------------------------------------------------ #
@st.cache_resource
def get_engine():
    """SQLAlchemy 엔진을 생성하고 Streamlit 캐시로 애플리케이션 전반에서 재사용합니다."""
    engine = st.connection("gop_db", type="sql").engine

    @event.listens_for(engine, "connect")
    def set_kst_timezone(dbapi_connection, connection_record):
        # NOW(), CURRENT_TIMESTAMP가 모두 한국 시간 기준으로 계산됩니다.
        cursor = dbapi_connection.cursor()
        cursor.execute("SET time_zone = '+09:00'")
        cursor.close()

    return engine


# ------------------------------------------------------------------ #
# 데이터베이스 초기화 및 자동 생성
# ------------------------------------------------------------------ #
def init_db() -> bool:
    """
    DB 연결 가능 여부를 확인하고, 테이블이 없다면 시스템 구동에 필요한 5개 핵심 테이블을 자동 생성합니다.
    AWS RDS 등 새 환경에 배포할 때 별도의 SQL 실행 없이 앱 구동만으로 초기 세팅이 완료되도록 돕습니다.
    탐지 이벤트 발생 시 insert_log()에서 model_versions 행을 1:1로 함께 생성합니다.
    """
    setup_queries = [
        # 1. model_versions — 운영 중인 모델 정보
        """
        CREATE TABLE IF NOT EXISTS model_versions (
            id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
            name            VARCHAR(100)     NOT NULL,
            phase           TINYINT UNSIGNED          DEFAULT NULL,
            checkpoint_path VARCHAR(1024)    NOT NULL,
            config_path     VARCHAR(1024)             DEFAULT NULL,
            class_map       JSON             NOT NULL,
            notes           TEXT                      DEFAULT NULL,
            created_at      DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2),
            INDEX idx_model_versions_phase      (phase),
            INDEX idx_model_versions_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,

        # 2. inference_jobs — 탐지 작업(현재 구조에서는 탐지 1건) 단위 관리
        #    camera: 어느 CCTV 채널에서 발생한 작업인지
        #    remarks: 관리자 로그 화면에서 입력하는 비고
        #    conf_thresh: 해당 작업에 실제 적용된 신뢰도 임계값 (backend.py 응답값을 그대로 기록)
        """
        CREATE TABLE IF NOT EXISTS inference_jobs (
            id               BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
            model_version_id BIGINT UNSIGNED  NOT NULL,
            camera           VARCHAR(100)              DEFAULT NULL,
            input_type       VARCHAR(20)      NOT NULL,
            input_modality   VARCHAR(20)      NOT NULL,
            status           VARCHAR(30)      NOT NULL DEFAULT 'queued',
            remarks          VARCHAR(500)              DEFAULT NULL,
            conf_thresh      DECIMAL(5,4)     NOT NULL DEFAULT 0.5000,
            nms_thresh       DECIMAL(5,4)     NOT NULL DEFAULT 0.4500,
            frame_stride     INT UNSIGNED              DEFAULT NULL,
            max_frames       INT UNSIGNED              DEFAULT NULL,
            error_message    TEXT                      DEFAULT NULL,
            created_at       DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2),
            started_at       DATETIME(2)               DEFAULT NULL,
            completed_at     DATETIME(2)               DEFAULT NULL,
            CONSTRAINT fk_jobs_model_version FOREIGN KEY (model_version_id) REFERENCES model_versions(id) ON DELETE RESTRICT,
            INDEX idx_jobs_model_version_id          (model_version_id),
            INDEX idx_jobs_status_created_at         (status, created_at),
            INDEX idx_jobs_input_type_created_at     (input_type, created_at),
            INDEX idx_jobs_input_modality_created_at (input_modality, created_at),
            INDEX idx_jobs_camera                    (camera),
            INDEX idx_jobs_created_at                (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,

        # 3. storage_objects — 스냅샷 이미지 등 파일 경로 및 메타데이터 관리
        """
        CREATE TABLE IF NOT EXISTS storage_objects (
            id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
            job_id       BIGINT UNSIGNED  NOT NULL,
            object_type  VARCHAR(50)      NOT NULL,
            storage_type VARCHAR(20)      NOT NULL,
            uri          VARCHAR(1024)    NOT NULL,
            content_type VARCHAR(100)              DEFAULT NULL,
            file_size    BIGINT UNSIGNED           DEFAULT NULL,
            created_at   DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2),
            CONSTRAINT fk_storage_objects_job FOREIGN KEY (job_id) REFERENCES inference_jobs(id) ON DELETE CASCADE,
            INDEX idx_storage_job_id      (job_id),
            INDEX idx_storage_object_type (object_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,

        # 4. inference_frames — 영상 내 특정 프레임의 메타데이터 관리
        """
        CREATE TABLE IF NOT EXISTS inference_frames (
            id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
            job_id       BIGINT UNSIGNED  NOT NULL,
            frame_index  INT UNSIGNED     NOT NULL,
            timestamp_ms DECIMAL(12,3)    NOT NULL,
            image_width  INT UNSIGNED     NOT NULL,
            image_height INT UNSIGNED     NOT NULL,
            latency_ms   DECIMAL(10,3)             DEFAULT NULL,
            created_at   DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2),
            CONSTRAINT fk_inference_frames_job FOREIGN KEY (job_id) REFERENCES inference_jobs(id) ON DELETE CASCADE,
            INDEX idx_frames_job_frame     (job_id, frame_index),
            INDEX idx_frames_job_timestamp (job_id, timestamp_ms)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,

        # 5. detections — 개별 탐지 객체의 좌표 및 신뢰도 관리
        """
        CREATE TABLE IF NOT EXISTS detections (
            id         BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT PRIMARY KEY,
            job_id     BIGINT UNSIGNED  NOT NULL,
            frame_id   BIGINT UNSIGNED  NOT NULL,
            class_id   INT UNSIGNED     NOT NULL,
            class_name VARCHAR(50)      NOT NULL,
            score      DECIMAL(6,5)     NOT NULL,
            x1         DECIMAL(10,3)    NOT NULL,
            y1         DECIMAL(10,3)    NOT NULL,
            x2         DECIMAL(10,3)    NOT NULL,
            y2         DECIMAL(10,3)    NOT NULL,
            created_at DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2),
            CONSTRAINT fk_detections_job FOREIGN KEY (job_id) REFERENCES inference_jobs(id) ON DELETE CASCADE,
            CONSTRAINT fk_detections_frame FOREIGN KEY (frame_id) REFERENCES inference_frames(id) ON DELETE CASCADE,
            INDEX idx_detections_job_id      (job_id),
            INDEX idx_detections_frame_id    (frame_id),
            INDEX idx_detections_class_score (class_id, score),
            INDEX idx_detections_job_class   (job_id, class_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
        """,
    ]

    try:
        engine = get_engine()
        with engine.begin() as conn:
            for query in setup_queries:
                conn.execute(text(query))
        return True
    except Exception as e:
        # 권한 문제나 DB 접속 실패 시 에러를 세션에 기록하고 메모리 전용 모드로 작동하게 합니다.
        st.session_state["_db_init_error"] = str(e)
        return False


# ------------------------------------------------------------------ #
# 데이터(로그) 조회 (Read)
# ------------------------------------------------------------------ #
def fetch_all_logs() -> list[dict]:
    """
    분산된 여러 테이블을 JOIN하여 프론트엔드가 한눈에 보여줄 수 있도록 평탄화된 딕셔너리 리스트를 반환합니다.
    """
    engine = get_engine()
    sql = """
    SELECT
        d.id AS detection_id,
        j.id AS job_id,
        j.camera,
        j.status,
        j.remarks,
        f.frame_index,
        d.created_at,
        j.input_type,
        d.class_name,
        d.score,
        d.x1, d.y1, d.x2, d.y2,
        s.uri
    FROM detections d
    JOIN inference_frames f ON d.frame_id = f.id
    JOIN inference_jobs j ON d.job_id = j.id
    LEFT JOIN storage_objects s ON j.id = s.job_id AND s.object_type = 'thumbnail'
    ORDER BY d.created_at DESC, d.id DESC
    """
    df = pd.read_sql(sql, engine)

    logs = []
    for _, row in df.iterrows():
        logs.append({
            "id": int(row["detection_id"]),
            "job_id": int(row["job_id"]),
            "camera": row["camera"] if pd.notna(row["camera"]) else "",
            "status": row["status"] if pd.notna(row["status"]) else "대기",
            "remarks": row["remarks"] if pd.notna(row["remarks"]) else "",
            "frame_index": int(row["frame_index"]),
            "created_at": str(row["created_at"]),
            "input_type": row["input_type"],
            "class_name": row["class_name"],
            "score": float(row["score"]),
            "x1": float(row["x1"]),
            "y1": float(row["y1"]),
            "x2": float(row["x2"]),
            "y2": float(row["y2"]),
            "uri": row["uri"] if pd.notna(row["uri"]) else "",
        })
    return logs


# ------------------------------------------------------------------ #
# 데이터(로그) 생성 (Create)
# ------------------------------------------------------------------ #
def insert_log(rec: dict) -> int:
    """
    탐지 이벤트를 관계형 스키마에 맞춰 5개 테이블(model_versions, jobs, storage, frames, detections)에
    분산 저장합니다. 트랜잭션으로 묶여 있어 중간에 오류가 발생하면 전체가 롤백됩니다.

    rec는 frontend의 create_detection_alert()가 만든 딕셔너리로, image_width/height, timestamp_ms,
    latency_ms, conf_thresh 등 추론 시점에 결정되는 값들을 이미 담고 있습니다. 이 함수는 그 값을
    그대로 저장할 뿐, 별도의 기본값 정책을 갖지 않습니다(없으면 컬럼 자체의 DEFAULT가 적용됩니다).
    """
    engine = get_engine()
    box = rec.get("box", {"x1": 0.0, "y1": 0.0, "x2": 0.0, "y2": 0.0})

    # source(한글)가 아니라 input_type(영문)이 record에 이미 있으면 그 값을 우선 사용합니다.
    input_type = rec.get("input_type") or ("video" if rec.get("source") == "영상" else "image")

    with engine.begin() as conn:
        # 0. model_versions — 탐지 1건당 모델 정보 1행 생성
        sql_model = text("""
            INSERT INTO model_versions (name, checkpoint_path, class_map, notes)
            VALUES ('GOP YOLO (Default)', 'weights/best.pt',
                    '{"0":"person", "1":"boar", "2":"deer", "3":"small_animal"}', '탐지 이벤트 자동 생성')
        """)
        model_version_id = conn.execute(sql_model).lastrowid

        # 1. inference_jobs — 작업 단위 메타데이터
        #    conf_thresh가 전달된 경우(backend 응답 기반)에는 그 값을 그대로 기록하고,
        #    전달되지 않은 경우(데모 모드 등)에는 컬럼 자체의 DEFAULT를 사용합니다.
        job_params = {
            "model_version_id": model_version_id,
            "camera":     rec.get("camera", ""),
            "input_type": input_type,
            "status":     rec.get("status", "대기"),
            "remarks":    rec.get("remarks", ""),
            "latency_sec": float(rec.get("latency_ms", 0.0)) / 1000.0,
        }

        # conf_thresh, nms_thresh 둘 다 전달된 경우에만 SQL에 포함시키고,
        # 없으면 컬럼 자체의 DEFAULT(0.4500)에 위임합니다.
        extra_cols = []
        extra_vals = []
        if rec.get("conf_thresh") is not None:
            extra_cols.append("conf_thresh")
            extra_vals.append(":conf_thresh")
            job_params["conf_thresh"] = rec["conf_thresh"]
        if rec.get("nms_thresh") is not None:
            extra_cols.append("nms_thresh")
            extra_vals.append(":nms_thresh")
            job_params["nms_thresh"] = rec["nms_thresh"]

        extra_cols_sql = ("," + ", ".join(extra_cols)) if extra_cols else ""
        extra_vals_sql = ("," + ", ".join(extra_vals)) if extra_vals else ""

        sql_job = text(f"""
            INSERT INTO inference_jobs
                (model_version_id, camera, input_type, input_modality, status, remarks,
                started_at, completed_at{extra_cols_sql})
            VALUES
                (:model_version_id, :camera, :input_type, 'rgb', :status, :remarks,
                NOW(6) - INTERVAL :latency_sec SECOND, NOW(6){extra_vals_sql})
        """)
        job_id = conn.execute(sql_job, job_params).lastrowid

        # 2. storage_objects — 스냅샷 이미지가 있을 때만 생성
        uri = rec.get("image_path", "")
        if uri:
            storage_type = 's3' if uri.startswith('detections/') or uri.startswith('s3://') else 'local'
            sql_storage = text("""
                INSERT INTO storage_objects
                    (job_id, object_type, storage_type, uri, content_type, file_size)
                VALUES
                    (:job_id, 'thumbnail', :storage_type, :uri, :content_type, :file_size)
            """)
            conn.execute(sql_storage, {
                "job_id":       job_id,
                "storage_type": storage_type,
                "uri":          uri,
                "content_type": rec.get("content_type", "image/jpeg"),
                "file_size":    rec.get("file_size"),
            })

        # 3. inference_frames — 프레임 메타데이터 (해상도, 타임스탬프, 추론 지연시간)
        frame_idx = int(rec.get("hit_frames", 0)) if input_type == 'video' else 0
        sql_frame = text("""
            INSERT INTO inference_frames
                (job_id, frame_index, timestamp_ms, image_width, image_height, latency_ms)
            VALUES
                (:job_id, :frame_index, :timestamp_ms, :image_width, :image_height, :latency_ms)
        """)
        frame_id = conn.execute(sql_frame, {
            "job_id":       job_id,
            "frame_index":  frame_idx,
            "timestamp_ms": float(rec.get("timestamp_ms", 0.0)),
            "image_width":  int(rec.get("image_width", 1920)),
            "image_height": int(rec.get("image_height", 1080)),
            "latency_ms":   float(rec.get("latency_ms", 0.0)),
        }).lastrowid

        # 4. detections — 탐지 객체 좌표 및 신뢰도
        class_name = rec.get("class_name", "")
        sql_det = text("""
            INSERT INTO detections (job_id, frame_id, class_id, class_name, score, x1, y1, x2, y2)
            VALUES (:job_id, :frame_id, :class_id, :class_name, :score, :x1, :y1, :x2, :y2)
        """)
        res_det = conn.execute(sql_det, {
            "job_id":     job_id,
            "frame_id":   frame_id,
            "class_id":   resolve_class_id(class_name),
            "class_name": class_name,
            "score":      float(rec.get("confidence", 0.0)),
            "x1": box.get("x1", 0.0),
            "y1": box.get("y1", 0.0),
            "x2": box.get("x2", 0.0),
            "y2": box.get("y2", 0.0),
        })

        return int(res_det.lastrowid)


# ------------------------------------------------------------------ #
# 데이터(로그) 수정 (Update)
# ------------------------------------------------------------------ #
def update_log(aid: int, rec: dict) -> None:
    """
    탐지 ID(aid) 기준으로 detections와 inference_jobs 테이블을 한 트랜잭션 내에서 갱신합니다.

    - detections: class_name, class_id, score
    - inference_jobs: camera, input_type, status, remarks
    """
    engine = get_engine()

    class_name = rec.get("class_name", "")
    class_id   = resolve_class_id(class_name)
    score      = float(rec.get("score", rec.get("confidence", 0.0)))
    camera     = rec.get("camera", "")
    input_type = rec.get("input_type", "image")
    status     = rec.get("status", "대기")
    remarks    = rec.get("remarks", "")

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE detections
                SET class_name = :class_name,
                    class_id   = :class_id,
                    score      = :score
                WHERE id = :aid
            """),
            {"class_name": class_name, "class_id": class_id, "score": score, "aid": int(aid)},
        )

        # job_id를 알면 직접 업데이트하고, 모르면 detections와의 JOIN으로 간접 업데이트합니다.
        job_id = rec.get("job_id")
        if job_id:
            conn.execute(
                text("""
                    UPDATE inference_jobs
                    SET camera     = :camera,
                        input_type = :input_type,
                        status     = :status,
                        remarks    = :remarks
                    WHERE id = :job_id
                """),
                {
                    "camera": camera, "input_type": input_type,
                    "status": status, "remarks": remarks,
                    "job_id": int(job_id),
                },
            )
        else:
            conn.execute(
                text("""
                    UPDATE inference_jobs ij
                    JOIN detections d ON d.job_id = ij.id
                    SET ij.camera     = :camera,
                        ij.input_type = :input_type,
                        ij.status     = :status,
                        ij.remarks    = :remarks
                    WHERE d.id = :aid
                """),
                {
                    "camera": camera, "input_type": input_type,
                    "status": status, "remarks": remarks,
                    "aid": int(aid),
                },
            )


# ------------------------------------------------------------------ #
# 데이터(로그) 일괄 삭제 (Delete)
# ------------------------------------------------------------------ #
def delete_logs(ids: list[int]) -> None:
    """
    삭제할 탐지 ID에 연결된 최상위 Job을 찾아 삭제합니다.
    CASCADE 규칙에 따라 연결된 프레임, 스토리지, 탐지 객체가 함께 삭제됩니다.
    model_versions는 inference_jobs에 ON DELETE RESTRICT가 걸려 있어 jobs 삭제 후 별도 삭제합니다.
    """
    if not ids:
        return
    engine = get_engine()
    placeholders = ", ".join(str(int(i)) for i in ids)

    with engine.begin() as conn:
        sql_find = text(f"""
            SELECT DISTINCT j.id AS job_id, j.model_version_id
            FROM detections d
            JOIN inference_jobs j ON d.job_id = j.id
            WHERE d.id IN ({placeholders})
        """)
        rows = conn.execute(sql_find).fetchall()
        jobs_to_delete = [r[0] for r in rows]
        model_versions_to_delete = [r[1] for r in rows]

        if jobs_to_delete:
            job_placeholders = ", ".join(str(j) for j in jobs_to_delete)
            conn.execute(text(f"DELETE FROM inference_jobs WHERE id IN ({job_placeholders})"))

        if model_versions_to_delete:
            mv_placeholders = ", ".join(str(m) for m in model_versions_to_delete)
            conn.execute(text(f"DELETE FROM model_versions WHERE id IN ({mv_placeholders})"))
