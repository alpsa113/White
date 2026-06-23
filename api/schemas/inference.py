from pydantic import BaseModel

class DetectionResponse(BaseModel):
    class_id: int
    class_name: str
    score: float
    bbox: list[float]

class ImagePredictionResponse(BaseModel):
    input_modality: str
    image_width: int
    image_height: int
    latency_ms: float
    detections: list[DetectionResponse]