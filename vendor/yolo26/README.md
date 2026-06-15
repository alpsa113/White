# YOLO26 Provider

Place the YOLO26 model source code used to create `yolo26m-coco.pt` in this
directory.

Requirements:
- The provider code must define the same Python classes referenced by the
  checkpoint.
- The checkpoint must load with `torch.load(..., weights_only=False)` and expose
  an `nn.Module` under `model` or `ema`.
- The loaded model must expose its layer graph as `model.model`
  (`nn.ModuleList` or `nn.Sequential`).
- The layer graph must support C3/C4 truncated execution without running the
  neck/head layers.

Do not store pretrained weight files in this directory.
