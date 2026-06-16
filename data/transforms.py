import albumentations as A
import cv2
import numpy as np


class WeatherAwareTransform:
    def __init__(
        self,
        pre_weather: A.Compose,
        weather_transforms: dict[int, A.Compose],
        normalize: A.Compose,
        probs: tuple[float, float, float, float] = (0.65, 0.10, 0.10, 0.15),
    ):
        self.pre_weather = pre_weather
        self.weather_transforms = weather_transforms
        self.normalize = normalize
        self.probs = probs

    def __call__(self, **kwargs):
        result = self.pre_weather(**kwargs)
        weather_id = int(np.random.choice([0, 1, 2, 3], p=self.probs))
        if weather_id != 0:
            result = self.weather_transforms[weather_id](**result)
        result = self.normalize(**result)
        result["weather_id"] = weather_id
        return result


def _compose(transforms: list, bbox_params: A.BboxParams) -> A.Compose:
    return A.Compose(
        transforms,
        bbox_params=bbox_params,
        additional_targets={"thermal": "image"},
    )


def _letterbox(img_size: int) -> list:
    """원본 비율을 유지한 채 목표 입력 크기까지 padding."""
    return [
        A.LongestMaxSize(max_size=img_size),
        A.PadIfNeeded(
            min_height=img_size,
            min_width=img_size,
            position="center",
            border_mode=cv2.BORDER_CONSTANT,
            fill=(114, 114, 114),
            fill_mask=0,
        ),
    ]


def build_transforms(mode: str = "train", img_size: int = 640):
    bbox_params = A.BboxParams(
        format="pascal_voc",
        label_fields=["labels"],
        min_area=64,
        min_visibility=0.3,
    )

    if mode == "train":
        pre_weather = _compose([
            *_letterbox(img_size),
            A.HorizontalFlip(p=0.5),
            A.ColorJitter(
                brightness=0.3, contrast=0.3, saturation=0.2, hue=0.1, p=0.6
            ),
            A.GaussNoise(std_range=(0.04, 0.12), p=0.3),
            A.MotionBlur(blur_limit=7, p=0.2),
        ], bbox_params)
        weather_transforms = {
            1: _compose([A.RandomRain(
                slant_range=(-10, 10),
                drop_length=20,
                blur_value=3,
                p=1.0,
            )], bbox_params),
            2: _compose([A.RandomSnow(p=1.0)], bbox_params),
            3: _compose([A.RandomFog(fog_coef_range=(0.1, 0.4), p=1.0)], bbox_params),
        }
        normalize = _compose([
            A.Normalize(
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            ),
        ], bbox_params)
        return WeatherAwareTransform(pre_weather, weather_transforms, normalize)
    else:  # 검증
        transforms = [
            *_letterbox(img_size),
            A.Normalize(
                mean=(0.485, 0.456, 0.406),
                std=(0.229, 0.224, 0.225),
            ),
        ]
        return _compose(transforms, bbox_params)
