from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.rebuild import router as rebuild_router
from app.api.websocket import router as websocket_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(rebuild_router)
api_router.include_router(websocket_router)
