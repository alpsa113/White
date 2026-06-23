from fastapi import FastAPI

from api.routes.health import router as health_router
from api.routes.inference import router as inference_router

app = FastAPI(title="DualYOLO API")

app.include_router(health_router)
app.include_router(inference_router)