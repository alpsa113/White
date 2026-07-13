"""s3_storage.py — GOP 탐지 스냅샷/클립 이미지를 S3에 저장하는 모듈. S3_* 환경변수 설정 시 자동 활성화됩니다."""

import io
import os
import uuid
from datetime import datetime
from functools import lru_cache

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
    HAS_BOTO3 = True
except ImportError:
    boto3 = None
    Config = None
    BotoCoreError = ClientError = Exception
    HAS_BOTO3 = False

# boto3 기본 타임아웃(연결 60초/응답 60초)은 실시간 탐지 파이프라인에 너무 깁니다. 네트워크가
# 잠깐 불안정할 때 이 호출 하나가 카메라 탐지 스레드를 수십 초씩 묶어두는 걸 막기 위해 짧게 강제합니다.
_S3_CONFIG = (
    Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 1})
    if HAS_BOTO3
    else None
)

_last_s3_warning: str | None = None


def get_last_warning() -> str | None:
    """가장 최근 S3 작업 실패 시의 경고 메시지를 반환합니다(성공/미실행 시 None)."""
    return _last_s3_warning


def _set_warning(message: str) -> None:
    global _last_s3_warning
    _last_s3_warning = message


@lru_cache(maxsize=1)
def get_s3_client():
    """boto3 S3 클라이언트를 생성하고 프로세스 전체에서 재사용합니다."""
    if not HAS_BOTO3:
        raise RuntimeError("boto3가 설치되지 않아 S3 저장소를 사용할 수 없습니다.")
    return boto3.client(
        "s3",
        region_name=os.environ["S3_REGION"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=_S3_CONFIG,
    )


def _bucket() -> str:
    """환경변수에서 버킷 이름을 가져옵니다."""
    return os.environ["S3_BUCKET"]


def is_enabled() -> bool:
    """S3 의존성과 필수 환경변수가 준비되어 있는지 확인합니다."""
    required = ("S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    return HAS_BOTO3 and all(os.environ.get(key) for key in required)


def upload_snapshot(pil_img, camera: str) -> str | None:
    """탐지 스냅샷을 JPEG로 S3에 업로드하고 객체 키를 반환합니다(실패 시 None)."""
    if pil_img is None:
        return None

    try:
        client = get_s3_client()

        buffer = io.BytesIO()
        pil_img.convert("RGB").save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        safe_cam = "".join(c if c.isalnum() else "_" for c in camera)
        date_dir = datetime.now().strftime("%Y-%m-%d")
        key = f"detections/{date_dir}/{safe_cam}_{uuid.uuid4().hex[:8]}.jpg"

        client.upload_fileobj(
            buffer,
            _bucket(),
            key,
            ExtraArgs={"ContentType": "image/jpeg"},
        )
        return key

    except (BotoCoreError, ClientError, KeyError) as e:
        _set_warning(f"S3 업로드 실패: {e}")
        return None


def get_presigned_url(key: str, expires: int = 3600) -> str | None:
    """S3 객체의 임시 접근 URL(기본 1시간)을 발급합니다."""
    if not key:
        return None
    try:
        client = get_s3_client()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key},
            ExpiresIn=expires,
        )
    except (BotoCoreError, ClientError, KeyError) as e:
        _set_warning(f"S3 URL 발급 실패: {e}")
        return None


def download_snapshot(key: str) -> bytes | None:
    """S3 이미지를 서버가 직접 다운로드해 바이트로 반환합니다(CORS 우회)."""
    if not key:
        return None
    try:
        client = get_s3_client()
        response = client.get_object(Bucket=_bucket(), Key=key)
        return response["Body"].read()
    except (BotoCoreError, ClientError, KeyError) as e:
        _set_warning(f"S3 이미지 다운로드 실패: {e}")
        return None


def delete_snapshots(keys: list[str]) -> None:
    """로그 삭제 시 S3의 해당 이미지 파일도 함께 정리합니다."""
    valid = [k for k in keys if k]
    if not valid:
        return
    try:
        client = get_s3_client()
        client.delete_objects(
            Bucket=_bucket(),
            Delete={"Objects": [{"Key": k} for k in valid]},
        )
    except (BotoCoreError, ClientError, KeyError) as e:
        _set_warning(f"S3 삭제 실패: {e}")


def upload_clip(local_path: str, camera: str) -> str | None:
    """로컬에 인코딩된 mp4 클립을 S3에 업로드하고 객체 키를 반환합니다(실패 시 None)."""
    try:
        client = get_s3_client()
        safe_cam = "".join(c if c.isalnum() else "_" for c in camera)
        date_dir = datetime.now().strftime("%Y-%m-%d")
        key = f"detections/{date_dir}/{safe_cam}_{uuid.uuid4().hex[:8]}.mp4"

        client.upload_file(
            local_path,
            _bucket(),
            key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
        return key

    except (BotoCoreError, ClientError, KeyError) as e:
        _set_warning(f"S3 클립 업로드 실패: {e}")
        return None
