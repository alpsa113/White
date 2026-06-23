from pathlib import Path

from inference import DualYOLOPredictor


_DEFAULT_CHECKPOINT = Path("checkpoints/phase3/best.pt")
_DEFAULT_MODEL_CFG = Path("configs/model.yaml")

_predictor: DualYOLOPredictor | None = None


def get_predictor() -> DualYOLOPredictor:
    global _predictor

    if _predictor is None:
        if not _DEFAULT_CHECKPOINT.exists():
            raise FileNotFoundError(
                f"추론 checkpoint를 찾지 못했습니다: {_DEFAULT_CHECKPOINT}"
            )

        _predictor = DualYOLOPredictor(
            checkpoint_path=_DEFAULT_CHECKPOINT,
            model_cfg_path=_DEFAULT_MODEL_CFG,
            device="cpu",
        )

    return _predictor

def predict_image_arrays(
    rgb_image=None,
    thermal_image=None,
    conf: float = 0.25,
    nms: float = 0.6,
) -> dict:
    predictor = get_predictor()
    old_conf = predictor.conf_thresh
    old_nms = predictor.nms_thresh

    try:
        predictor.conf_thresh = conf
        predictor.nms_thresh = nms
        result = predictor.predict(
            rgb_image=rgb_image,
            thermal_image=thermal_image,
        )
        return result.to_dict()
    finally:
        predictor.conf_thresh = old_conf
        predictor.nms_thresh = old_nms
