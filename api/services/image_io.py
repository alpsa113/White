from fastapi import UploadFile
import cv2
import numpy as np


async def _read_upload_bytes(file: UploadFile) -> bytes:
    content = await file.read()
    if not content:
        raise ValueError("업로드 파일이 비어 있습니다.")
    return content


def _decode_image(content: bytes, flags: int) -> np.ndarray:
    array = np.frombuffer(content, dtype=np.uint8)
    image = cv2.imdecode(array, flags)
    if image is None:
        raise ValueError("이미지 파일을 읽지 못했습니다.")
    return image


async def read_upload_rgb(file: UploadFile) -> np.ndarray:
    content = await _read_upload_bytes(file)
    image = _decode_image(content, cv2.IMREAD_COLOR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


async def read_upload_thermal(file: UploadFile) -> np.ndarray:
    content = await _read_upload_bytes(file)
    return _decode_image(content, cv2.IMREAD_GRAYSCALE)