# GOP 경계 탐지 모델 — 학습 시나리오

이 문서는 현재 코드 기준의 phase별 학습 목적, 데이터 구조, 실행 순서를 정리합니다.

---

## 1. 공통 원칙

학습은 raw 데이터를 직접 읽지 않고 manifest를 기준으로 진행합니다.

```text
raw 데이터 정리
  → manifest 생성
  → train.py 실행
```

생성되는 manifest:

```text
data/manifests/phase1_train.json
data/manifests/phase1_val.json
data/manifests/phase2_train.json
data/manifests/phase2_val.json
data/manifests/phase3_train.json
data/manifests/phase3_val.json
```

클래스 ID:

```text
0 = person
1 = boar
2 = deer
3 = non_target
```

`empty background`는 class `3`이 아닙니다.

```text
boxes: []
labels: []
tags: ["empty_background"]
```

---

## 2. Phase 1 — Single Modality 기본 탐지 학습

### 목적

RGB-only와 thermal-only 단독 데이터로 person/boar/deer/non_target의 기본 탐지 표현을 학습합니다.

### 데이터 구조

```text
data/phase1_raw/
  single/
    0/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    1/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    2/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    3/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
```

이미지와 라벨 파일명은 stem이 같아야 합니다.

```text
rgb/img/a.jpg
rgb/label/a.txt
```

YOLO label 형식:

```text
class_id cx cy w h
```

### 설정

`configs/splits/manifest_splits.yaml`의 `phase1`은 `data/phase1_raw/single`을 봅니다.

`configs/phases.yaml`의 phase1 주요 설정:

```yaml
allow_rgb_only: true
allow_thm_only: true
allow_pairs: true
aux_active: true
uncertainty_active: false
fusion_reg_active: false
modality_dropout_prob: 0.2
```

### 실행

```bash
python tools/build_manifest_splits.py --phase phase1
python train.py --phase 1
```

결과:

```text
checkpoints/phase1/best.pt
```

---

## 3. Phase 2 — Pair Fusion 학습

### 목적

RGB-TIR pair 데이터로 Adaptive Fusion이 두 모달리티를 어떻게 조합할지 학습합니다.

### 핵심 전략

Phase 2는 pair 전용 단계입니다.

```yaml
allow_rgb_only: false
allow_thm_only: false
allow_pairs: true
```

따라서 phase2 manifest에는 `modality: pair` 샘플만 들어가야 합니다.

### 데이터 구조

```text
data/phase2_raw/
  pair/
    0/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    1/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    2/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
    3/
      rgb/img/
      rgb/label/
      tir/img/
      tir/label/
```

권장 구성:

```text
0/person     : LLVIP person pair
1/boar       : boar synthetic pair 또는 실제 pair
2/deer       : deer synthetic pair 또는 실제 pair
3/non_target : 가능하면 pair 형태로 포함
```

### LLVIP 사용 방식

LLVIP는 phase2에 유용하지만 직접 Dataset으로 학습하지 않습니다.
먼저 표준 pair 구조로 변환합니다.

```bash
python tools/convert_llvip_to_phase2_raw.py \
  --root data/llvip \
  --split train \
  --output data/phase2_raw/pair \
  --overwrite
```

LLVIP는 person 중심이므로 변환 결과는 `data/phase2_raw/pair/0/` 아래에 생성됩니다.

### Synthetic boar/deer pair

boar/deer RGB-only 데이터에서 Pix2PixHD 등으로 synthetic TIR을 생성했다면 phase2에 넣는 것이 자연스럽습니다.

이유:

```text
phase2의 목적 = pair 기반 fusion 학습
boar/deer synthetic pair = boar/deer에 대한 RGB-TIR 조합 신호 제공
```

phase3는 실제 GOP 환경 적응 단계로 남겨두는 것이 좋습니다.

### 설정

`configs/splits/manifest_splits.yaml`의 `phase2`는 `data/phase2_raw/pair`를 봅니다.

`configs/phases.yaml`의 phase2 주요 설정:

```yaml
aux_active: true
uncertainty_active: false
uncertainty_start_epoch: 10
fusion_reg_active: true
modality_dropout_prob: 0.05
```

