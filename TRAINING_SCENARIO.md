# GOP 경계 탐지 모델 — 학습 시나리오

## 모델 개요

```
입력 (RGB / 열화상 / 조건벡터)
  ↓
[Dual Backbone]
  RGB  → YOLO26-M (C3:256 stride 8, C4:512 stride 16)
  열화상 → YOLO26-M 1채널 (conv1 weight inflation)
  ↓
[Adaptive Middle Fusion]
  조건벡터(weather·temp_c·illuminance 3차원)를 참조해
  RGB/열화상 가중치를 동적으로 산출 후 합산
  ↓
[FPN] → P3 (stride 8, small), P4 (stride 16, large)
  ↓
[Detection Head]  →  person / boar / deer / non_target  (YOLOX 스타일)
[Aux Head × 2]   →  RGB C4 / 열화상 C4 보조 분류
[Uncertainty Head] → Aleatoric 불확실성 추정 (Phase 2 후반~3)
```

**Pretrained backbone checkpoint**

- YOLO26-M COCO pretrained 백본은 Google Drive에 저장한 PyTorch training checkpoint에서 로드한다.
- YOLO26 provider 코드는 공식 Ultralytics 소스를 repo 내부 `vendor/yolo26/`에 고정해 Colab과 로컬에서 같은 모델 클래스를 import한다.
- Ultralytics provider 코드는 AGPL-3.0 라이선스를 따르며, 라이선스 전문은 `vendor/yolo26/LICENSE`를 기준으로 확인한다.
- Colab 기준 기본 경로는 `/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt`이다.
- checkpoint는 내부 layer graph에 접근 가능한 `nn.Module`을 `model` 또는 `ema` 키로 포함해야 한다.
- `nn.Module` checkpoint 로드를 위해 checkpoint를 생성한 YOLO26 모델 코드/패키지가 Colab 런타임에서 import 가능해야 한다.
- state-dict-only, ONNX, TensorRT, TorchScript export는 C3/C4 truncated training wrapper 입력으로 사용하지 않는다.
- checkpoint가 없거나 C3/C4 stride/channel 검증에 실패하면 학습을 중단한다. 랜덤 초기화 fallback은 사용하지 않는다.
- DualYOLO 학습 재개 checkpoint는 `checkpoints/phase*/` 아래에 별도로 저장하며 AdamW optimizer, scheduler, AMP scaler 상태를 함께 저장한다.

**클래스 구성** (전 페이즈 고정)

| ID | 클래스 |
|----|--------|
| 0 | person |
| 1 | boar |
| 2 | deer |
| 3 | non_target |

---

## 학습 3단계 시나리오

### Phase 1 — 다양한 환경 사전학습

**목표**: 클래스별 외형 특징을 다양한 환경·센서 조건에서 학습한다.
백본이 실제 탐지 대상에 대한 표현을 충분히 확보한 뒤 Phase 2로 넘어간다.

**데이터 조건**

- RGB 단독 이미지, 열화상 단독 이미지, RGB+열화상 페어 모두 허용
- 라벨: person / boar / deer (3클래스 전부 포함)
- 환경: 도심, 야외, 숲, 산악, 주간·야간 혼합
- 날씨: 맑음, 강우, 폭설, 안개 포함

**데이터 예시**

| 소스 유형 | 모달리티 | 주요 클래스 | 비고 |
|-----------|----------|-------------|------|
| 도심 보행자 데이터셋 (COCO 등) | RGB | person | weather augmentation 적용 |
| 야생동물 RGB 데이터셋 | RGB | boar, deer | weather augmentation 적용 |
| KAIST Multispectral Pedestrian | RGB + Thermal | person | **person 라벨 프레임만 필터링**, weather augmentation 적용 |
| 열화상 단독 야생동물 이미지 | Thermal | boar, deer | — |

**학습 전략**

- RGB 단독 배치: `thermal_available=False` → 열화상 백본 gradient 없음
- 열화상 단독 배치: `rgb_available=False` → RGB 백본 gradient 없음
- 페어 배치: 양쪽 백본 동시 학습, fusion도 함께 학습
- batch 내부에는 `rgb` / `thermal` / `pair` 중 하나의 modality 타입만 포함한다.
- weather augmentation (RandomRain·RandomFog·RandomSnow) 적용 시 cond_vec[0](weather)을 `weather / 3.0` 값으로 자동 동기화
- Aux Head 활성화 (RGB·열화상 각 백본 출력에 보조 손실 적용)
- Uncertainty Head 비활성화

