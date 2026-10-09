from typing import Annotated, cast

from fastapi import Depends, Request

from edge_hardware_service.services.camera import CameraService
from edge_hardware_service.services.gpio import GpioService


def get_gpio_service(request: Request) -> GpioService:
    return cast(GpioService, request.app.state.gpio_service)


GpioServiceDep = Annotated[
    GpioService,
    Depends(get_gpio_service),
]


def get_camera_service(request: Request) -> CameraService:
    """Return the process-scoped camera service."""
    return cast(CameraService, request.app.state.camera_service)


CameraServiceDep = Annotated[
    CameraService,
    Depends(get_camera_service),
]
