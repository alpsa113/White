# DualYOLO 실험 설계

이 문서는 현재 DualYOLO 구조에서 모델 선택의 타당성을 검증하기 위한 비교 실험을 정리합니다.

## 비교 목적

프로젝트의 핵심 검증 질문은 두 가지입니다.

1. RGB/TIR 멀티모달 입력을 사용하는 DualYOLO가 RGB-only 비교군보다 탐지 성능이 좋은가?
2. YOLO26m 백본을 사용하는 DualYOLO가 YOLO11m 백본 비교군보다 탐지 성능이 좋은가?

## 공통 조건

모든 비교 실험은 가능한 한 아래 조건을 동일하게 유지합니다.

- 동일한 manifest split 사용
- 동일한 phase별 epoch, batch, image size 사용
- 동일한 optimizer, scheduler, loss, metric 코드 사용
- 동일한 class id 사용: `person=0`, `boar=1`, `deer=2`, `non_target=3`
- 동일한 평가 지표 사용: validation loss, mAP50, mAP50-95, class별 AP, person precision/recall/F1
- 동일한 검증 데이터로 최종 checkpoint 평가

성능 비교에서는 `best.pt` 기준 결과와 `final.pt` 기준 결과를 모두 기록하되, 모델 선택 판단은 주로 같은 검증셋의 `best.pt` mAP50, AP_person, Recall_person을 기준으로 합니다.

## 기본 DualYOLO: YOLO26m 백본

기본 모델은 `configs/model.yaml`과 `configs/phases.yaml`을 사용합니다.

```bash
python train.py --phase 1 --model-cfg configs/model.yaml --phase-cfg configs/phases.yaml
python train.py --phase 2 --model-cfg configs/model.yaml --phase-cfg configs/phases.yaml --init-from checkpoints/phase1/best.pt
python train.py --phase 3 --model-cfg configs/model.yaml --phase-cfg configs/phases.yaml --init-from checkpoints/phase2/best.pt
```

## RGB-only 비교군

RGB-only 비교군은 멀티모달 효과를 확인하기 위한 ablation입니다.

- 설정 파일: `configs/model.yaml`, `configs/phases_rgb_only.yaml`
- split 파일: `configs/splits/manifest_splits_rgb_only.yaml`
- Phase2는 RGB/TIR pair fusion 단계이므로 실행하지 않습니다.
- Thermal 입력은 사용하지 않고 RGB 단일 입력만 사용합니다.

```bash
python tools/build_manifest_splits.py --config configs/splits/manifest_splits_rgb_only.yaml
python train.py --phase 1 --model-cfg configs/model.yaml --phase-cfg configs/phases_rgb_only.yaml --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only
python train.py --phase 3 --model-cfg configs/model.yaml --phase-cfg configs/phases_rgb_only.yaml --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only --init-from /content/drive/MyDrive/dual_yolo/checkpoints_rgb_only/phase1/best.pt
```

## YOLO11m 백본 비교군

YOLO11m 비교군은 백본 선택의 효과를 확인하기 위한 실험입니다.

- 모델 설정 파일: `configs/model_yolo11m.yaml`
- phase 설정 파일: `configs/phases_yolo11m.yaml`
- weight 파일: `weights/yolo11m.pt`
- manifest split은 기본 DualYOLO와 동일한 `data/manifests/*.json`을 사용합니다.

비교 공정성을 위해 fusion, FPN, detection head, loss, scheduler, 데이터 split은 YOLO26m 기본 모델과 동일하게 유지합니다. 변경되는 부분은 YOLO 백본 checkpoint와 백본 provider 로딩 경로뿐입니다.

```bash
python train.py --phase 1 --model-cfg configs/model_yolo11m.yaml --phase-cfg configs/phases_yolo11m.yaml --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_yolo11m
python train.py --phase 2 --model-cfg configs/model_yolo11m.yaml --phase-cfg configs/phases_yolo11m.yaml --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_yolo11m --init-from /content/drive/MyDrive/dual_yolo/checkpoints_yolo11m/phase1/best.pt
python train.py --phase 3 --model-cfg configs/model_yolo11m.yaml --phase-cfg configs/phases_yolo11m.yaml --save-dir /content/drive/MyDrive/dual_yolo/checkpoints_yolo11m --init-from /content/drive/MyDrive/dual_yolo/checkpoints_yolo11m/phase2/best.pt
```

## 결과 기록 양식

| 실험 | 백본 | 입력 | Phase | best mAP50 | mAP50-95 | AP_person | Recall_person | Precision_person | F1_person | 비고 |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| DualYOLO | YOLO26m | RGB+TIR | 3 |  |  |  |  |  |  | 기본 모델 |
| RGB-only | YOLO26m | RGB | 3 |  |  |  |  |  |  | Phase2 생략 |
| DualYOLO-YOLO11m | YOLO11m | RGB+TIR | 3 |  |  |  |  |  |  | 백본 비교군 |

class별 상세 AP는 별도 표에 기록합니다.

| 실험 | AP_person | AP_boar | AP_deer | AP_non_target | 비고 |
|---|---:|---:|---:|---:|---|
| DualYOLO |  |  |  |  |  |
| RGB-only |  |  |  |  |  |
| DualYOLO-YOLO11m |  |  |  |  |  |

`best.pt` 기준 추가 평가 산출물은 아래 명령으로 생성합니다.

```bash
python tools/evaluate_checkpoint.py \
  --checkpoint /content/drive/MyDrive/dual_yolo/checkpoints/phase3/best.pt \
  --phase 3 \
  --prefix phase3
```

비교 실험별로 `summary.json`, `threshold_table_person.csv`, `pr_curve_person.png`, `confusion_matrix.png`를 보관합니다.

## 해석 기준

- RGB-only 대비 DualYOLO의 mAP50, AP_person, Recall_person이 높으면 멀티모달 구조의 이점을 주장할 수 있습니다.
- YOLO11m 대비 YOLO26m의 mAP50, mAP50-95, AP_person이 높으면 YOLO26m 백본 선택의 근거가 됩니다.
- 특정 클래스만 개선되는 경우에는 전체 mAP50뿐 아니라 GOP 핵심 클래스인 `person`, `boar`, `deer`의 AP를 따로 해석합니다.
- `non_target`은 오탐 억제 목적이 강하므로 AP뿐 아니라 실제 추론 이미지/영상에서 false positive 변화도 함께 확인합니다.
- PR curve는 confidence threshold 선정 근거로 사용하고, confusion matrix는 클래스 간 오분류와 background 오탐을 확인하는 용도로 사용합니다.
