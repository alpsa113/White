# FastAPI 추론 API 정리

이 문서는 DualYOLO 추론 API의 현재 구조와 실행 방법을 정리한다.

## 현재 상태

- FastAPI 서버 기본 구조 작성 완료
- `/health` 상태 확인 API 작성 완료
- `/predict/image` 이미지 추론 API 작성 완료
- `/predict/video` 영상 추론 API 작성 완료
- RGB-only, thermal-only, RGB+thermal pair 입력 지원
- `conf`, `nms`, `frame_stride`, `max_frames` query parameter 지원
- 영상 API에서 `track`과 tracking 세부 query parameter 지원
- 기본 입력 검증과 주요 예외 처리 추가

아직 DB 저장, Streamlit 대시보드 연동은 구현하지 않았다.

## 파일 구조

```text
api/
  main.py                    # FastAPI 앱 생성과 router 등록
  routes/
    health.py                # /health endpoint
    inference.py             # /predict/image, /predict/video endpoint
  schemas/
    inference.py             # API 응답 schema
  services/
    image_io.py              # UploadFile -> OpenCV/Numpy 이미지 변환
    video_io.py              # UploadFile -> tempfile 영상 파일 저장
    predictor_service.py     # DualYOLOPredictor 로드/재사용과 추론 호출
```

## 서버 실행

```bash
uvicorn api.main:app --reload
```

`uvicorn` 명령이 잡히지 않으면 다음처럼 실행한다.

```bash
python -m uvicorn api.main:app --reload
```

확인 URL:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

## Health Check

```text
GET /health
```

응답:

```json
{
  "status": "ok"
}
```

## 이미지 추론 API

```text
POST /predict/image
```

입력:

```text
rgb_file: RGB 이미지 파일, optional
thermal_file: thermal 이미지 파일, optional
conf: confidence threshold, 기본 0.25
nms: NMS IoU threshold, 기본 0.6
```

입력 규칙:

```text
rgb_file만 업로드      -> RGB-only 추론
thermal_file만 업로드  -> thermal-only 추론
둘 다 업로드           -> RGB+thermal pair 추론
둘 다 없음             -> 400 Bad Request
```

`conf`, `nms`는 `0.0 <= 값 <= 1.0` 범위만 허용한다. 범위를 벗어나면 FastAPI validation error가 반환된다.

## 응답 형식

```json
{
  "input_modality": "pair",
  "image_width": 1280,
  "image_height": 1024,
  "latency_ms": 498.75,
  "detections": [
    {
      "class_id": 0,
      "class_name": "person",
      "score": 0.91,
      "bbox": [120.5, 80.0, 240.5, 300.0]
    }
  ]
}
```

현재 테스트 checkpoint는 confidence가 낮을 수 있으므로 `detections`가 빈 배열일 수 있다. API 연결 확인 목적이면 `/docs`에서 `conf=0.0001`처럼 낮춰 bbox 후보가 반환되는지 확인할 수 있다.

## 영상 추론 API

```text
POST /predict/video
```

입력:

```text
rgb_video: RGB 영상 파일, optional
thermal_video: thermal 영상 파일, optional
conf: confidence threshold, 기본 0.25
nms: NMS IoU threshold, 기본 0.6
frame_stride: 몇 프레임마다 추론할지, 기본 5
max_frames: 최대 추론 프레임 수, optional
track: 영상 프레임 간 bbox tracking 적용 여부, 기본 false
track_high_thresh: 새 track 생성용 confidence threshold, 기본 0.25
track_low_thresh: 기존 track 보정용 confidence threshold, 기본 0.10
track_match_thresh: track과 detection을 연결할 IoU threshold, 기본 0.35
track_buffer: 짧은 미탐 시 track을 유지할 프레임 수, 기본 8
track_smooth_alpha: bbox smoothing 강도, 기본 0.7
track_min_area_ratio: bbox 면적 급변 방어 하한, 기본 0.4
track_max_area_ratio: bbox 면적 급변 방어 상한, 기본 2.5
track_min_hits: 결과에 표시하기 전 필요한 최소 연속 관측 수, 기본 1
```

입력 규칙:

```text
rgb_video만 업로드      -> RGB-only 영상 추론
thermal_video만 업로드  -> thermal-only 영상 추론
둘 다 업로드            -> RGB+thermal pair 영상 추론
둘 다 없음              -> 400 Bad Request
```

