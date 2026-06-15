# Weights

Store large model weight files outside Git.

Colab default path:

```text
/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt
```

Required pretrained backbone checkpoint:

```text
yolo26m-coco.pt
```

The file must be a PyTorch training checkpoint whose YOLO26 provider code is
available under `vendor/yolo26/` or otherwise importable in the Colab runtime.
