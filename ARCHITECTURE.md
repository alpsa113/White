# DualYOLO Architecture Pipeline
> 버전: v0.5.4  
> 최종 수정: 2026-06-15  
> 이 파일이 구현의 단일 진실 공급원(SSoT)입니다.  
> **코드 수정 전 반드시 이 파일을 먼저 업데이트하세요.**

---

## 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| v0.1.0 | 2026-06-12 | 초기 아키텍처 정의 |
| v0.2.0 | 2026-06-12 | Phase 3 hard negative 전략 업데이트 (소형 동물 background + 원거리 person 샘플 병행 필수) |
| v0.3.0 | 2026-06-12 | Dual Backbone을 ResNet50/34 → YOLO26-M/M으로 교체. RGB·THM 채널 수 대칭화 (C3:256, C4:512) |
| v0.4.0 | 2026-06-12 | Detection Head 스타일 표기 정정 (YOLOX/YOLOv8 → YOLOX). reg loss Smooth L1 → CIoU 업그레이드 |
| v0.5.0 | 2026-06-15 | cond_vec 7→3차원 축소 (sensor_quality·humidity·wind_speed·visibility 제거). Phase 2 데이터 LLVIP 단독으로 변경 (KAIST → Phase 1으로 이동). weather augmentation 전략 추가. 데이터셋별 temp_c 매크로값 명시. MLP 입력 7→3 업데이트. fusion_reg 야간 판별 버그 수정 (< 2.0 → == 0). |
| v0.5.1 | 2026-06-15 | background 클래스를 non_target으로 명확화. CIoU decode 좌표계 명시. fusion_reg를 C3+C4 평균으로 확정. uncertainty 활성 시 det cls/reg 손실 대체 방식 명시. |
| v0.5.2 | 2026-06-15 | weather 원시값(0~3)을 MLP 입력 전 `weather / 3.0`으로 정규화하도록 조건벡터 스펙 명확화. illuminance는 0/1 이진값 유지. |
| v0.5.3 | 2026-06-15 | YOLO26-M 백본 피처 추출 방식을 full forward hook이 아닌 C4까지만 실행하는 truncated wrapper로 명확화. Neck/Head forward 금지 원칙 추가. |
| v0.5.4 | 2026-06-15 | Manifest split, homogeneous modality batch, Phase 3 source 단위 cond_vec, weighted homogeneous hard-negative sampling 정책 반영. |
| v0.5.5 | 2026-06-15 | YOLO26-M COCO pretrained 백본을 Google Drive/local checkpoint 기반 필수 로드 방식으로 명확화. 랜덤 초기화 fallback 금지. |

---

## 1. 전체 파이프라인

```
입력
  RGB   [B, 3, H, W]   (없으면 None)
  열화상 [B, 1, H, W]  (없으면 None)
  조건벡터 [B, 3]       (없으면 DEFAULT_COND)
       │
       ▼
┌─────────────────────────────┐
│       Dual Backbone         │
│  RGB → YOLO26-M (stride 16) │
│  THM → YOLO26-M (stride 16) │
│  출력: C3 (stride 8)        │
│       C4 (stride 16)        │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│    Adaptive Middle Fusion   │
│  조건벡터 → MLP → α, β     │
│  fused = α·proj_rgb         │
│        + β·proj_thm         │
│  (단독 모달은 해당 proj만)  │
│  출력: fused_c3, fused_c4   │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────────────────┐
│           FPN               │
│  P4 = conv(fused_c4)        │
│  P3 = conv(up(P4) + fused_c3)│
│  출력 채널: fpn_dim=256      │
└──────┬──────────────┬───────┘
       │              │
      P3             P4
(stride 8)      (stride 16)
(small obj)     (large obj)
       │              │
       ▼              ▼
┌─────────────────────────────┐
│    Multi-Scale Det Heads    │
│  각 스케일 독립 적용         │
│  cls [B, 4, H, W]           │
│  reg [B, 4, H, W]  (cxcywh) │
│  obj [B, 1, H, W]           │
└─────────────────────────────┘
       │
       ▼ (조건부 활성화)
┌─────────────────────────────┐
│     Uncertainty Head        │
│  log_var_cls [B, 4, H, W]   │
│  log_var_reg [B, 4, H, W]   │
│  Phase 2 후반 ~ 3에서 활성  │
└─────────────────────────────┘

별도 분기:
┌─────────────────────────────┐
│       Aux Heads × 2         │
│  RGB C4  → GAP → FC → [B,3] │
│  THM C4  → GAP → FC → [B,3] │
│  Phase 1·2에서 활성          │
└─────────────────────────────┘
```

