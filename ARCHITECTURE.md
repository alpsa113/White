# DualYOLO Architecture Pipeline

> 버전: v0.6.1
> 최종 수정: 2026-06-22
> 이 문서는 모델 구조, 데이터 파이프라인, 코드 모듈 구조의 기준 문서입니다.

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| v0.5.5 | 2026-06-15 | YOLO26-M COCO pretrained 백본을 local checkpoint 기반 필수 로드 방식으로 명확화 |
| v0.6.0 | 2026-06-16 | phase1/2/3 표준 raw 디렉토리 구조, manifest 중심 학습, LLVIP 변환 도구, loader 모듈 분리, `run_training()` 실행 구조 반영 |
| v0.6.1 | 2026-06-22 | phase 전환용 `--init-from`과 같은 phase 재개용 `--resume` 분리 |

---

## 1. 전체 모델 파이프라인

```text
입력
  RGB      [B, 3, H, W] 또는 None
  Thermal  [B, 1, H, W] 또는 None
  cond_vec [B, 3]
       │
       ▼
Dual Backbone
  RGB     → YOLO26-M truncated backbone
  Thermal → YOLO26-M truncated backbone, 첫 conv 1채널 inflation
  출력: C3(stride 8), C4(stride 16)
       │
       ▼
Adaptive Middle Fusion
  cond_vec → MLP → RGB/Thermal channel weight
  pair batch: α * RGB feature + β * Thermal feature
  single batch: 존재하는 modality feature만 통과
       │
       ▼
FPN
  fused C3/C4 → P3/P4
       │
       ▼
Multi-Scale Detection Heads
  cls [B, 4, H, W]
  reg [B, 4, H, W]
  obj [B, 1, H, W]

조건부 분기
  AuxHead: Phase 1/2
  UncertaintyHead: Phase 2 후반 ~ Phase 3
```

---

## 2. 클래스 정의

전 phase에서 클래스 ID는 고정입니다.

| ID | 클래스 | 의미 |
|----|--------|------|
| 0 | person | 사람 |
| 1 | boar | 멧돼지 |
| 2 | deer | 고라니/사슴 계열 |
| 3 | non_target | 박스가 있는 비대상 객체 |

`empty_background`는 class `3`이 아닙니다. 박스와 라벨이 없는 negative sample이며 `tags: ["empty_background"]`로 관리합니다.

---

## 3. 백본

| 항목 | RGB 백본 | Thermal 백본 |
|------|----------|--------------|
| 베이스 | YOLO26-M | YOLO26-M |
| 입력 채널 | 3 | 1 |
| 사전학습 | COCO detection | COCO detection conv1 평균 inflation |
| 추출 피처 | C3, C4 | C3, C4 |
| C3 stride | 8 | 8 |
| C4 stride | 16 | 16 |
| C3 채널 | config 검증값 기준 512 | config 검증값 기준 512 |
| C4 채널 | config 검증값 기준 512 | config 검증값 기준 512 |

YOLO26 provider 코드는 `vendor/yolo26/`에 포함되어 있습니다. `configs/model.yaml`은 기본적으로 아래 weight를 사용합니다.

```text
weights/yolo26m-coco.pt
```

원칙:

- `provider=local_checkpoint`만 지원합니다.
- checkpoint 내부에 `model` 또는 `ema` 키로 `nn.Module`이 있어야 합니다.
- state-dict-only, ONNX, TensorRT, TorchScript 파일은 현재 지원하지 않습니다.
- C3/C4 layer와 채널 검증에 실패하면 학습을 중단합니다.
- YOLO26 full detection head까지 forward하지 않고 C4까지만 실행합니다.

---

## 4. Fusion / FPN / Head

### Adaptive Middle Fusion

조건벡터는 3차원입니다.

```text
0: weather      # weather_id / 3.0
1: temp_c       # 0~1 정규화값
2: illuminance  # 0=야간, 1=주간
```

pair batch에서는 RGB/Thermal feature를 조건 기반 채널 가중치로 합성합니다.
single modality batch에서는 존재하는 feature만 통과시킵니다.

### FPN

```text
fused C4 → P4
fused C3 + upsample(P4) → P3
```

### Detection Head

YOLOX 스타일 decoupled anchor-free head를 사용합니다.

```text
cls: class logit
reg: cx_rel, cy_rel, log_w, log_h
obj: objectness logit
```

### Aux / Uncertainty

- AuxHead는 person/boar/deer 3클래스 보조 분류를 수행합니다. `non_target`과 empty는 aux label에서 제외됩니다.
- UncertaintyHead는 Phase 2 후반부터 cls/reg loss를 heteroscedastic NLL 형태로 대체합니다.

