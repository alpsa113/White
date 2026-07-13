# YOLO26 Provider 코드

이 디렉터리는 YOLO26-M COCO 사전학습 checkpoint를 로드하기 위한 provider 코드 위치입니다.

현재 provider는 공식 Ultralytics 패키지 소스를 repo 내부 vendor 형태로 포함합니다.

```text
vendor/yolo26/
├── ultralytics/
├── LICENSE
├── pyproject.toml
└── README.md
```

## 요구 조건

- `configs/model.yaml`의 `model.backbone.provider_code`는 `vendor/yolo26`을 가리킵니다.
- Colab/로컬 런타임에서 이 경로가 `sys.path`에 추가된 뒤 checkpoint가 로드됩니다.
- checkpoint는 `torch.load(..., weights_only=False)`로 로드 가능해야 합니다.
- checkpoint 내부에는 `model` 또는 `ema` 키로 `nn.Module`이 들어 있어야 합니다.
- 로드된 모델은 레이어 graph를 `model.model`로 노출해야 합니다.
- `model.model`은 `nn.ModuleList` 또는 `nn.Sequential`이어야 합니다.
- C3/C4까지만 실행 가능한 레이어 graph여야 하며, 학습 forward에서 neck/head는 호출하지 않습니다.

## 라이선스

Ultralytics provider 코드는 AGPL-3.0 라이선스를 따릅니다.
라이선스 전문은 `vendor/yolo26/LICENSE`를 확인하세요.

## Weight 관리

사전학습 weight 파일은 이 디렉터리에 저장하지 않습니다.
`yolo26m-coco.pt`는 Google Drive 등 외부 저장소에 두고, 기본 Colab 경로는 아래를 사용합니다.

```text
/content/drive/MyDrive/dual_yolo/weights/yolo26m-coco.pt
```
