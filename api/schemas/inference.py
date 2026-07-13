from pydantic import BaseModel


class DetectionResponse(BaseModel):
    class_id: int
    class_name: str
    score: float
    bbox: list[float]
    track_id: int | None = None


class ImagePredictionResponse(BaseModel):
    input_modality: str
    image_width: int
    image_height: int
    latency_ms: float
    detections: list[DetectionResponse]


class VideoMetadataResponse(BaseModel):
    rgb_path: str | None
    thermal_path: str | None
    output_path: str | None
    fps: float
    width: int
    height: int
    total_frames: int
    frame_stride: int
    processed_frames: int
    tracking: bool


class VideoFramePredictionResponse(ImagePredictionResponse):
    frame_index: int
    timestamp_ms: float


class VideoPredictionResponse(BaseModel):
    video: VideoMetadataResponse
    frames: list[VideoFramePredictionResponse]
