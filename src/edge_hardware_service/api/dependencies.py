from typing import Annotated, cast

from fastapi import Depends, Request

from edge_hardware_service.services.gpio import GpioService


def get_gpio_service(request: Request) -> GpioService:
    return cast(GpioService, request.app.state.gpio_service)


GpioServiceDep = Annotated[
    GpioService,
    Depends(get_gpio_service),
]