영상 API는 업로드 파일을 `tempfile.TemporaryDirectory()` 아래에 임시 저장한 뒤 `inference.video.predict_video()`를 호출한다. 현재 단계에서는 결과 영상을 영구 저장하지 않고, 프레임별 추론 결과 JSON만 반환한다.

`track=true`로 요청하면 CLI 영상 추론과 동일한 간단한 ByteTrack 스타일 tracking을 적용한다. 이 옵션은 bbox 깜빡임과 짧은 미탐을 줄이는 데 사용한다. 장면 전환 직후 생기는 일시적 오탐은 아직 별도 scene-change 안정화 로직을 붙이지 않았으므로, 필요하면 `track_high_thresh`, `track_min_hits`, `track_buffer`를 보수적으로 조정한다.

테스트 예시:

```text
rgb_video: data/inference/video/sample_rgb_video.mp4
conf: 0.25
nms: 0.6
frame_stride: 5
max_frames: 2
track: true
track_high_thresh: 0.35
track_low_thresh: 0.18
track_match_thresh: 0.30
track_buffer: 6
track_min_hits: 4
```

응답 예시:

```json
{
  "video": {
    "rgb_path": null,
    "thermal_path": null,
    "output_path": null,
    "fps": 10.0,
    "width": 640,
    "height": 360,
    "total_frames": 30,
    "frame_stride": 5,
    "processed_frames": 2,
    "tracking": true
  },
  "frames": [
    {
      "frame_index": 0,
      "timestamp_ms": 0.0,
      "latency_ms": 353.98,
      "input_modality": "rgb",
      "image_width": 640,
      "image_height": 360,
      "detections": [
        {
          "class_id": 0,
          "class_name": "person",
          "score": 0.82,
          "bbox": [120.5, 80.0, 240.5, 300.0],
          "track_id": 1
        }
      ]
    }
  ]
}
```

임시 파일 경로는 API 응답에서 노출하지 않는다. 나중에 로컬 저장소 또는 S3 저장 정책을 붙이면 `output_path` 대신 결과 파일 URL 또는 저장 경로를 반환한다.

## 예외 처리

### 입력 파일 없음

이미지 API에서 RGB와 thermal 파일을 모두 비워서 요청하면 `400`을 반환한다.

```json
{
  "detail": "rgb_file 또는 thermal_file 중 하나는 필요합니다."
}
```

영상 API에서 RGB와 thermal 영상을 모두 비워서 요청하면 `400`을 반환한다.

```json
{
  "detail": "rgb_video 또는 thermal_video 중 하나는 필요합니다."
}
```

### 이미지 decode 실패

이미지가 아닌 파일 또는 깨진 파일을 업로드하면 `400`을 반환한다.

```json
{
  "detail": "이미지 파일을 읽지 못했습니다."
}
```

### 영상 decode 실패

영상이 아닌 파일 또는 깨진 파일을 업로드하면 `400`을 반환한다.

```json
{
  "detail": "업로드한 파일을 영상으로 읽지 못했습니다."
}
```

### Checkpoint 없음

기본 checkpoint가 없으면 `503`을 반환한다.

```json
{
  "detail": "추론 모델 checkpoint가 준비되지 않았습니다."
}
```

모델 로드 또는 추론 실행 중 오류가 발생하면 `503`을 반환한다.

```json
{
  "detail": "추론 모델을 로드하거나 실행하지 못했습니다."
}
```

## 현재 한계와 다음 단계

- `predictor_service.py`는 현재 단일 predictor를 재사용한다.
- `conf`, `nms`는 요청마다 predictor 속성을 임시로 바꾸는 방식이다.
- 동시 요청이 많아지는 운영 환경에서는 `DualYOLOPredictor.predict()`가 요청별 `conf`, `nms`를 직접 받도록 개선하는 것이 좋다.
- 영상 API는 현재 JSON 응답만 반환하며, 결과 영상 파일 저장은 아직 연결하지 않았다.
- 영상 tracking은 현재 프레임 간 IoU 기반 최소 구현이며, 장면 전환 감지와 API 결과 영상 저장은 이후 단계에서 추가한다.
- DB 저장, FastAPI-Streamlit 연동, AWS RDS MySQL 기록 구조는 이후 단계에서 추가한다.
- 초기 서비스 단계에서는 로컬 저장소를 사용할 수 있지만, 다중 사용자/배포 환경에서는 S3 같은 object storage 연결을 검토한다.
