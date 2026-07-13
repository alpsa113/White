from pathlib import Path
from fastapi import UploadFile

async def save_upload_video(file: UploadFile, output_path: Path) -> Path:
    content = await file.read()
    if not content:
        raise ValueError("업로드 영상 파일이 비어 있습니다.")
    output_path.write_bytes(content)
    return output_path