**Optimizer**

- RGB/열화상 백본: lr = 1e-5 (YOLO26-M COCO 사전학습 가중치 보존)
- Fusion / FPN / Head: lr = 1e-4

---

### Phase 2 — 페어 데이터 융합 학습

**목표**: RGB+열화상 페어 데이터로 Adaptive Fusion이 두 모달을
상황에 맞게 적절히 조합하도록 가중치를 집중 학습한다.

**데이터 조건**

- RGB+열화상 페어만 사용 (단독 모달 제외)
- 라벨: person (LLVIP 전체 야간 기준)
- KAIST 제외: 차량·도심 도로 중심 구성으로 GOP 자연지형 열 분포와 상이, person 비율 낮음 → Phase 1 활용

**데이터 예시**

| 소스 | 특징 | cond_vec |
|------|------|---------|
| LLVIP | 야간 저조도 고정 카메라 페어, person 라벨 | weather=augmentation 연동, temp_c=0.2, illuminance=0.0 |

**학습 전략**

- 양 모달 항상 존재 → fusion이 실질적인 가중치 배분을 학습
- weather augmentation (RandomRain·RandomFog·RandomSnow) 적용 시 cond_vec[0](weather)을 `weather / 3.0` 값으로 자동 동기화
- Fusion regularization loss 활성화 (illuminance==0 야간 기준)
- Aux Head 유지, Uncertainty Head forward/loss 전반부 비활성화 → 후반부 활성화 (epoch 10~)
- Modality dropout 낮은 비율 유지 (0.05, 페어 학습 집중)

**Optimizer**

- 백본: lr = 5e-6 (Phase 1 학습 결과 보존)
- Fusion / FPN / Head: lr = 1e-5
- Uncertainty Head optimizer group은 시작부터 존재하지만, forward/loss는 후반부에 활성화

---

### Phase 3 — GOP 유사 환경 Fine-tuning

**목표**: 실제 전방 GOP 운용 환경과 유사한 수풀·산악·자연 지형 이미지로
최종 도메인 적응을 수행한다.

**데이터 조건**

- 환경: 숲, 수풀, 산악, 야산 등 자연 지형
- 모달리티: RGB+열화상 페어 중심, 단독 모달 hard negative 보조 허용
- 라벨: person / boar / deer
- GOP 실데이터 확보 시 포함
- RGB 원본과 같은 프레임에서 CycleGAN으로 생성한 TIR은 paired thermal로 취급

**학습 전략**

- 전반부: 백본 동결, Fusion·FPN·Head만 fine-tune
- 후반부: 전체 파라미터 소폭 lr로 함께 fine-tune
- Uncertainty Head 활성화 유지
- Hard negative 샘플(야간·폭설·안개·강한 열 교란) 비율 상향
- 원거리 person 샘플과 소형 동물 non_target 샘플을 반드시 병행 구성

**Phase 3 source 구성**

| source 유형 | modality | cond_vec |
|-------------|----------|----------|
| GOP 주간 pair | pair (RGB + CycleGAN TIR) | `[weather_aug, 0.5, 1.0]` |
| GOP 야간 pair | pair (RGB + CycleGAN TIR 또는 실제 TIR) | `[weather_aug, 0.3, 0.0]` |
| 원거리 person 주간 | rgb 또는 pair | `[weather_aug, 0.5, 1.0]` |
| 원거리 person 야간 | thermal 또는 pair | `[weather_aug, 0.3, 0.0]` |
| 소형 동물 non_target 주간 | rgb 또는 pair | `[weather_aug, 0.5, 1.0]` |
| 소형 동물 non_target 야간 | thermal 또는 pair | `[weather_aug, 0.3, 0.0]` |

초기 비율은 GOP pair 60~70%, 원거리 person 15~20%, small non_target 15~20%, 검수 empty background 5~10%를 기준으로 시작한다. 실제 TIR과 CycleGAN synthetic TIR이 모두 있으면 source를 분리해 manifest에 기록한다.

**Optimizer**

- 백본 동결 구간: Fusion / FPN / Head lr = 1e-5
- 전체 해제 구간: 전 파라미터 lr = 5e-6

---

## 단계별 요약

