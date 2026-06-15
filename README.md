# DualYOLO GOP 경계 탐지 모델

RGB와 열화상 영상을 함께 사용하는 GOP 경계 감시용 객체 탐지 모델입니다.

모델은 RGB/열화상 각각에 YOLO26-M COCO 사전학습 백본을 사용하고,
weather, temp_c, illuminance 조건벡터를 기반으로 adaptive middle fusion을
수행합니다. 학습은 일반 환경 사전학습, 페어 데이터 융합 학습, GOP 유사 환경
fine-tuning의 3단계로 구성됩니다.

## 현재 상태

- 전체 아키텍처와 학습 정책은 `ARCHITECTURE.md`, `TRAINING_SCENARIO.md`에 정리되어 있습니다.
- 학습/검증 데이터는 사전 생성한 manifest split을 기준으로 로드합니다.
- 검증 루프는 mAP@0.5를 계산하고 best/final checkpoint를 저장합니다.
- synthetic 데이터와 tiny test checkpoint 기반 로컬 smoke test를 통과했습니다.
- 실제 학습에는 아직 실제 YOLO26 provider 코드, `yolo26m-coco.pt`, 실제 manifest 데이터가 필요합니다.

## 디렉터리 구조

```text
configs/
  model.yaml                     # 모델, 백본, 학습 기본 설정
  phases.yaml                    # phase별 학습 설정
  splits/manifest_splits.yaml    # 원본 데이터셋 → manifest split 설정
data/                            # 데이터셋 로더와 transform
model/                           # DualYOLO, backbone, fusion, FPN, head
tools/
  build_manifest_splits.py       # phase별 train/val manifest 생성 도구
training/                        # loss, metric, trainer, phase scheduler
vendor/yolo26/                   # YOLO26 provider 코드 위치
weights/                         # weight 안내 파일만 포함, 대용량 weight는 Git 제외
```

## 설치

```bash
pip install -r requirements.txt
```

필요 패키지:

```text
torch
torchvision
opencv-python
albumentations
numpy
pyyaml
```

## 외부 준비물

아래 파일들은 Git에 커밋하지 않습니다.

### YOLO26 Provider 코드

`yolo26m-coco.pt`를 생성한 YOLO26 모델 정의 코드를 아래 위치에 둡니다.

```text
vendor/yolo26/
```

조건:

- checkpoint에 들어있는 Python 모델 클래스가 런타임에서 import 가능해야 합니다.
- 로드된 모델은 layer graph를 `model.model`로 노출해야 합니다.
- `model.model`은 `nn.ModuleList` 또는 `nn.Sequential`이어야 합니다.

### YOLO26-M COCO 사전학습 weight

Colab 기준 기본 경로:

```text
/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt
```

조건:

- PyTorch training checkpoint여야 합니다.
- checkpoint 내부에 `model` 또는 `ema` 키로 `nn.Module`이 들어 있어야 합니다.
- state-dict-only, ONNX, TensorRT, TorchScript export 파일은 현재 truncated-backbone wrapper에서 지원하지 않습니다.

## Manifest 생성

학습 중 랜덤 split을 하지 않고, 사전에 생성한 manifest split을 사용합니다.

먼저 `configs/splits/manifest_splits.yaml`에 원본 데이터셋 경로를 맞춘 뒤 실행합니다.

```bash
python tools/build_manifest_splits.py \
  --config configs/splits/manifest_splits.yaml
```

생성되는 파일:

```text
data/manifests/phase1_train.json
data/manifests/phase1_val.json
data/manifests/phase2_train.json
data/manifests/phase2_val.json
data/manifests/phase3_train.json
data/manifests/phase3_val.json
```

manifest 생성 시 source, modality, class, tag, empty image 통계가 출력됩니다.
실제 학습 전에 이 분포를 확인해 Phase 3 데이터 비율이 정책과 크게 어긋나지 않는지 점검합니다.

## 학습 실행

Phase 1:

```bash
python train.py --phase 1 --device cuda
```

Phase 1 best checkpoint에서 Phase 2 시작:

```bash
python train.py \
  --phase 2 \
  --resume checkpoints/phase1/best.pt \
  --device cuda
```

Phase 2 best checkpoint에서 Phase 3 시작:

```bash
python train.py \
  --phase 3 \
  --resume checkpoints/phase2/best.pt \
  --device cuda
```

빠른 1 epoch 확인:

```bash
python train.py --phase 1 --batch 1 --epochs 1 --img-size 640 --device cuda
```

## Git 관리 정책

Git에는 코드, 설정, 문서만 올립니다.

기본 ignore 대상:

```text
data/
checkpoints/
weights/*.pt
weights/*.pth
weights/*.onnx
weights/*.engine
*.pt
*.pth
*.onnx
*.engine
```

대용량 데이터셋, 생성된 manifest, 학습 checkpoint, pretrained weight는 Git에 올리지 않고
Google Drive 등 외부 저장소에 둡니다.

## 브랜치 작업 방식

`main`은 기준 브랜치로 유지하고, 기능별 작업은 별도 브랜치에서 진행합니다.

예시:

```bash
git checkout main
git pull origin main
git checkout -b feature/yolo26-provider
```

작업 후:

```bash
git add .
git commit -m "작업 내용 요약"
git push -u origin feature/yolo26-provider
```

이후 GitHub에서 Pull Request를 생성해 리뷰 후 `main`에 병합합니다.
