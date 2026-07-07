# DualYOLO GOP 경계 탐지 모델

RGB와 열화상 영상을 함께 사용하는 GOP 경계 감시용 객체 탐지 모델입니다.
모델은 RGB/열화상 각각에 YOLO26-M COCO 사전학습 백본을 사용하고,
`weather`, `temp_c`, `illuminance` 조건벡터를 기반으로 조건 적응형 중간 융합을 수행합니다.

학습은 다음 3단계로 진행합니다.

```text
Phase 1: single RGB/TIR 기본 탐지 학습
Phase 2: RGB-TIR pair 융합 학습
Phase 3: GOP 실제 환경 fine-tuning
```

## 현재 구조

```text
configs/
  model.yaml                     # 모델, 백본 weight, 학습 기본 설정
  phases.yaml                    # 단계별 학습 설정
  phases_rgb_only.yaml           # RGB-only ablation 학습 설정
  splits/manifest_splits.yaml    # raw 데이터 → manifest 분할 설정
  splits/manifest_splits_mini.yaml
                                 # mini_test 데이터셋용 manifest 분할 설정
  splits/manifest_splits_rgb_only.yaml
                                 # RGB-only ablation용 manifest 분할 설정
  splits/manifest_splits_legacy.yaml
                                 # 외부/레거시 데이터셋 source 예시
data/
  dataset.py                     # ManifestDetectionDataset
  legacy_detection.py            # COCO/YOLO 직접 로딩 호환 Dataset
  builders.py                    # Dataset/DataLoader 생성
  samplers.py                    # 모달리티 단위 batch sampler
  external/                      # KAIST/LLVIP 원본 직접 로더 보관
inference/                       # 이미지/영상 추론, 전처리/후처리, 시각화
model/                           # DualYOLO, 백본, 융합, FPN, 헤드
tools/
  build_manifest_splits.py       # phase별 manifest 생성
  build_mini_dataset.py          # raw 데이터 일부를 mini_test subset으로 복사
  convert_forestpersons_phase.py # ForestPersons → phase1/phase3 single 변환
  convert_llvip_to_phase2_raw.py # LLVIP → phase2_raw/pair 변환
  evaluate_checkpoint.py         # best.pt 기준 PR curve/confusion matrix 생성
  plot_training_metrics.py       # metrics.csv → PNG 그래프 생성
  predict_image.py               # 단일 이미지 추론 CLI
  predict_video.py               # 영상 추론 CLI
  manifest_loaders/              # manifest 생성용 source loader
training/                        # 손실, 지표, 학습기, phase scheduler
vendor/yolo26/                   # 공식 Ultralytics YOLO26 provider 코드
weights/                         # 사전학습 weight 위치
```

## 설치

```bash
pip install -r requirements.txt
```

## Weight 준비

대용량 weight 파일은 Git에 포함하지 않습니다. 각자 아래 위치에 준비합니다.

```text
weights/yolo26m-coco.pt
```

`configs/model.yaml`의 기본 경로도 이 위치를 사용합니다.

```yaml
weights: weights/yolo26m-coco.pt
```

조건:

- PyTorch training checkpoint여야 합니다.
- checkpoint 내부에 `model` 또는 `ema` 키로 `nn.Module`이 들어 있어야 합니다.
- state-dict-only, ONNX, TensorRT, TorchScript export 파일은 현재 C3/C4 절단 백본 래퍼에서 지원하지 않습니다.

## 표준 데이터 디렉토리

현재 학습 파이프라인은 raw 데이터를 먼저 표준 디렉토리로 정리한 뒤 manifest를 생성합니다.

```text
data/
  phase1_raw/
    single/
      0/rgb/img/
      0/rgb/label/
      0/tir/img/
      0/tir/label/
      1/...
      2/...
      3/...

  phase2_raw/
    pair/
      0/rgb/img/
      0/rgb/label/
      0/tir/img/
      0/tir/label/
      1/...
      2/...
      3/...

  gop_raw/
    single/
      0/rgb/img/
      0/rgb/label/
      0/tir/img/
      0/tir/label/
      1/...
      2/...
      3/...
    pair/
      0/rgb/img/
      0/rgb/label/
      0/tir/img/
      0/tir/label/
      1/...
      2/...
      3/...
    empty/
      rgb/img/
      tir/img/
```

클래스 ID는 전 phase 고정입니다.

```text
0 = person
1 = boar
2 = deer
3 = non_target
```

`empty background`는 class `3`이 아닙니다. 박스와 라벨이 없는 negative sample이며 `data/gop_raw/empty/` 아래에 둡니다.