| 구분 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|
| 데이터 | COCO·야생동물·KAIST(person 필터) 혼합 | LLVIP 단독 페어 | GOP pair 중심 + hard negative 보강 |
| 모달리티 | 단독 + 페어 혼합 | 페어 전용 | 페어 중심 + 단독 보조 |
| 클래스 | person / boar / deer | person 중심 | person / boar / deer / non_target |
| Aux Head | ✅ 활성 | ✅ 활성 | 선택 |
| Uncertainty | ❌ 비활성 | 후반부 ✅ 활성 | ✅ 활성 |
| Fusion reg | ❌ 비활성 | ✅ 활성 | ✅ 활성 |
| 백본 lr | 1e-5 | 5e-6 | 동결 → 5e-6 |

---

## 데이터 구성 및 로더 정책

### 공통 샘플 스키마

모든 데이터셋은 로더 출력 시 아래 형태로 정규화한다.

```python
{
    "rgb": Tensor[3,H,W] 또는 없음,
    "thermal": Tensor[1,H,W] 또는 없음,
    "boxes": Tensor[N,4],      # xyxy 절대좌표
    "labels": Tensor[N],       # 0 person, 1 boar, 2 deer, 3 non_target
    "cond_vec": Tensor[3],     # [weather_norm, temp_c, illuminance]
    "aux_label": int,          # person/boar/deer dominant class, 없으면 -1
    "tags": list[str],         # hard negative sampler용
}
```

`cond_vec[0]`은 `weather_id / 3.0`이며, train transform에서 선택된 weather augmentation과 자동 동기화한다.

### Manifest split 정책

학습/검증 split은 학습 실행 중 랜덤으로 나누지 않고, 사전에 생성한 manifest 파일로 고정한다.

```text
data/manifests/
  phase1_train.json
  phase1_val.json
  phase2_train.json
  phase2_val.json
  phase3_train.json
  phase3_val.json
```

manifest는 각 샘플의 RGB/thermal 경로, box, label, source, modality, cond_vec, split_group을 가진다. `split_group`은 이미지 단위 독립 샘플에서는 image_id를 사용하고, KAIST 같은 연속 프레임 데이터에서는 `set/video` 단위로 묶어 train/val 누수를 막는다.

생성 명령:

```bash
python tools/build_manifest_splits.py --config configs/splits/manifest_splits.yaml
```

`phases.yaml`은 원본 데이터셋 경로 대신 생성된 manifest train/val 파일을 참조한다.
manifest 생성 시 source, modality, class box, tag, empty image 분포를 출력해 Phase 3 비율 정책을 실데이터 기준으로 확인한다.

### Phase 1 데이터 정책

- 목표는 person / boar / deer의 기본 표현 학습이다.
- COCO person, 야생동물 RGB, 열화상 야생동물, KAIST person 페어 데이터를 사용한다.
- target 학습용 데이터셋은 빈 라벨 이미지를 기본 제외한다.
- 실제 target 객체가 있는데 라벨이 빈 이미지는 라벨 보정 또는 학습 제외한다.
- 검수된 background/negative 목적 데이터셋이 아니라면 empty label 이미지를 Phase 1 target 학습에 섞지 않는다.

권장 config 정책:

```yaml
require_boxes: true
require_labels: [0, 1, 2]
```

범용 로더는 `require_labels`가 지정되면 해당 클래스가 하나 이상 있는 이미지만 사용한다. KAIST 로더는 기본적으로 `require_person: true`로 동작하며, person annotation이 없는 프레임은 Phase 1 target 학습에서 제외한다.

### Phase 2 데이터 정책

- LLVIP RGB+열화상 pair만 사용한다.
- 라벨은 person 중심이며, RGB와 thermal이 모두 존재해야 한다.
- 빈 라벨 이미지는 원칙적으로 제외한다.
- `temp_c=0.2`, `illuminance=0.0`을 유지하고, weather만 augmentation 결과와 연동한다.

### Phase 3 데이터 정책

