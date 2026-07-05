-- =========================================================
-- GOP Dual-YOLO Inference Database Schema
--
-- 테이블 목록:
--   1) model_versions   : 추론에 사용한 모델 checkpoint 이력
--   2) inference_jobs   : 이미지/영상 추론 요청 1건
--   3) storage_objects  : 입력·출력·썸네일 파일 저장 위치
--   4) inference_frames : 프레임 단위 추론 결과
--   5) detections       : bbox 1개당 1행
--
-- 공통 규칙:
--   - PK : BIGINT UNSIGNED AUTO_INCREMENT
--   - 시각 : DATETIME(2) NOT NULL DEFAULT CURRENT_TIMESTAMP(2)
--   - 상태/타입값 : VARCHAR (ENUM 미사용, 애플리케이션에서 검증)
--   - FK 삭제 정책:
--       inference_jobs.model_version_id → ON DELETE RESTRICT
--       나머지 모든 자식 테이블       → ON DELETE CASCADE
-- =========================================================

CREATE DATABASE IF NOT EXISTS gop_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE gop_db;

-- ---------------------------------------------------------
-- 1. 모델 버전
-- 추론에 사용한 모델 checkpoint와 설정 정보를 저장한다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_versions (
    id              BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '모델 버전 ID',
    name            VARCHAR(100)     NOT NULL               COMMENT '모델 버전 이름 (예: phase3_gop_best_20260623)',
    phase           TINYINT UNSIGNED          DEFAULT NULL  COMMENT '학습 phase (1/2/3). 외부 실험 모델은 NULL 가능',
    checkpoint_path VARCHAR(1024)    NOT NULL               COMMENT 'checkpoint 경로 (로컬 또는 S3 URI)',
    config_path     VARCHAR(1024)             DEFAULT NULL  COMMENT '모델 설정 파일 경로. 없으면 NULL',
    class_map       JSON             NOT NULL               COMMENT '추론 당시 클래스 ID-이름 매핑 (예: {"0":"person","1":"boar","2":"deer","3":"small_animal"})',
    notes           TEXT                      DEFAULT NULL  COMMENT '비고',
    created_at      DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2) COMMENT '생성 시각',
    PRIMARY KEY (id),
    INDEX idx_model_versions_phase      (phase),
    INDEX idx_model_versions_created_at (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='추론에 사용한 모델 checkpoint 및 설정 이력';

-- ---------------------------------------------------------
-- 2. 추론 작업
-- 이미지 또는 영상 추론 요청 1건을 저장한다.
-- 권장 status 값: queued / running / completed / failed / 대기 / 오탐 / 사람탐지(경보) / 동물탐지
-- 권장 input_type 값: image / video
-- 권장 input_modality 값: rgb / thermal / pair
-- 현재 구조에서는 탐지 1건이 곧 작업 1건이므로, status/remarks는 사실상
-- "이 탐지 건의 처리 상태/비고"로 사용된다.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS inference_jobs (
    id               BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '추론 작업 ID',
    model_version_id BIGINT UNSIGNED  NOT NULL               COMMENT '사용 모델 버전 ID (FK → model_versions)',
    camera           VARCHAR(100)              DEFAULT NULL  COMMENT '탐지가 발생한 CCTV 카메라 명',
    input_type       VARCHAR(20)      NOT NULL               COMMENT '입력 타입. 예: image, video',
    input_modality   VARCHAR(20)      NOT NULL               COMMENT '입력 모달리티. 예: rgb, thermal, pair',
    status           VARCHAR(30)      NOT NULL DEFAULT 'queued' COMMENT '작업 상태. queued / running / completed / failed / 대기 / 오탐 / 사람탐지(경보) / 동물탐지',
    remarks          VARCHAR(500)              DEFAULT NULL  COMMENT '관리자가 입력하는 비고',
    conf_thresh      DECIMAL(5,4)     NOT NULL DEFAULT 0.5000 COMMENT 'confidence threshold. 이 값 미만 bbox는 결과에서 제외. backend.py의 실제 적용값을 기록',
    nms_thresh       DECIMAL(5,4)     NOT NULL DEFAULT 0.4500 COMMENT 'NMS IoU threshold. 중복 bbox 제거 기준',
    frame_stride     INT UNSIGNED              DEFAULT NULL  COMMENT '영상 추론 frame stride. 이미지 추론은 NULL',
    max_frames       INT UNSIGNED              DEFAULT NULL  COMMENT '영상 추론 최대 처리 프레임 수. 제한 없으면 NULL',
    error_message    TEXT                      DEFAULT NULL  COMMENT '실패 사유. status=failed 일 때 기록',
    created_at       DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2) COMMENT '작업 생성 시각',
    started_at       DATETIME(2)               DEFAULT NULL  COMMENT '추론 시작 시각',
    completed_at     DATETIME(2)               DEFAULT NULL  COMMENT '추론 완료 시각',
    PRIMARY KEY (id),
    CONSTRAINT fk_jobs_model_version
        FOREIGN KEY (model_version_id)
        REFERENCES model_versions(id)
        ON DELETE RESTRICT,
    INDEX idx_jobs_model_version_id          (model_version_id),
    INDEX idx_jobs_status_created_at         (status, created_at),
    INDEX idx_jobs_input_type_created_at     (input_type, created_at),
    INDEX idx_jobs_input_modality_created_at (input_modality, created_at),
    INDEX idx_jobs_camera                    (camera),
    INDEX idx_jobs_created_at                (created_at)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='이미지/영상 추론 요청 1건';

-- ---------------------------------------------------------
-- 3. 저장 객체
-- 입력 파일, 출력 파일, 결과 JSON, 썸네일 등
-- 파일성 객체의 저장 위치를 관리한다.
-- 권장 object_type 값:
--   input_rgb / input_thermal / output_image /
--   output_video / result_json / thumbnail
-- 권장 storage_type 값: local / s3
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS storage_objects (
    id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '저장 객체 ID',
    job_id       BIGINT UNSIGNED  NOT NULL               COMMENT '추론 작업 ID (FK → inference_jobs)',
    object_type  VARCHAR(50)      NOT NULL               COMMENT '객체 종류. input_rgb / output_image / thumbnail 등',
    storage_type VARCHAR(20)      NOT NULL               COMMENT '저장소 타입. local / s3',
    uri          VARCHAR(1024)    NOT NULL               COMMENT '파일 위치. 로컬 경로 또는 S3 URI',
    content_type VARCHAR(100)              DEFAULT NULL  COMMENT 'MIME type. 예: image/jpeg, video/mp4',
    file_size    BIGINT UNSIGNED           DEFAULT NULL  COMMENT '파일 크기 (byte)',
    created_at   DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2) COMMENT '생성 시각',
    PRIMARY KEY (id),
    CONSTRAINT fk_storage_objects_job
        FOREIGN KEY (job_id)
        REFERENCES inference_jobs(id)
        ON DELETE CASCADE,
    INDEX idx_storage_job_id      (job_id),
    INDEX idx_storage_object_type (object_type)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='추론 작업의 입력/출력/썸네일 파일 저장 위치';

-- ---------------------------------------------------------
-- 4. 추론 프레임
-- 영상의 처리 프레임 단위 결과를 저장한다.
-- 이미지 추론도 동일 구조로 저장한다.
--   이미지: frame_index = 0, timestamp_ms = 0.000
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS inference_frames (
    id           BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '프레임 ID',
    job_id       BIGINT UNSIGNED  NOT NULL               COMMENT '추론 작업 ID (FK → inference_jobs)',
    frame_index  INT UNSIGNED     NOT NULL               COMMENT '원본 영상 기준 프레임 번호. 이미지는 0',
    timestamp_ms DECIMAL(12,3)    NOT NULL               COMMENT '영상 타임스탬프 ms. 이미지는 0.000',
    image_width  INT UNSIGNED     NOT NULL               COMMENT '원본 입력 이미지/프레임 너비 (픽셀)',
    image_height INT UNSIGNED     NOT NULL               COMMENT '원본 입력 이미지/프레임 높이 (픽셀)',
    latency_ms   DECIMAL(10,3)             DEFAULT NULL  COMMENT '해당 프레임 추론 소요 시간 (ms). 성능 모니터링용',
    created_at   DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2) COMMENT '생성 시각',
    PRIMARY KEY (id),
    CONSTRAINT fk_inference_frames_job
        FOREIGN KEY (job_id)
        REFERENCES inference_jobs(id)
        ON DELETE CASCADE,
    INDEX idx_frames_job_frame     (job_id, frame_index),
    INDEX idx_frames_job_timestamp (job_id, timestamp_ms)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='프레임 단위 추론 결과. 이미지 추론도 frame_index=0으로 동일 구조 사용';

-- ---------------------------------------------------------
-- 5. 탐지 결과
-- bbox 1개를 1행으로 저장한다.
-- bbox 좌표는 정규화 좌표가 아닌 원본 픽셀 좌표로 저장한다.
-- job_id는 frame_id로 역추적 가능하지만
-- 특정 job의 전체 bbox 빠른 조회를 위해 중복 저장한다.
-- class_id 매핑 (db_rds.py의 CLASS_ID_MAP과 반드시 동일하게 유지):
--   0=person(사람), 1=boar(멧돼지), 2=deer(고라니), 3=small_animal(소형동물),
--   99=정의되지 않은 클래스(UNKNOWN_CLASS_ID)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS detections (
    id         BIGINT UNSIGNED  NOT NULL AUTO_INCREMENT COMMENT '탐지 결과 ID',
    job_id     BIGINT UNSIGNED  NOT NULL               COMMENT '추론 작업 ID (FK → inference_jobs, 빠른 조회용 중복 저장)',
    frame_id   BIGINT UNSIGNED  NOT NULL               COMMENT '프레임 ID (FK → inference_frames)',
    class_id   INT UNSIGNED     NOT NULL               COMMENT '모델 출력 클래스 번호 (0=person, 1=boar, 2=deer, 3=small_animal, 99=미정의)',
    class_name VARCHAR(50)      NOT NULL               COMMENT '추론 당시 클래스 이름. 매핑 변경에 대비해 저장',
    score      DECIMAL(6,5)     NOT NULL               COMMENT 'confidence score. conf_thresh 통과한 결과만 저장',
    x1         DECIMAL(10,3)    NOT NULL               COMMENT 'bbox 좌상단 x 픽셀 좌표 (원본 이미지 기준)',
    y1         DECIMAL(10,3)    NOT NULL               COMMENT 'bbox 좌상단 y 픽셀 좌표 (원본 이미지 기준)',
    x2         DECIMAL(10,3)    NOT NULL               COMMENT 'bbox 우하단 x 픽셀 좌표 (원본 이미지 기준)',
    y2         DECIMAL(10,3)    NOT NULL               COMMENT 'bbox 우하단 y 픽셀 좌표 (원본 이미지 기준)',
    created_at DATETIME(2)      NOT NULL DEFAULT CURRENT_TIMESTAMP(2) COMMENT '생성 시각',
    PRIMARY KEY (id),
    CONSTRAINT fk_detections_job
        FOREIGN KEY (job_id)
        REFERENCES inference_jobs(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_detections_frame
        FOREIGN KEY (frame_id)
        REFERENCES inference_frames(id)
        ON DELETE CASCADE,
    INDEX idx_detections_job_id      (job_id),
    INDEX idx_detections_frame_id    (frame_id),
    INDEX idx_detections_class_score (class_id, score),
    INDEX idx_detections_job_class   (job_id, class_id)
) ENGINE=InnoDB
  DEFAULT CHARSET=utf8mb4
  COLLATE=utf8mb4_unicode_ci
  COMMENT='탐지 bbox 1개당 1행. 좌표는 원본 픽셀 기준';

-- ---------------------------------------------------------
-- 초기 데이터
-- 대시보드 최초 실행 시 inference_jobs.model_version_id
-- NOT NULL 제약을 만족시키기 위한 기본 모델 레코드
-- class_map은 실제 모델(backend.py)의 출력 라벨인 영문 기준으로 기록한다.
-- db_rds.py의 CLASS_ID_MAP과 항상 동일한 클래스 집합을 유지해야 한다.
-- ---------------------------------------------------------
INSERT IGNORE INTO model_versions
    (name, checkpoint_path, class_map, notes)
VALUES
    (
        'GOP YOLO (Default)',
        'weights/best.pt',
        '{"0":"person", "1":"boar", "2":"deer", "3":"small_animal"}',
        '자동 생성된 기본 모델'
    );