## LLVIP 변환

LLVIP는 phase2 pair 학습에 사용할 수 있지만, 학습 중 직접 `LLVIPDataset`으로 읽지 않습니다.
먼저 표준 phase2 구조로 변환한 뒤 manifest를 생성합니다.

```bash
python tools/convert_llvip_to_phase2_raw.py \
  --root data/llvip \
  --split train \
  --output data/phase2_raw/pair \
  --overwrite
```

LLVIP는 person 중심 데이터셋이므로 변환 결과는 `data/phase2_raw/pair/0/` 아래에 생성됩니다.
boar/deer synthetic pair가 있다면 같은 구조의 `1/`, `2/` 아래에 추가합니다.
미니테스트처럼 일부만 변환하려면 `--max-samples`, `--seed`를 사용합니다.

```bash
python tools/convert_llvip_to_phase2_raw.py \
  --root data/llvip \
  --split train \
  --output data/mini_test/phase2_raw/pair \
  --max-samples 3000 \
  --seed 42 \
  --overwrite
```

## Mini Test / ForestPersons

미니 성능 테스트는 `data/mini_test/` 아래에 phase별 raw 구조를 따로 구성해 실행합니다.

```bash
python tools/build_mini_dataset.py --dry-run
python tools/build_mini_dataset.py --overwrite
```

ForestPersons는 person RGB 데이터로만 사용하며, 원본은 보존하고 선택된 subset만 변환합니다.

```bash
python tools/convert_forestpersons_phase.py \
  --phase1-output data/mini_test/phase1_raw/single \
  --phase3-output data/mini_test/gop_raw/single \
  --phase1-count 4000 \
  --phase3-count 2000 \
  --overwrite
```

## Manifest 생성

학습은 raw 디렉토리를 직접 훑지 않고, 사전에 생성한 manifest를 기준으로 진행합니다.

```bash
python tools/build_manifest_splits.py --phase phase1
python tools/build_manifest_splits.py --phase phase2
python tools/build_manifest_splits.py --phase phase3
```

생성 파일:

```text
data/manifests/phase1_train.json
data/manifests/phase1_val.json
data/manifests/phase2_train.json
data/manifests/phase2_val.json
data/manifests/phase3_train.json
data/manifests/phase3_val.json
```

manifest 생성 시 source, 모달리티, 클래스, tag, 빈 라벨 이미지 통계가 출력됩니다.
실제 학습 전에 이 분포를 확인합니다.

미니테스트와 RGB-only ablation은 각각 별도 split config를 사용합니다.

```bash
python tools/build_manifest_splits.py --config configs/splits/manifest_splits_mini.yaml
python tools/build_manifest_splits.py --config configs/splits/manifest_splits_rgb_only.yaml
```

## 학습 실행

1단계:

```bash
python train.py --phase 1 --device cuda
```

2단계:

```bash
python train.py \
  --phase 2 \
  --init-from checkpoints/phase1/best.pt \
  --device cuda
```

3단계:

```bash
python train.py \
  --phase 3 \
  --init-from checkpoints/phase2/best.pt \
  --device cuda
```

phase 전환에는 `--init-from`을 사용합니다.
이 옵션은 이전 phase checkpoint에서 모델 weight만 가져오고 optimizer, scheduler, epoch은 새 phase 기준으로 시작합니다.
`--resume`은 같은 phase 학습이 중간에 끊겼을 때 전체 학습 상태를 이어받는 용도입니다.

Python 코드에서 직접 호출할 수도 있습니다.

```python
from train import run_training

run_training(
    phase=3,
    init_from="checkpoints/phase2/best.pt",
    device="cuda",
)
```

학습을 실행하면 phase별 checkpoint 폴더에 `metrics.csv`가 함께 누적 저장됩니다.
Colab에서 `/content/drive/MyDrive/dual_yolo`가 마운트되어 있으면 기본 저장 위치는 Drive 경로입니다.

```text
로컬: checkpoints/phase*/metrics.csv
Colab: /content/drive/MyDrive/dual_yolo/checkpoints/phase*/metrics.csv
```

## RGB-only Ablation

RGB-only 비교군은 DualYOLO 구조를 유지하되 RGB 샘플만 사용하고 phase2 pair fusion 학습은 생략합니다.

```bash
python tools/build_manifest_splits.py \
  --config configs/splits/manifest_splits_rgb_only.yaml

python train.py \
  --phase 1 \
  --phase-cfg configs/phases_rgb_only.yaml \
  --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only \
  --device cuda

python train.py \
  --phase 3 \
  --init-from /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only/phase1/best.pt \
  --phase-cfg configs/phases_rgb_only.yaml \
  --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only \
  --device cuda
```