---

## 5. 데이터 파이프라인

표준 흐름은 다음과 같습니다.

```text
raw directory
  → tools/build_manifest_splits.py
  → data/manifests/phase*_train.json, phase*_val.json
  → ManifestDetectionDataset
  → DataLoader
  → Trainer
```

학습 중 raw 폴더를 직접 순회하지 않습니다. 모든 phase는 manifest 파일을 기준으로 학습합니다.

### 표준 raw 구조

```text
data/phase1_raw/single/
  {class_id}/rgb/img/
  {class_id}/rgb/label/
  {class_id}/tir/img/
  {class_id}/tir/label/

data/phase2_raw/pair/
  {class_id}/rgb/img/
  {class_id}/rgb/label/
  {class_id}/tir/img/
  {class_id}/tir/label/

data/gop_raw/
  single/
  pair/
  empty/
```

label은 YOLO txt 형식입니다.

```text
class_id cx cy w h
```

`build_manifest_splits.py`가 이를 절대좌표 `xyxy` box로 변환합니다.

---

## 6. Manifest Loader 구조

manifest 생성 도구는 loader registry를 사용합니다.

```text
tools/
  build_manifest_splits.py
  manifest_loaders/
    common.py
    gop.py
    legacy.py
```

주요 loader:

| format | 역할 |
|--------|------|
| `gop_class_yolo` | 표준 single 구조 로드 |
| `gop_class_yolo_pair` | 표준 pair 구조 로드 |
| `gop_empty_folder` | empty background 로드 |
| `coco` | COCO JSON 호환 source |
| `yolo` | 이미지 목록 기반 YOLO 호환 source |
| `kaist` | KAIST 원본 호환 source |
| `manifest` | 기존 manifest 재사용 |

현재 기본 phase 설정은 표준 raw 구조를 사용합니다. COCO/YOLO/KAIST loader는 호환용으로 유지됩니다.

---

## 7. Dataset / DataLoader 구조

```text
data/
  dataset.py              # ManifestDetectionDataset
  legacy_detection.py     # COCO/YOLO 직접 로딩 호환 Dataset
  builders.py             # build_dataset, build_loaders
  samplers.py             # ModalityHomogeneousBatchSampler
  external/
    kaist_loader.py
    llvip_loader.py
```

`train.py`는 `build_loaders()`를 호출해 manifest 기반 DataLoader를 만듭니다.

batch 내부에는 하나의 modality만 들어갑니다.

```text
rgb batch
thermal batch
pair batch
```

이 정책은 `ModalityHomogeneousBatchSampler`가 담당합니다.

---

## 8. Phase별 데이터 정책

### Phase 1

```text
data/phase1_raw/single
```

RGB-only와 thermal-only 단독 데이터를 사용해 기본 탐지 표현을 학습합니다.

### Phase 2

```text
data/phase2_raw/pair
```

pair 데이터만 사용합니다. LLVIP는 직접 Dataset으로 학습하지 않고 먼저 변환합니다.

```bash
python tools/convert_llvip_to_phase2_raw.py \
  --root data/llvip \
  --split train \
  --output data/phase2_raw/pair
```

boar/deer synthetic pair가 있다면 같은 `phase2_raw/pair/{1,2}/` 구조에 추가합니다.

### Phase 3

```text
data/gop_raw/single
data/gop_raw/pair
data/gop_raw/empty
```

GOP 실제 환경 fine-tuning 단계입니다. 실제 GOP single, 실제/검증된 pair, empty background, non_target을 포함합니다.

---

## 9. 실행 구조

`train.py`는 CLI와 Python 함수 호출을 모두 지원합니다.

```bash
python train.py --phase 3 --init-from checkpoints/phase2/best.pt
```

```python
from train import run_training

run_training(
    phase=3,
    init_from="checkpoints/phase2/best.pt",
)
```

`--init-from`은 phase 전환용이며 모델 weight만 로드합니다.
`--resume`은 같은 phase 중단 재개용으로 optimizer, scheduler, epoch까지 복원합니다.

내부 흐름:

```text
run_training()
  → configs/model.yaml 로드
  → configs/phases.yaml 로드
  → build_loaders()
  → DualYOLO 생성
  → Trainer 생성
  → trainer.train()
```

---

## 10. 미결 과제

| 항목 | 상태 |
|------|------|
| 실제 phase1/2/3 데이터 배치 후 manifest 통계 검증 | 필요 |
| LLVIP + boar/deer synthetic pair 비율 실험 | 필요 |
| phase3 hard negative weight 검증 | 필요 |
| 동적 target assignment 개선 검토 | 추후 |
| 영상/스트림 추론 구현 | 추후 |