---

## 2. 모듈별 상세 스펙

### 2-1. Dual Backbone

| 항목 | RGB 백본 | 열화상 백본 |
|------|----------|-------------|
| 베이스 | YOLO26-M | YOLO26-M |
| depth multiplier | 0.50 | 0.50 |
| width multiplier | 1.00 | 1.00 |
| 입력 채널 | 3 | 1 |
| 사전학습 | COCO detection | COCO detection (conv1 가중치 3ch 평균 → 1ch inflation) |
| 핵심 블록 | C3k2 + C2PSA | C3k2 + C2PSA |
| 피처 추출 방식 | truncated backbone wrapper (C4까지만 forward) | truncated backbone wrapper (C4까지만 forward) |
| C3 채널 | 256 | 256 |
| C4 채널 | 512 | 512 |
| C3 stride | 8 | 8 |
| C4 stride | 16 | 16 |

> RGB·THM 채널 수가 완전히 대칭이므로 Fusion projection 구조가 균형을 이룸.

**YOLO26-M 백본 실행 원칙:**
- 백본은 `provider=local_checkpoint`로 지정한 PyTorch training checkpoint에서 로드한다.
- YOLO26 provider 코드는 repo 내부 `vendor/yolo26/`에 고정해 Colab과 로컬에서 같은 모델 클래스를 import한다.
- Colab 기준 기본 경로는 `/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt`이다.
- checkpoint는 내부 layer graph에 접근 가능한 `nn.Module`을 `model` 또는 `ema` 키로 포함해야 한다.
- `nn.Module` checkpoint 로드를 위해 checkpoint를 생성한 YOLO26 모델 코드/패키지가 Colab 런타임에서 import 가능해야 한다.
- state-dict-only, ONNX, TensorRT, TorchScript export는 C3/C4 truncated training wrapper 입력으로 사용하지 않는다.
- pretrained checkpoint가 없거나 C3/C4 shape 검증에 실패하면 학습을 중단한다. 랜덤 초기화 fallback은 허용하지 않는다.
- C3/C4 layer index 확정 후 wrapper에는 C4까지의 `ModuleList`만 등록하고 이후 Neck/Head/Tail 파라미터는 보관하지 않는다.
- YOLO26-M 전체 detection model을 끝까지 forward하지 않는다.
- Backbone에서 stride 8(C3), stride 16(C4) 피처가 생성되는 지점까지만 실행한다.
- Neck/Head 레이어는 학습 forward 경로에서 호출하지 않는다.
- C3/C4 추출을 위해 full model forward + hook 방식을 사용하지 않는다.
- hook은 레이어 위치 검증 또는 디버깅 용도로만 허용한다.

**단독 모달 처리:**  
- `rgb=None` → RGB 백본 skip, gradient 없음  
- `thermal=None` → 열화상 백본 skip, gradient 없음  
- 학습 batch는 `rgb` / `thermal` / `pair` 중 하나의 modality 타입만 포함한다.
- mixed-modality sample을 같은 batch에 섞지 않는다.
- phase별 `allow_rgb_only`, `allow_thm_only`, `allow_pairs` 정책을 DataLoader 구성 시 검증한다.

---

### 2-2. Adaptive Middle Fusion

**입력:**
- `rgb_c3`: [B, 256, H/8, W/8]
- `rgb_c4`: [B, 512, H/16, W/16]
- `thm_c3`: [B, 256, H/8, W/8]
- `thm_c4`: [B, 512, H/16, W/16]
- `cond_vec`: [B, 3]

**연산:**
```
proj_rgb = Conv1x1+BN+ReLU(rgb_c4)  → [B, 256, H/16, W/16]
proj_thm = Conv1x1+BN+ReLU(thm_c4)  → [B, 256, H/16, W/16]

[α_raw, β_raw] = MLP(cond_vec)       → [B, 256*2]
                 reshape              → [B, 2, 256]
α, β = softmax(dim=1)                → [B, 256] each  (채널별, 합=1)

fused_c4 = α[:,i,None,None] * proj_rgb
          + β[:,i,None,None] * proj_thm   ∀ i

(C3도 동일 구조, 독립적인 weight_net)
```

