from typing import Annotated, cast

from fastapi import Depends, Request

from edge_hardware_service.services.gpio import GpioDeviceService


def get_gpio_service(request: Request) -> GpioDeviceService:
    return cast(GpioDeviceService, request.app.state.gpio_service)


GpioDeviceServiceDep = Annotated[
    GpioDeviceService,
    Depends(get_gpio_service),
]