`PhaseScheduler`는 `uncertainty_start_epoch`에 도달하면 uncertainty head를 활성화합니다.
미니테스트처럼 uncertainty를 끄고 비교하려면 `uncertainty_active: false`,
`uncertainty_start_epoch: null`로 설정합니다.

### 실행

```bash
python tools/build_manifest_splits.py --phase phase2
python train.py --phase 2 --init-from checkpoints/phase1/best.pt
```

결과:

```text
checkpoints/phase2/best.pt
```

---

## 4. Phase 3 — GOP 실제 환경 Fine-tuning

### 목적

실제 GOP 운용 환경에 맞춰 최종 fine-tuning을 수행합니다.

### 데이터 구조

```text
data/gop_raw/
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

현재 기본 config에서는:

```text
gop_raw_single
gop_empty_background
```

가 활성화되어 있습니다. 실제 GOP pair가 준비되면 `gop_raw_pair`를 `enabled: true`로 바꿉니다.

### 데이터 의미

```text
single/0 = person single
single/1 = boar single
single/2 = deer single
single/3 = boxed non_target single
empty/   = target도 non_target box도 없는 검수된 background
```

`non_target`은 박스가 있는 비대상 객체입니다.
empty background를 `single/3`에 넣지 않습니다.

### 설정

`configs/phases.yaml`의 phase3 주요 설정:

```yaml
aux_active: false
uncertainty_active: true
uncertainty_start_epoch: 0
fusion_reg_active: true
backbone_unfreeze_epoch: 8
hard_negative_sampling:
  enabled: true
```

전반부는 backbone을 동결하고, 후반부에 전체를 낮은 learning rate로 fine-tuning합니다.

### 실행

```bash
python tools/build_manifest_splits.py --phase phase3
python train.py --phase 3 --init-from checkpoints/phase2/best.pt
```

결과:

```text
checkpoints/phase3/best.pt
```

---

## 5. 전체 실행 순서

처음부터 전체 학습:

```bash
python tools/build_manifest_splits.py --phase phase1
python train.py --phase 1

python tools/build_manifest_splits.py --phase phase2
python train.py --phase 2 --init-from checkpoints/phase1/best.pt

python tools/build_manifest_splits.py --phase phase3
python train.py --phase 3 --init-from checkpoints/phase2/best.pt
```

Colab에서는 코드 셀에서 `!`를 붙여 실행합니다.

```python
!python tools/build_manifest_splits.py --phase phase3
!python train.py --phase 3 --init-from checkpoints/phase2/best.pt
```

phase 전환에는 `--init-from`을 사용합니다.
이전 phase의 모델 weight만 가져오고 optimizer, scheduler, epoch은 새 phase 기준으로 초기화합니다.
`--resume`은 같은 phase 학습이 중간에 끊겼을 때 전체 상태를 이어받는 용도입니다.

---

## 6. Manifest 생성 후 확인할 것

각 phase manifest 생성 시 다음 통계가 출력됩니다.

```text
source별 분포
모달리티별 분포
클래스별 box 분포
빈 라벨 이미지
tag별 분포
```

확인 포인트:

```text
phase1: rgb/thermal 단독 분포, class imbalance
phase2: pair만 포함되는지 확인
phase3: empty_background, non_target, pair/single 비율 확인
```

phase2에 `rgb` 또는 `thermal` 단독 sample이 들어가면 설정상 학습 시작 전에 중단되어야 합니다.

---

## 7. 현재 남은 실데이터 검증 항목

| 항목 | 확인 내용 |
|------|-----------|
| phase1 데이터 | person/boar/deer/non_target class 분포, RGB/TIR 비율 |
| phase2 데이터 | LLVIP person pair와 boar/deer synthetic pair 비율 |
| phase3 데이터 | GOP single/empty/pair 비율, hard negative tag 분포 |
| label 품질 | 폴더 class id와 label class id 일치 여부 |
| split 품질 | 같은 scene/stem이 train/val로 갈라지지 않는지 |
| 성능 지표 | class별 AP/recall, RGB vs TIR 성능 차이, empty false positive |

학습 완료 후 이미지/영상 추론 실행 방법과 결과 JSON 구조는 `INFERENCE_PIPELINE.md`를 참고합니다.