**MLP 구조:**
```
Linear(3 → 64) → ReLU → Linear(64 → 64) → ReLU → Linear(64 → 512)
```
> cond_vec 3차원 (weather, temp_c, illuminance) 반영.

**단독 모달:**
- `rgb=None` → `fused = proj_thm` (가중치 무시)
- `thm=None` → `fused = proj_rgb`

**손실용 출력:** `_alpha_c4`, `_beta_c4`, `_alpha_c3`, `_beta_c3` (fusion reg loss 용)

---

### 2-3. FPN

```
P4 = OutConv(LateralConv(fused_c4))               [B, 256, H/16, W/16]
P3 = OutConv(LateralConv(fused_c3) + Upsample(P4)) [B, 256, H/8,  W/8]
```

- `LateralConv`: Conv1×1  
- `OutConv`: Conv3×3 + BN + ReLU  
- Upsample: nearest, size = fused_c3.shape[-2:]

---

### 2-4. Detection Head (per scale)

**Decoupled Head (YOLOX 스타일)**

```
cls_stem: Conv3x3+BN+SiLU → Conv3x3+BN+SiLU
cls_pred: Conv1x1 → [B, 4, H, W]   (4 classes)

reg_stem: Conv3x3+BN+SiLU → Conv3x3+BN+SiLU
reg_pred: Conv1x1 → [B, 4, H, W]   (cx_rel, cy_rel, log_w, log_h)
obj_pred: Conv1x1 → [B, 1, H, W]
```

**클래스 정의 (전 페이즈 고정):**

| ID | 클래스 |
|----|--------|
| 0 | person |
| 1 | boar |
| 2 | deer |
| 3 | non_target |

**reg loss:** CIoU (박스 중심 정렬 + 종횡비 일관성 동시 최적화)
> Smooth L1 대비 클래스별 형태 차이(사람=세로형 / 멧돼지=가로형)를 손실 신호에 직접 반영.

**CIoU 좌표계:**
1. Detection Head의 `reg_pred`는 각 positive grid에서 `(cx_rel, cy_rel, log_w, log_h)`를 출력한다.
2. `log_w`, `log_h`는 decode 전 `[-4, 4]`로 clamp한다.
3. `cx = (grid_x + cx_rel) * stride`, `cy = (grid_y + cy_rel) * stride`, `w = exp(clamp(log_w, -4, 4)) * stride`, `h = exp(clamp(log_h, -4, 4)) * stride`로 이미지 절대 좌표계의 `cxcywh` 박스로 decode한다.
4. decode된 예측 박스와 GT 박스를 동일한 이미지 절대 좌표계의 `xyxy`로 변환한 뒤 positive grid 위치에서 CIoU를 계산한다.

**obj + Uncertainty Head 분리 운용:**
```
obj 높음 + uncertainty 낮음  →  확실한 탐지  →  즉각 경보
obj 높음 + uncertainty 높음  →  탐지됐으나 불확실  →  주의 요망
obj 낮음                      →  배경/비대상 영역 필터링
```

> `non_target`은 박스가 있는 비대상 객체(예: 소형 동물, 열 교란 객체)를 명시적으로 학습하기 위한 클래스이다.
> 박스가 없는 일반 배경은 `obj=0`으로 처리한다.

**타겟 매칭:** Center-point 기반 (추후 SimOTA 교체 예정)

---

### 2-5. Aux Head

```
입력: backbone C4 [B, C, H, W]
→ AdaptiveAvgPool2d(1)
→ Flatten
→ Linear(C → 256) → ReLU → Dropout(0.3)
→ Linear(256 → 3)   (person / boar / deer, non_target 제외)
```

- RGB Aux: `rgb_c4` (512ch 입력)
- THM Aux: `thm_c4` (512ch 입력)
- 활성화: Phase 1, 2 / Phase 3 선택

---

### 2-6. Uncertainty Head

**Aleatoric 불확실성 (Kendall & Gal 2017)**

```
입력: FPN 피처 [B, 256, H, W]
→ Conv3x3+BN+SiLU → Conv3x3+BN+SiLU(128ch)
→ log_var_cls: Conv1x1 → [B, 4, H, W]
→ log_var_reg: Conv1x1 → [B, 4, H, W]
```

**손실 적용:**
```
ℒ_unc = 0.5 * exp(-s) * ℒ_base + 0.5 * s
        (s = log σ²)
```