- GOP 유사 자연지형, 원거리 person, 소형 동물 non_target, 야간/폭설/안개/열교란 샘플을 포함한다.
- Phase 3 `cond_vec`는 source 단위 매크로값으로 지정한다. 주간 source는 `temp_c=0.5`, `illuminance=1.0`, 야간 source는 `temp_c=0.3`, `illuminance=0.0`을 기본값으로 사용한다.
- 검수된 empty background 이미지는 negative sample로 허용한다.
- Phase 1 target 필터링에서 제외된 도시/도로 배경 non_target 이미지를 Phase 3로 자동 편입하지 않는다.
- 실제 target 객체가 있는데 라벨이 빈 이미지는 라벨 보정 또는 학습 제외한다.
- `non_target`은 박스가 있는 비대상 객체에만 사용한다.
- hard negative tags는 annotation에서 자동 계산하고, meta 파일의 `tags`가 있으면 union한다.

자동 태그 기준:

| 조건 | 태그 |
|------|------|
| person box area < 32×32 | `distant_person` |
| non_target box 존재 | `non_target` |
| non_target box area < 32×32 | `small_non_target` |

### 빈 라벨 이미지 처리 원칙

| 경우 | 처리 |
|------|------|
| 실제 target 있음 + 라벨 없음 | 라벨 오류. 보정 또는 제외 |
| 실제 target 없음 + 라벨 없음 | 검수된 negative로 유지 가능 |
| target 학습용 데이터셋의 빈 라벨 | 기본 제외 |
| 검수된 background/negative 데이터셋 | 빈 라벨 허용 |
| non_target 객체 있음 | 빈 라벨이 아니라 label=3 box 필요 |

### 추론 조건 입력 정책

초기 영상 추론 테스트는 센서 메타데이터와 자동 weather 추정을 사용하지 않는다. 샘플 영상 단위로 운용자가 조건을 지정하고, 동일 영상 내 모든 프레임에 같은 `cond_vec`를 적용한다.

| 입력 | 값 |
|------|-----|
| weather | `clear`, `rain`, `snow`, `fog` |
| illuminance | `day`, `night` |
| temp_c | 0~1 정규화 값 |

미지정 fallback은 GOP/야간 테스트 기준으로 `weather=clear`, `illuminance=night`, `temp_c=0.3`을 사용한다. `infer_video.py`는 학습 파이프라인, manifest split, 후처리 정책 확정 후 생성한다.

---

## 구현 전 선결 과제

| 항목 | 상태 | 내용 |
|------|------|------|
| 범용 데이터셋 로더 | ✅ 완료 | dataset.py (COCO JSON, YOLO txt 지원) |
| LLVIP 로더 | ✅ 완료 | llvip_loader.py 구현됨 |
| 조건벡터 fallback | ✅ 완료 | DEFAULT_COND = [0.0, 0.5, 1.0] (3차원) |
| phases.py 재설계 | ✅ 완료 | 3단계 optimizer 구성 구현됨 |
| weather augmentation ↔ cond_vec 연동 | ✅ 완료 | WeatherAwareTransform에서 선택된 weather_id를 cond_vec[0]에 자동 반영 |
| KAIST person 프레임 필터링 | ✅ 완료 | `require_person: true`로 person annotation이 있는 프레임만 선별 |
| Hard negative 샘플러 | ✅ 완료 | annotation 자동 tag + weighted homogeneous batch sampler 구현됨 |
| Manifest split | ✅ 완료 | 사전 생성한 phase별 train/val manifest 기반으로 학습/검증 분리 |
| Manifest 통계 출력 | ✅ 완료 | 생성 직후 source/modality/class/tag/empty 분포 출력 |
| Homogeneous modality batch | ✅ 완료 | rgb-only / thermal-only / pair sample을 batch 내부에서 섞지 않음 |
| Phase별 modality 검증 | ✅ 완료 | `allow_rgb_only` / `allow_thm_only` / `allow_pairs` 위반 시 학습 시작 전 중단 |
| 클래스 가중치 phase별 주입 | ✅ 완료 | `phases.yaml`의 `class_weights`가 detection cls loss에 반영됨 |
| 샘플러 일반화 | ✅ 완료 | tag 기반 weighted homogeneous batch sampler로 manifest/ConcatDataset 공통 지원, threshold/weight 실데이터 검증 필요 |
| 추론 시 weather 입력 방법 | ✅ 정책 완료 | 영상 단위 수동 입력 + 기본 fallback 사용, `infer_video.py` 구현 필요 |
| Phase 3 GOP temp_c 값 결정 | ✅ 정책 완료 | source 단위 매크로값 사용: 주간 0.5/day, 야간 0.3/night |
