"""s3_storage.py — GOP 탐지 스냅샷/클립 이미지를 S3에 저장하는 모듈. secrets.toml [s3] 설정 시 자동 활성화됩니다."""

import io
import uuid
from datetime import datetime

import boto3
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError


@st.cache_resource
def get_s3_client():
    """boto3 S3 클라이언트를 생성하고 캐시로 재사용합니다."""
    cfg = st.secrets["s3"]
    return boto3.client(
        "s3",
        region_name=cfg["region"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
    )


def _bucket() -> str:
    """설정 파일에서 버킷 이름을 가져옵니다."""
    return st.secrets["s3"]["bucket"]


def is_enabled() -> bool:
    """secrets.toml에 [s3] 설정이 있는지 확인합니다."""
    try:
        _ = st.secrets["s3"]["bucket"]
        return True
    except Exception:
        return False


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
        st.session_state["s3_write_warning"] = f"S3 업로드 실패: {e}"
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
        st.session_state["s3_write_warning"] = f"S3 URL 발급 실패: {e}"
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
        st.session_state["s3_write_warning"] = f"S3 이미지 다운로드 실패: {e}"
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
        st.session_state["s3_write_warning"] = f"S3 삭제 실패: {e}"


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
        st.session_state["s3_write_warning"] = f"S3 클립 업로드 실패: {e}"
        return None
