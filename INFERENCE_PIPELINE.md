# 추론 파이프라인 정리

이 문서는 현재까지 작성한 DualYOLO 추론 코드의 구조와 테스트 방법을 정리한다.

## 현재 상태

- 단일 이미지 추론 코드 작성 완료
- 영상 추론 코드 작성 완료
- RGB-only, thermal-only, RGB+thermal pair 입력 smoke test 완료
- 결과 JSON 저장 확인
- bbox 시각화 이미지/영상 저장 확인
- 실제 검출 성능 평가는 실제 학습 데이터로 학습한 checkpoint가 준비된 뒤 재확인 필요

현재 `checkpoints/phase3/best.pt`는 테스트용 학습 결과라 confidence가 매우 낮다. 따라서 bbox 표시 여부만 확인하려면 임시로 `--conf 0.0001`처럼 낮은 값을 사용할 수 있다. 실제 운영/검증에서는 학습이 충분히 된 checkpoint 기준으로 `--conf 0.25` 근처부터 조정한다.

## 파일 구조

```text
inference/
  schemas.py          # 추론 결과, bbox, letterbox 메타데이터 dataclass
  preprocessing.py    # 이미지 로드, letterbox, normalize, tensor 변환
  postprocessing.py   # 모델 출력 decode, NMS, 원본 좌표 복원
  predictor.py        # checkpoint 로드와 단일 이미지 추론 래퍼
  visualization.py    # bbox 시각화 공통 함수
  video.py            # 영상 프레임 순회와 프레임별 추론

tools/
  predict_image.py    # 단일 이미지 추론 CLI
  predict_video.py    # 영상 추론 CLI
```

## 이미지 추론 흐름

```text
이미지 경로 입력
→ RGB/TIR 이미지 로드
→ letterbox로 모델 입력 크기에 맞춤
→ normalize
→ DualYOLO forward
→ decode + NMS
→ bbox를 원본 이미지 좌표로 복원
→ JSON 출력
→ 필요 시 bbox 이미지 저장
```

실행 예시:

```bash
python tools/predict_image.py \
  --checkpoint checkpoints/phase3/best.pt \
  --rgb data/inference/rgb/sample_rgb.jpg \
  --output outputs/pred_rgb.jpg \
  --json outputs/pred_rgb.json \
  --device cpu
```

thermal-only 예시:

```bash
python tools/predict_image.py \
  --checkpoint checkpoints/phase3/best.pt \
  --thermal data/inference/tir/sample_tir.jpg \
  --output outputs/pred_tir.jpg \
  --json outputs/pred_tir.json \
  --device cpu
```

RGB+thermal pair 예시:

```bash
python tools/predict_image.py \
  --checkpoint checkpoints/phase3/best.pt \
  --rgb data/inference/pair/rgb/sample_001.jpg \
  --thermal data/inference/pair/tir/sample_001.jpg \
  --output outputs/pred_pair.jpg \
  --json outputs/pred_pair.json \
  --device cpu
```

## 영상 추론 흐름

영상 추론은 새로운 모델 로직을 만들지 않고, 기존 `DualYOLOPredictor.predict()`를 프레임마다 반복 호출한다.

```text
영상 경로 입력
→ cv2.VideoCapture로 프레임 읽기
→ frame_stride 기준으로 추론할 프레임 선택
→ 프레임을 RGB 또는 thermal 이미지로 변환
→ 기존 이미지 추론기 호출
→ 프레임별 detection 결과 저장
→ 필요 시 bbox가 그려진 영상 저장
```

RGB 영상 실행 예시:

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --video data/inference/video/sample_rgb_video.mp4 \
  --output outputs/pred_sample_video.mp4 \
  --json outputs/pred_sample_video.json \
  --device cpu \
  --frame-stride 5
```

thermal 영상 실행 예시:

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --thermal-video data/inference/video/sample_tir_video.mp4 \
  --output outputs/pred_tir_video.mp4 \
  --json outputs/pred_tir_video.json \
  --device cpu \
  --frame-stride 5
```

