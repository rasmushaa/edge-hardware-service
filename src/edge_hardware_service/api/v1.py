"""Version 1 API router composition."""

from fastapi import APIRouter

from .routers.camera import router as camera_router
from .routers.gpio import router as gpio_router
from .routers.health import router as health_router

__all__ = ["camera_router", "gpio_router", "health_router"]

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(camera_router)
router.include_router(gpio_router)
