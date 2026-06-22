# Training Smoke Test CLI

phase1부터 phase3까지 학습 파이프라인이 최소 단위로 동작하는지 확인하는 명령입니다.

## 0. 준비

```bash
cd /Users/hl/Documents/Workspaces/White/dual_yolo
python -m pip install -r requirements.txt
ls weights/yolo26m-coco.pt
```

## 1. Manifest 생성

```bash
python tools/build_manifest_splits.py --config configs/splits/manifest_splits.yaml
ls data/manifests
```

## 2. Phase1 Smoke Test

```bash
python train.py \
  --phase 1 \
  --epochs 1 \
  --batch 2 \
  --img-size 320 \
  --device cuda
```

```bash
ls checkpoints/phase1
```

## 3. Phase2 Smoke Test

```bash
python train.py \
  --phase 2 \
  --init-from checkpoints/phase1/best.pt \
  --epochs 1 \
  --batch 2 \
  --img-size 320 \
  --device cuda
```

```bash
ls checkpoints/phase2
```

## 4. Phase3 Smoke Test

```bash
python train.py \
  --phase 3 \
  --init-from checkpoints/phase2/best.pt \
  --epochs 1 \
  --batch 2 \
  --img-size 320 \
  --device cuda
```

```bash
ls checkpoints/phase3
```

## CPU 최소 확인

GPU를 사용할 수 없으면 `--device cpu --no-amp`를 붙이고 `--batch 1`로 낮춥니다.

```bash
python train.py \
  --phase 1 \
  --epochs 1 \
  --batch 1 \
  --img-size 320 \
  --device cpu \
  --no-amp
```

## 통과 기준

```text
manifest 로드 성공
dataloader 생성 성공
모델 생성 성공
YOLO26 backbone weight 로드 성공
forward/loss/backward 성공
checkpoint 저장 성공
```

phase 전환은 `--init-from`을 사용합니다.
`--resume`은 같은 phase가 중간에 끊겼을 때만 사용합니다.
