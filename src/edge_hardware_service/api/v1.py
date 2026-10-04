from fastapi import APIRouter
from .routers.gpio import router as gpio_router
#from .routers.camera import router as camera_router
from .routers.health import router as health_router

__all__ = ["gpio_router", "health_router"]

router = APIRouter(prefix="/app/v1")
router.include_router(health_router)
router.include_router(gpio_router)
#router.include_router(camera_router)