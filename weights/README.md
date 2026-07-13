# Weight 관리

대용량 모델 weight 파일은 Git에 올리지 않습니다.

Colab 기준 기본 경로:

```text
/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt
```

필수 사전학습 백본 checkpoint:

```text
yolo26m-coco.pt
```

이 파일은 PyTorch 학습 checkpoint여야 합니다.
checkpoint 내부에는 `model` 또는 `ema` 키로 실제 `nn.Module`이 들어 있어야 합니다.

YOLO26 provider 코드는 `vendor/yolo26/` 아래에 포함되어 있거나,
Colab 런타임에서 import 가능한 상태여야 합니다.
