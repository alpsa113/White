"""
s3_storage.py — GOP 탐지 스냅샷 이미지 S3 저장 모듈

탐지 순간의 캡처 이미지를 클라우드 저장소(AWS S3)에 업로드하고, 저장된 경로(URI Key)를 반환합니다.
데이터베이스에는 무거운 이미지 파일이 아닌 이 문자열 경로만 가볍게 저장하여 효율성을 높입니다.

secrets.toml 파일의 [s3] 섹션에 버킷 이름과 권한 키를 설정하면 자동으로 활성화됩니다.
"""

import io
import uuid
from datetime import datetime

import boto3
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError


# ------------------------------------------------------------------ #
# S3 클라이언트 — Streamlit 캐시로 1회만 생성하여 재사용
# ------------------------------------------------------------------ #
@st.cache_resource
def get_s3_client():
    """
    boto3를 이용해 S3 통신 클라이언트를 생성합니다.
    Streamlit의 캐시 기능을 이용해 한 번만 로그인하여 연결을 유지하므로 통신 속도가 빠릅니다.
    """
    cfg = st.secrets["s3"]
    return boto3.client(
        "s3",
        region_name=cfg["region"],
        aws_access_key_id=cfg["access_key_id"],
        aws_secret_access_key=cfg["secret_access_key"],
    )


def _bucket() -> str:
    """설정 파일에서 버킷(S3의 최상위 폴더 개념) 이름을 가져옵니다."""
    return st.secrets["s3"]["bucket"]


def is_enabled() -> bool:
    """설정 파일(secrets.toml)에 [s3] 정보가 채워져 있는지 확인하여 S3 기능 활성화 여부를 결정합니다."""
    try:
        _ = st.secrets["s3"]["bucket"]
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ #
# 이미지 업로드 (Create)
# ------------------------------------------------------------------ #
def upload_snapshot(pil_img, camera: str) -> str | None:
    """
    탐지된 화면(PIL 이미지)을 JPEG로 변환해 S3에 업로드하고, 저장된 경로(객체 키)를 반환합니다.

    키 구조: detections/2026-06-23/CCTV-01_a1b2c3d4.jpg
      → 날짜별 폴더로 자동 분류되어, 추후 클라우드 관리 콘솔에서 직접 찾아볼 때 매우 편리합니다.

    Args:
        pil_img: 업로드할 PIL.Image 형태의 스냅샷 객체
        camera : 카메라 이름 (중복 방지를 위해 파일명에 포함)
    Returns:
        str : S3에 저장된 최종 경로 문자열 (업로드 실패 시 None)
    """
    if pil_img is None:
        return None

    try:
        client = get_s3_client()

        # 이미지를 하드디스크에 저장하지 않고, 메모리 공간(BytesIO) 상에서 바로 변환하여 속도를 높입니다.
        buffer = io.BytesIO()
        pil_img.convert("RGB").save(buffer, format="JPEG", quality=85)
        buffer.seek(0)

        # 파일명 충돌을 막기 위해 날짜와 짧은 난수(UUID)를 조합합니다.
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


# ------------------------------------------------------------------ #
# 이미지 조회용 URL 발급 (Read)
# ------------------------------------------------------------------ #
def get_presigned_url(key: str, expires: int = 3600) -> str | None:
    """
    S3에 저장된 사진을 브라우저에서 볼 수 있도록 '일시적인 접근 주소(Presigned URL)'를 만듭니다.
    버킷을 외부 비공개(Private) 상태로 안전하게 유지하면서도, 이 주소를 통해서만 1시간 동안 열람할 수 있게 해줍니다.

    Args:
        key     : upload_snapshot 함수가 반환했던 저장 경로(객체 키)
        expires : 주소의 유효 시간 (초 단위, 기본 1시간)
    Returns:
        str : 접근 가능한 임시 웹 주소 (실패 시 None)
    """
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


# ------------------------------------------------------------------ #
# 이미지 다운로드 (Read) — 브라우저 보안(CORS) 우회용
# ------------------------------------------------------------------ #
def download_snapshot(key: str) -> bytes | None:
    """
    S3에 저장된 이미지를 백엔드 파이썬 서버가 직접 다운로드하여 바이트(bytes) 데이터로 반환합니다.

    브라우저 보안 규칙(CORS) 때문에 S3 주소를 화면에 바로 띄우면 이미지가 차단되는 경우가 있습니다.
    이 함수는 서버 측에서 데이터를 미리 가져와 Streamlit에 직접 전달함으로써 보안 차단 문제를 완벽하게 우회합니다.
    """
    if not key:
        return None
    try:
        client = get_s3_client()
        response = client.get_object(Bucket=_bucket(), Key=key)
        return response["Body"].read()
    except (BotoCoreError, ClientError, KeyError) as e:
        st.session_state["s3_write_warning"] = f"S3 이미지 다운로드 실패: {e}"
        return None


# ------------------------------------------------------------------ #
# 이미지 삭제 (Delete)
# ------------------------------------------------------------------ #
def delete_snapshots(keys: list[str]) -> None:
    """사용자가 시스템에서 로그를 삭제할 때, S3 클라우드 공간을 차지하고 있는 실제 이미지 파일도 함께 정리합니다."""
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


# ------------------------------------------------------------------ #
# 탐지 전후 클립 업로드 (Create) — 스냅샷 이미지 대신 짧은 영상을 저장하는 기능용
# ------------------------------------------------------------------ #
def upload_clip(local_path: str, camera: str) -> str | None:
    """이미 로컬에 인코딩되어 있는 짧은 mp4 클립 파일을 S3에 업로드하고,
    저장된 경로(객체 키)를 반환합니다. upload_snapshot()과 동일한 날짜별 폴더
    구조를 쓰되 확장자만 .mp4로 다릅니다.

    Args:
        local_path: 이미 인코딩되어 디스크에 저장된 mp4 파일 경로
        camera    : 카메라 이름 (파일명 구분용)
    Returns:
        str : S3에 저장된 최종 경로 문자열 (업로드 실패 시 None)
    """
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