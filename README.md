# DualYOLO GOP Boundary Detector

RGB and thermal dual-backbone object detector for GOP boundary monitoring.

The model uses a YOLO26-M COCO pretrained backbone for each modality, adaptive
middle fusion conditioned by weather, temperature, and illuminance, and a
three-phase training scenario for general pretraining, paired fusion learning,
and GOP-like fine-tuning.

## Current Status

- Architecture and training policy are documented in `ARCHITECTURE.md` and
  `TRAINING_SCENARIO.md`.
- The training pipeline supports manifest-based train/validation splits.
- Validation computes mAP@0.5 and saves best/final checkpoints.
- Local smoke testing has passed with synthetic data and a tiny test checkpoint.
- Real training still requires the actual YOLO26 provider code, pretrained
  checkpoint, and dataset manifests.

## Repository Layout

```text
configs/
  model.yaml                     # model, backbone, and training defaults
  phases.yaml                    # phase-specific training configuration
  splits/manifest_splits.yaml    # source-to-manifest split configuration
data/                            # dataset loaders and transforms
model/                           # DualYOLO, backbone, fusion, FPN, heads
tools/
  build_manifest_splits.py       # creates phase train/val manifests
training/                        # loss, metrics, trainer, phase scheduler
vendor/yolo26/                   # YOLO26 provider code placeholder
weights/                         # weight README only; large weights stay out of Git
```

## Requirements

```bash
pip install -r requirements.txt
```

For the local environment used during smoke testing, the required packages were:

```text
torch
torchvision
opencv-python
albumentations
numpy
pyyaml
```

## Required External Assets

These files are intentionally not committed to Git.

### YOLO26 Provider Code

Place the YOLO26 model source code used to create the pretrained checkpoint under:

```text
vendor/yolo26/
```

The provider code must make the checkpoint's Python model classes importable in
the runtime. The loaded model must expose its layer graph as `model.model`
(`nn.ModuleList` or `nn.Sequential`).

### Pretrained Weight

Default Colab path:

```text
/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt
```

The checkpoint must be a PyTorch training checkpoint containing an `nn.Module`
under `model` or `ema`. State-dict-only, ONNX, TensorRT, and TorchScript export
files are not supported by the current truncated-backbone wrapper.

## Data Manifests

Training uses prebuilt manifest splits instead of random runtime splitting.

Generate manifests after configuring source paths in
`configs/splits/manifest_splits.yaml`:

```bash
python tools/build_manifest_splits.py \
  --config configs/splits/manifest_splits.yaml
```

Expected outputs:

```text
data/manifests/phase1_train.json
data/manifests/phase1_val.json
data/manifests/phase2_train.json
data/manifests/phase2_val.json
data/manifests/phase3_train.json
data/manifests/phase3_val.json
```

The manifest builder prints source, modality, class, tag, and empty-image
statistics so the actual data distribution can be checked before training.

## Training

Phase 1:

```bash
python train.py --phase 1 --device cuda
```

Phase 2 from the best Phase 1 checkpoint:

```bash
python train.py \
  --phase 2 \
  --resume checkpoints/phase1/best.pt \
  --device cuda
```

Phase 3 from the best Phase 2 checkpoint:

```bash
python train.py \
  --phase 3 \
  --resume checkpoints/phase2/best.pt \
  --device cuda
```

Quick one-epoch check:

```bash
python train.py --phase 1 --batch 1 --epochs 1 --img-size 640 --device cuda
```

## Git Policy

The repository tracks code, configuration, and documentation only.

Ignored by default:

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

Store large datasets, generated manifests, checkpoints, and pretrained weights
outside Git, preferably under Google Drive for Colab workflows.
