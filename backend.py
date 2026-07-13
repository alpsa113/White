"""backend.py — GOP 탐지 시스템 FastAPI 서버.

React 프론트엔드가 소비하는 REST API를 제공합니다. 영상은 브라우저가 원본 파일을 그대로
재생하고, 탐지 결과는 영상 지정 시 한 번 백그라운드에서 미리 분석해(services/video_analyzer.py)
캐싱해둔 뒤 재생 시간에 맞춰 프론트가 동기화해서 그립니다.

실행: uvicorn backend:app --reload --port 8000
"""
import io

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from PIL import Image

import db_rds as db
import s3_storage as s3
import state_store as store
from services import model_runtime
from services import video_analyzer
from services.audio_alert import beep_wav_bytes
from routers import auth, outposts, cameras, tracking, settings, logs

app = FastAPI(title="GOP 탐지 시스템 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(outposts.router)
app.include_router(cameras.router)
app.include_router(tracking.router)
app.include_router(settings.router)
app.include_router(logs.router)


def _load_initial_logs() -> None:
    """RDS 연결 시 과거 로그를 메모리 캐시(state_store.detection_logs)로 적재합니다."""
    if not store.status["db_enabled"]:
        return
    try:
        rows = db.fetch_all_logs()
        for row in rows:
            date_str, _, time_str = row["created_at"].partition(" ")
            store.detection_logs.append({
                "id": row["id"],
                "job_id": row["job_id"],
                "class_name": row["class_name"],
                "camera": row["camera"],
                "confidence": row["score"],
                "hit_frames": row["frame_index"],
                "source": "영상" if row["input_type"] == "video" else "이미지",
                "input_type": row["input_type"],
                "date": date_str,
                "time": time_str,
                "status": row["status"],
                "remarks": row["remarks"],
                "image_path": row["uri"],
                "uri": row["uri"],
                "content_type": row["content_type"],
                "box": {"x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"]},
                "x1": row["x1"], "y1": row["y1"], "x2": row["x2"], "y2": row["y2"],
                "snapshot": None,
            })
        if store.detection_logs:
            store.bump_next_id(max(a["id"] for a in store.detection_logs))
    except Exception as e:
        store.status["db_write_warning"] = f"RDS 로그 불러오기 실패: {e}"


@app.on_event("startup")
def startup():
    """서버 구동 시 모델을 1회 로드하고 DB/S3 연결·과거 로그를 준비합니다."""
    model_runtime.load_model()
    store.status["db_enabled"] = db.init_db()
    store.status["s3_enabled"] = s3.is_enabled()
    _load_initial_logs()


@app.on_event("shutdown")
def shutdown():
    """서버 종료(--reload 재시작 포함) 시 재생 페이서/클립 추출 스레드를 정리합니다."""
    video_analyzer.shutdown()


@app.post("/detect")
async def detect(image: UploadFile = File(...)):
    """이미지 1장을 받아 탐지 결과와 latency_ms/conf_thresh_used를 반환합니다.
    model_runtime.infer()는 동기 블로킹 호출이라 스레드풀로 넘겨 이벤트 루프를 막지 않습니다."""
    data = await image.read()
    pil_img = Image.open(io.BytesIO(data)).convert("RGB")

    detections, conf_thresh, nms_thresh, latency_ms = await run_in_threadpool(model_runtime.infer, pil_img)

    return {
        "image_width": pil_img.width,
        "image_height": pil_img.height,
        "latency_ms": latency_ms,
        "conf_thresh_used": conf_thresh,
        "nms_thresh_used": nms_thresh,
        "detections": detections,
    }


@app.get("/health")
def health():
    """서버 상태 체크 엔드포인트입니다."""
    return {"status": "ok", "model_loaded": model_runtime.is_loaded()}


@app.get("/api/alert-sound")
def alert_sound():
    """사람 탐지 알림음(WAV). React가 1회 받아 캐시해두고 새 탐지 시 재생합니다."""
    return Response(content=beep_wav_bytes(), media_type="audio/wav")
