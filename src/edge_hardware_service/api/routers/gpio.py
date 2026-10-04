from fastapi import APIRouter, Response, status

from edge_hardware_service.api.dependencies import GpioDeviceServiceDep
from edge_hardware_service.models.gpio import (
    DigitalRead,
    DigitalWrite,
    PwmWrite,
)


router = APIRouter(prefix="/gpio", tags=["GPIO"])


@router.get("/{pin}/value", response_model=DigitalRead)
def read_gpio(
    pin: int,
    service: GpioDeviceServiceDep,
) -> DigitalRead:
    return DigitalRead(value=service.read(pin))


@router.put(
    "/{pin}/value",
    status_code=status.HTTP_204_NO_CONTENT,
)
def write_gpio(
    pin: int,
    command: DigitalWrite,
    service: GpioDeviceServiceDep,
) -> Response:
    service.write(pin, command.value)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/{pin}/pwm",
    status_code=status.HTTP_204_NO_CONTENT,
)
def write_pwm(
    pin: int,
    command: PwmWrite,
    service: GpioDeviceServiceDep,
) -> Response:
    service.write_pwm(pin, command.duty_cycle)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{pin}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def release_gpio(
    pin: int,
    service: GpioDeviceServiceDep,
) -> Response:
    service.release(pin)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