## 성능 지표와 시각화

학습 중에는 epoch별 지표를 CSV로 저장하고, 필요할 때 CSV를 그래프로 변환합니다.

학습 지표 CSV를 시각화하려면:

```bash
python tools/plot_training_metrics.py \
  --metrics /content/drive/MyDrive/dual_yolo/checkpoints/phase1/metrics.csv \
  --prefix phase1
```

생성 예시:

```text
/content/drive/MyDrive/dual_yolo/metrics/phase1_loss_curve.png
/content/drive/MyDrive/dual_yolo/metrics/phase1_map_curve.png
/content/drive/MyDrive/dual_yolo/metrics/phase1_class_ap_curve.png
/content/drive/MyDrive/dual_yolo/metrics/phase1_person_prf_curve.png
```

phase 종료 후 `best.pt` 기준 최종 평가를 수행하려면:

```bash
python tools/evaluate_checkpoint.py \
  --checkpoint /content/drive/MyDrive/dual_yolo/checkpoints/phase3/best.pt \
  --phase 3 \
  --prefix phase3 \
  --device cuda
```

주요 산출물:

```text
/content/drive/MyDrive/dual_yolo/metrics/phase3_summary.json
/content/drive/MyDrive/dual_yolo/metrics/phase3_threshold_table_person.csv
/content/drive/MyDrive/dual_yolo/metrics/phase3_pr_curve_person.png
/content/drive/MyDrive/dual_yolo/metrics/phase3_confusion_matrix.csv
/content/drive/MyDrive/dual_yolo/metrics/phase3_confusion_matrix.png
```

기본 모델 지표는 `train_loss`, `val_loss`, `mAP50`, `mAP50_95`, class별 AP, `Precision_person`, `Recall_person`, `F1_person`을 사용합니다.
PR curve와 confusion matrix는 학습 중 매 epoch마다 만들지 않고, phase 종료 후 `best.pt` 기준으로 생성합니다.

## 추론 실행

학습된 checkpoint는 이미지와 영상 추론에 사용할 수 있습니다.
자세한 구조와 결과 JSON 형식은 [INFERENCE_PIPELINE.md](INFERENCE_PIPELINE.md)를 참고합니다.
FastAPI 기반 이미지 추론 API는 [API_PIPELINE.md](API_PIPELINE.md)를 참고합니다.

단일 RGB 이미지 예시:

```bash
python tools/predict_image.py \
  --checkpoint checkpoints/phase3/best.pt \
  --rgb data/inference/rgb/sample_rgb.jpg \
  --output outputs/pred_rgb.jpg \
  --json outputs/pred_rgb.json \
  --device cpu
```

영상 예시:

```bash
python tools/predict_video.py \
  --checkpoint checkpoints/phase3/best.pt \
  --video data/inference/video/sample_rgb_video.mp4 \
  --output outputs/pred_sample_video.mp4 \
  --json outputs/pred_sample_video.json \
  --device cpu \
  --frame-stride 1 \
  --track \
  --track-high-thresh 0.35 \
  --track-low-thresh 0.18 \
  --track-match-thresh 0.30 \
  --track-buffer 6 \
  --track-min-hits 4
```

현재 테스트용 checkpoint는 confidence가 낮을 수 있습니다. bbox 시각화 동작만 확인하려면 임시로 `--conf 0.0001`처럼 낮은 값을 사용할 수 있지만, 실제 검증에서는 충분히 학습된 checkpoint 기준으로 threshold를 다시 잡아야 합니다.
영상에서 `--track`을 켜면 프레임 간 bbox 흔들림과 짧은 미탐을 줄일 수 있습니다. 장면 전환 직후 오탐이 남으면 `--track-high-thresh`, `--track-min-hits`를 높여 보수적으로 조정합니다.

## Git 관리 정책

Git에는 코드, 설정, 문서만 올립니다.

기본 ignore 대상:

```text
data/*
checkpoints/
outputs/
weights/*.pt
weights/*.pth
weights/*.onnx
weights/*.engine
*.pt
*.pth
*.onnx
*.engine
```

단, `data/*.py`와 `data/external/*.py`는 코드이므로 Git 추적 대상입니다.
대용량 데이터셋, 생성된 manifest, 학습 checkpoint, 사전학습 weight, 추론 출력물은 Git에 올리지 않습니다.