RGB+thermal pair 영상 실행 예시:

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --rgb-video data/inference/video/rgb.mp4 \
  --thermal-video data/inference/video/tir.mp4 \
  --output outputs/pred_pair_video.mp4 \
  --json outputs/pred_pair_video.json \
  --device cpu \
  --frame-stride 5
```

테스트 목적으로 처리 프레임 수를 제한하려면 `--max-frames`를 사용한다.

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --video data/inference/video/sample_rgb_video.mp4 \
  --output outputs/pred_sample_video.mp4 \
  --json outputs/pred_sample_video.json \
  --device cpu \
  --frame-stride 5 \
  --max-frames 10
```

## frame-stride 기준

`frame_stride`는 몇 프레임마다 한 번 추론할지 정하는 값이다.
CLI 기본값은 `1`이며, API 기본값은 운영 비용을 고려해 `5`로 둔다.
GOP 1분 내외 영상의 시작값은 `5`를 권장한다.

```text
frame_stride = 원본 FPS / 목표 추론 FPS
```

30fps 영상 기준:

```text
frame_stride 1  -> 30fps 추론, 1분에 1800프레임
frame_stride 3  -> 10fps 추론, 1분에 600프레임
frame_stride 5  -> 6fps 추론, 1분에 360프레임
frame_stride 10 -> 3fps 추론, 1분에 180프레임
frame_stride 30 -> 1fps 추론, 1분에 60프레임
```

처리 시간이 길면 `10`으로 올리고, 객체를 놓치는 구간이 많으면 `3`으로 낮춘다.

## 샘플 영상

테스트용 RGB 샘플 영상:

```text
data/inference/video/sample_rgb_video.mp4
```

속성:

```text
fps: 10.0
해상도: 640 x 360
프레임 수: 30
길이: 약 3초
```

## 결과 JSON 구조

영상 추론 결과는 영상 메타데이터와 프레임별 detection 목록으로 구성된다.

```json
{
  "video": {
    "rgb_path": "data/inference/video/sample_rgb_video.mp4",
    "thermal_path": null,
    "output_path": "outputs/pred_sample_video.mp4",
    "fps": 10.0,
    "width": 640,
    "height": 360,
    "total_frames": 30,
    "frame_stride": 5,
    "processed_frames": 6
  },
  "frames": [
    {
      "frame_index": 0,
      "timestamp_ms": 0.0,
      "detections": [
        {
          "class_id": 0,
          "class_name": "person",
          "score": 0.91,
          "bbox": [120.5, 80.0, 240.5, 300.0]
        }
      ],
      "latency_ms": 12.4,
      "input_modality": "rgb",
      "image_width": 640,
      "image_height": 360
    }
  ]
}
```

## confidence 관련 주의사항

미니테스트 또는 초기 checkpoint는 confidence가 낮아 기본값 `--conf 0.25`에서 detection이 0개일 수 있다. bbox 시각화 코드가 동작하는지만 확인하려면 아래처럼 임시 threshold를 낮춘다.

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --video data/inference/video/sample_rgb_video.mp4 \
  --output outputs/pred_sample_video.mp4 \
  --json outputs/pred_sample_video.json \
  --device cpu \
  --conf 0.0001 \
  --max-frames 5
```

이 값은 테스트용이다. 실제 학습 데이터로 충분히 학습한 checkpoint에서는 validation 지표와 실제 영상 결과를 보면서 적정 confidence threshold를 다시 잡아야 한다.

## 추후 서비스 연동 방향

FastAPI 서버나 Streamlit 대시보드에서는 `tools/predict_video.py`를 직접 실행하지 않고, 아래 함수를 import해서 사용한다.

```python
from inference.video import predict_video
```

권장 흐름:

```text
FastAPI에서 영상 업로드
→ 임시 경로 또는 S3에 저장
→ DualYOLOPredictor 생성 또는 재사용
→ predict_video 호출
→ 결과 영상/JSON 저장
→ MySQL에 요청 정보와 결과 메타데이터 저장
→ Streamlit에서 결과 조회 및 시각화
```