- 활성화: Phase 2 후반 (epoch ≥ max_epochs//2) ~ Phase 3

---

## 3. 손실 함수

| 손실 | 대상 | 수식 | 활성 조건 |
|------|------|------|-----------|
| `det_cls` | cls 예측 | Focal Loss (α=0.25, γ=2) | 항상 |
| `det_reg` | reg 예측 | CIoU (또는 uncertainty NLL) | 항상 |
| `det_obj` | objectness | BCE (pos_weight=5) | 항상 |
| `aux_rgb` | RGB Aux Head | CrossEntropy | Phase 1·2 |
| `aux_thm` | THM Aux Head | CrossEntropy | Phase 1·2 |
| `fusion_reg` | β 가중치 (C3+C4 평균) | ReLU(0.4 - (β_c3_night + β_c4_night) / 2).mean() | Phase 2·3 |
| `uncertainty` | log σ² | heteroscedastic NLL | Phase 2후반~3 |

**Uncertainty 손실 적용 방식:**
- uncertainty 비활성: `det_cls = Focal Loss`, `det_reg = CIoU`
- uncertainty 활성: `det_cls`, `det_reg`를 각각 heteroscedastic NLL 형태로 대체
- `det_obj`는 uncertainty와 분리하여 BCE를 유지

**총 손실:**
```
ℒ = ℒ_det_p3 + ℒ_det_p4
  + 0.3 * (ℒ_aux_rgb + ℒ_aux_thm)   [aux_active]
  + 0.1 * ℒ_fusion_reg               [fusion_reg_active]
```

`ℒ_det` 내부의 cls/reg 항은 uncertainty 활성 여부에 따라 일반 손실 또는 NLL 대체 손실을 사용한다.

---

## 4. 학습 시나리오

### Phase 1 — 다양한 환경 사전학습

| 항목 | 설정 |
|------|------|
| max_epochs | 30 |
| 데이터 | COCO·야생동물 RGB + KAIST(person 프레임 필터링) + 열화상 단독 + 페어 혼합 |
| modality_dropout | 0.2 |
| weather augmentation | RandomRain·RandomFog·RandomSnow 적용 → cond_vec weather 인덱스 동기화 |
| Aux Head | ✅ |
| Uncertainty | ❌ |
| Fusion Reg | ❌ |
| backbone lr | 1e-5 |
| fusion/fpn/head lr | 1e-4 |

### Phase 2 — 페어 데이터 융합 학습

| 항목 | 설정 |
|------|------|
| max_epochs | 20 |
| 데이터 | LLVIP 단독 (페어 전용, person 라벨) |
| cond_vec | illuminance=0.0, temp_c=0.2 하드코딩 |
| modality_dropout | 0.05 |
| weather augmentation | RandomRain·RandomFog·RandomSnow 적용 → cond_vec weather 인덱스 동기화 |
| Aux Head | ✅ |
| Uncertainty | ❌ → ✅ (epoch 10~) |
| Fusion Reg | ✅ |
| backbone lr | 5e-6 |
| fusion/fpn/head lr | 1e-5 |
| uncertainty lr | 1e-4 (optimizer group은 시작부터 존재, forward/loss는 후반부 활성) |

> **KAIST 제외 근거**: KAIST는 차량·도심 도로 중심 이미지로 GOP 자연지형과 열 분포가 크게 다르고 person 비율이 낮아 fusion 학습을 오염시킬 수 있음. Phase 1에서 다양성 확보 용도로만 사용.

### Phase 3 — GOP 유사 환경 Fine-tuning

| 항목 | 설정 |
|------|------|
| max_epochs | 15 |
| 데이터 | GOP 유사 RGB + CycleGAN synthetic TIR pair 중심, single-modality hard negative 보강 |
| 전반부 (epoch < 8) | 백본 동결, rest lr=1e-5 |
| 후반부 (epoch ≥ 8) | 전체 해제, 전 파라미터 lr=5e-6 |
| Aux Head | ❌ (선택) |
| Uncertainty | ✅ |
| Fusion Reg | ✅ |

**Hard Negative 샘플링 전략**

| 샘플 유형 | 라벨 | 목적 | 주의사항 |
|-----------|------|------|----------|
| 야간·폭설·안개·강한 열 교란 | person / boar / deer | 극한 환경 적응 | — |
| 원거리 person (50~200m+ 실촬영) | person | 소형 픽셀 표현 학습 | 스케일 증강만으로 대체 불가, 실 데이터 필수 |
| 소형 동물 (여우·토끼 등) | non_target | "작은 열 덩어리 = person" 과적합 억제 | **원거리 person 샘플과 반드시 병행** — 소형 동물만 단독 투입 시 원거리 person 탐지 억제 역효과 발생 |
| 스케일 증강 (기존 샘플 축소) | 원본 라벨 유지 | 거리 다양성 보완 | 실 데이터 부족 시 보조 수단 |

> **핵심 제약:** 소형 동물 non_target 샘플과 원거리 person 샘플은 반드시 함께 구성해야 한다.
> 소형 동물만 단독 투입 시 모델이 "작은 열 덩어리 전체 = non_target"을 학습할 위험이 있다.

**Phase 3 데이터 구성 원칙:**
- 기본축은 GOP 유사 RGB 원본과 같은 프레임에서 생성한 CycleGAN synthetic TIR pair이다.
- CycleGAN synthetic TIR은 RGB와 같은 원본 프레임에서 생성된 경우 paired thermal로 취급한다.
- 실제 TIR과 CycleGAN synthetic TIR이 모두 있으면 source를 분리해 manifest에 기록한다.
- 원거리 person, 소형 동물 `non_target`, 검수된 empty background는 pair가 아니어도 single-modality 보강 샘플로 허용한다.
- Phase 3 초기 source 비율은 GOP pair 60~70%, 원거리 person 15~20%, small non_target 15~20%, 검수 empty background 5~10%를 기준으로 시작한다.

**Hard Negative 태그 산출:**
- 기본은 annotation의 box/label 기반 자동 태그 산출을 사용한다.
- `label == person`이고 box area `< 32×32`이면 `distant_person` 태그를 부여한다.
- `label == non_target`이면 `non_target` 태그를 부여하고, box area `< 32×32`이면 `small_non_target` 태그를 추가한다.
- meta 파일에 `tags`가 있으면 자동 태그와 union하여 사용한다.
- Phase 3 sampler는 `distant_person`과 `small_non_target`을 함께 가중 샘플링한다.

---

## 5. 조건벡터 스펙

7차원 → 3차원으로 축소. 실측 불가(sensor_quality·humidity·wind_speed) 및 중복(visibility) 차원 제거.

| Index | 의미 | 원시값 | MLP 입력값 | 공급 방법 |
|-------|------|--------|-----------|----------|
| 0 | weather | 0=맑음, 1=강우, 2=폭설, 3=안개 | `weather / 3.0` → 0.0~1.0 | 학습 시 augmentation 적용과 동기화 |
| 1 | temp_c | 0.0 ~ 1.0 | 그대로 | 데이터셋 레벨 매크로 고정값 |
| 2 | illuminance | 0=야간, 1=주간 | 그대로 | 데이터셋 레벨 매크로 고정값 |

> 세 차원 모두 MLP 입력 시 [0, 1] 범위로 통일됨. weather는 원시 정수값을 3으로 나눠 정규화.

**조건벡터 입력 규칙:**
- dict 메타데이터의 `weather` 값은 항상 원시 weather ID(0=맑음, 1=강우, 2=폭설, 3=안개)로 간주하고 내부에서 `weather / 3.0`으로 정규화한다.
- list/tuple/tensor 형태의 `cond_vec[0]`은 이미 정규화된 MLP 입력값으로 간주하고 그대로 사용한다.
- 외부 데이터셋 메타데이터는 dict 형태를 권장하고, 내부 fallback·로더 상수는 정규화된 3차원 list를 사용한다.
- train transform은 clear/rain/snow/fog 중 최대 하나의 weather augmentation만 선택하고, 선택된 `weather_id / 3.0`으로 `cond_vec[0]`을 갱신한다.

**데이터셋별 매크로값:**

| 데이터셋 | weather | temp_c | illuminance |
|---------|---------|--------|-------------|
| LLVIP | augmentation 연동 | 0.2 (가을~겨울 야간) | 0.0 (전체 야간) |
| KAIST (Phase 1) | augmentation 연동 | 0.3 (한국 사계절 혼합) | set 이름 기반 자동 판별 |
| Phase 1 일반 (COCO 등) | augmentation 연동 | 0.5 (DEFAULT) | 이미지 밝기 기반 추정 또는 DEFAULT |
| Phase 3 GOP day pair | augmentation 연동 | 0.5 (주간 일반) | 1.0 (주간) |
| Phase 3 GOP night pair | augmentation 연동 | 0.3 (야간·저온) | 0.0 (야간) |
| Phase 3 hard negative day | augmentation 연동 | 0.5 (주간 일반) | 1.0 (주간) |
| Phase 3 hard negative night | augmentation 연동 | 0.3 (야간·저온) | 0.0 (야간) |

**추론 시 조건벡터 입력 정책:**
- 초기 추론은 센서 메타데이터와 자동 weather 추정을 사용하지 않는다.
- 영상 단위로 운용자가 `weather`, `illuminance`, `temp_c`를 지정한다.
- 지정하지 않은 경우 `weather=clear`, `illuminance=night`, `temp_c=0.3`을 사용한다.
- 동일 영상 내 모든 프레임에는 동일한 `cond_vec`를 적용한다.
- `infer_video.py`는 학습 파이프라인, manifest split, 후처리 정책 확정 후 생성한다.

**fallback (메타데이터 없는 데이터셋):**
```python
DEFAULT_COND = [0.0, 0.5, 1.0]  # weather=맑음, temp_c=중간, illuminance=주간
```

`fusion_reg_loss`는 index 2 (illuminance == 0) 기준으로 야간 판별.

---

## 6. 파일 구조

```
dual_yolo/
├── ARCHITECTURE.md          ← 이 파일 (SSoT)
├── model/
│   ├── backbone.py          DualBackbone (RGBBackbone + ThermalBackbone)
│   ├── fusion.py            AdaptiveFusion + ConditionWeightNet
│   ├── fpn.py               FPN (P3, P4)
│   ├── heads.py             YOLODetectionHead / AuxHead / UncertaintyHead / MultiScaleHeads
│   └── dual_yolo.py         DualYOLO (조립 + get_param_groups)
├── training/
│   ├── losses.py            DetectionLoss / DualYOLOLoss
│   ├── metrics.py           mAP@0.5 / decode_detections
│   ├── phases.py            PhaseConfig / PhaseScheduler / build_optimizer
│   └── trainer.py           Trainer
├── data/
│   ├── dataset.py           GenericDetectionDataset + collate_fn
│   ├── kaist_loader.py      KAISTDataset
│   ├── llvip_loader.py      LLVIPDataset
│   └── transforms.py        build_transforms (albumentations)
├── configs/
│   ├── model.yaml
│   ├── phases.yaml
│   └── splits/
│       └── manifest_splits.yaml
├── tools/
│   └── build_manifest_splits.py
└── train.py
```

---

## 7. 미결 과제 및 검증 항목

| 항목 | 현황 | 우선순위 |
|------|------|---------|
| 동적 타겟 매칭 검토 | center-point baseline 학습 후 TaskAlignedAssigner 우선 / SimOTA 대안 검토 | 중 |
| 검증 데이터셋 경로 구성 | ✅ mAP@0.5 검증 루프 및 phase별 train/val manifest 경로 구성 완료, 실제 manifest 생성 후 샘플 수 검증 필요 | 높음 |
| Hard negative 샘플러 | annotation 기반 auto tag + weighted homogeneous batch sampler 구현됨, 데이터별 threshold/weight 검증 필요 | 중 |
| KAIST XML 어노테이션 파서 | txt 포맷만 지원 | 낮음 |
| 열화상 단독 Phase 1 패스 | ✅ homogeneous modality batch sampler로 rgb-only / thermal-only / pair batch 분리, 실제 데이터 비율 검증 필요 | 낮음 |
| weather augmentation ↔ cond_vec 연동 | WeatherAwareTransform으로 clear/rain/snow/fog 선택값을 cond_vec[0]에 자동 반영, 확률/시각 품질 검증 필요 | 높음 |
| KAIST person 프레임 필터링 | ✅ `require_person: true`로 person 라벨 있는 프레임만 선별 구현됨, 실제 split 경로 검증 필요 | 중 |
| 추론 시 weather 입력 방법 | ✅ 영상 단위 수동 입력 + 기본 fallback 정책 확정, `infer_video.py` 구현 필요 | 낮음 |
| Phase 3 GOP temp_c 값 결정 | ✅ source 단위 매크로값 사용: 주간 0.5/day, 야간 0.3/night | 낮음 |

---

## 8. 버전 업그레이드 가이드

이 파일을 수정한 뒤 코드를 수정하세요.

1. 변경 이력 테이블에 버전·날짜·내용 추가
2. 해당 섹션의 스펙 업데이트
3. 코드 수정
4. 코드가 이 파일과 일치하는지 검토
