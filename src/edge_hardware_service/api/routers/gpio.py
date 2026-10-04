"""HTTP endpoints for GPIO configuration, I/O, and registry inspection."""

from typing import Annotated, assert_never, cast

from fastapi import APIRouter, Body, Path, Request, status

from edge_hardware_service.api.dependencies import GpioServiceDep
from edge_hardware_service.api.errors import (
    HARDWARE_UNAVAILABLE_RESPONSE,
    PIN_CONFLICT_RESPONSE,
    PIN_NOT_OPEN_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
)
from edge_hardware_service.config import HardwareBackend
from edge_hardware_service.models.gpio import (
    DigitalOutputStatus,
    DigitalReadResponse,
    DigitalWriteRequest,
    InputPinStatus,
    PinConfigurationRequest,
    PinRegistryResponse,
    PinReleaseResponse,
    PinStatus,
    PwmOutputStatus,
    PwmWriteRequest,
)
from edge_hardware_service.services.gpio import (
    DigitalOutputPinSnapshot,
    InputPinSnapshot,
    PinSnapshot,
    PwmOutputPinSnapshot,
)


router = APIRouter(prefix="/gpio", tags=["GPIO"])

BcmPin = Annotated[
    int,
    Path(
        ge=0,
        description="Broadcom (BCM) GPIO pin number.",
        examples=[17, 18, 22],
    ),
]
PinConfigurationBody = Annotated[
    PinConfigurationRequest,
    Body(
        openapi_examples={
            "input_without_pull": {
                "summary": "Input without an internal resistor",
                "value": {"mode": "input", "pull": "none"},
            },
            "input_with_pull_up": {
                "summary": "Input with an internal pull-up resistor",
                "value": {"mode": "input", "pull": "up"},
            },
            "input_with_pull_down": {
                "summary": "Input with an internal pull-down resistor",
                "value": {"mode": "input", "pull": "down"},
            },
            "digital_output": {
                "summary": "Digital output",
                "value": {"mode": "output", "pull": "none"},
            },
            "pwm_with_provider_frequency": {
                "summary": "PWM output using the provider's default frequency",
                "value": {
                    "mode": "pwm",
                    "pull": "none",
                    "frequency_hz": None,
                },
            },
            "pwm_with_custom_frequency": {
                "summary": "PWM output with an explicit frequency",
                "value": {
                    "mode": "pwm",
                    "pull": "none",
                    "frequency_hz": 500.0,
                },
            },
        }
    ),
]
DigitalWriteBody = Annotated[
    DigitalWriteRequest,
    Body(
        openapi_examples={
            "high": {
                "summary": "Set the output high",
                "value": {"value": True},
            },
            "low": {
                "summary": "Set the output low",
                "value": {"value": False},
            },
        }
    ),
]
PwmWriteBody = Annotated[
    PwmWriteRequest,
    Body(
        openapi_examples={
            "off": {
                "summary": "Stop the PWM output",
                "value": {"duty_cycle": 0.0},
            },
            "partial_provider_frequency": {
                "summary": "Partial duty cycle at the active frequency",
                "value": {"duty_cycle": 0.5, "frequency_hz": None},
            },
            "partial_custom_frequency": {
                "summary": "Partial duty cycle with an explicit frequency",
                "value": {"duty_cycle": 0.25, "frequency_hz": 500.0},
            },
            "fully_on": {
                "summary": "Fully on with an explicit frequency",
                "value": {"duty_cycle": 1.0, "frequency_hz": 1000.0},
            },
        }
    ),
]

COMMON_OPERATION_ERRORS = {
    status.HTTP_409_CONFLICT: PIN_CONFLICT_RESPONSE,
    status.HTTP_422_UNPROCESSABLE_CONTENT: VALIDATION_ERROR_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
}
LOOKUP_ERRORS = {
    status.HTTP_404_NOT_FOUND: PIN_NOT_OPEN_RESPONSE,
    status.HTTP_422_UNPROCESSABLE_CONTENT: VALIDATION_ERROR_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
}


def _to_pin_status(snapshot: PinSnapshot) -> PinStatus:
    """Convert an internal service snapshot to its public response model.

    Args:
        snapshot: Immutable state returned by the GPIO service.

    Returns:
        Public status model matching the pin's active mode.
    """
    if isinstance(snapshot, InputPinSnapshot):
        return InputPinStatus(
            pin=snapshot.pin,
            value=snapshot.value,
            pull=snapshot.pull,
            configuration_source=snapshot.configuration_source,
        )
    if isinstance(snapshot, DigitalOutputPinSnapshot):
        return DigitalOutputStatus(
            pin=snapshot.pin,
            value=snapshot.value,
            configuration_source=snapshot.configuration_source,
        )
    if isinstance(snapshot, PwmOutputPinSnapshot):
        return PwmOutputStatus(
            pin=snapshot.pin,
            duty_cycle=snapshot.duty_cycle,
            frequency_hz=snapshot.frequency_hz,
            configuration_source=snapshot.configuration_source,
        )
    assert_never(snapshot)


@router.get(
    "",
    summary="Inspect the GPIO registry",
    operation_id="list_gpio_pins",
    description="""
Return every GPIO pin currently owned by this service process.

- Pins are ordered by BCM pin number.
- Each item reports its effective mode, state, and configuration source.
- The response identifies whether the service uses the `simulation` or `rpi`
  backend.
- A process restart clears the registry and releases all devices.
""",
    response_model=PinRegistryResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def list_gpio_pins(
    request: Request,
    service: GpioServiceDep,
) -> PinRegistryResponse:
    """Return the active backend and all currently open GPIO pins.

    Args:
        request: Current HTTP request containing application runtime state.
        service: Process-scoped GPIO service.

    Returns:
        Ordered snapshot of the GPIO registry.
    """
    pins = tuple(_to_pin_status(item) for item in service.list_pin_statuses())
    backend = cast(HardwareBackend, request.app.state.hardware_backend)
    return PinRegistryResponse(backend=backend, count=len(pins), pins=pins)


@router.get(
    "/{pin}",
    summary="Inspect one GPIO pin",
    operation_id="get_gpio_pin_status",
    description="""
Return the effective state and configuration of one open BCM GPIO pin.

- This operation does not open or reconfigure a pin.
- The response shape is selected by the active input, output, or PWM mode.
- A pin absent from the process registry returns `404 Not Found`.
""",
    response_model=PinStatus,
    responses=LOOKUP_ERRORS,
)
def get_gpio_pin_status(
    pin: BcmPin,
    service: GpioServiceDep,
) -> PinStatus:
    """Return the status of one open GPIO pin.

    Args:
        pin: BCM GPIO pin number.
        service: Process-scoped GPIO service.

    Returns:
        Status matching the pin's active mode.
    """
    return _to_pin_status(service.get_pin_status(pin))


@router.put(
    "/{pin}/configuration",
    summary="Configure a GPIO pin",
    operation_id="configure_gpio_pin",
    description="""
Explicitly configure or reconfigure a BCM GPIO pin.

- Any device currently using the pin is closed before its replacement opens.
- Input mode supports `none`, `up`, and `down` pull configurations.
- PWM mode accepts an optional positive frequency; omission uses the provider
  default.
- A successful response reports `explicit` as its configuration source.
""",
    response_model=PinStatus,
    responses=COMMON_OPERATION_ERRORS,
)
def configure_gpio_pin(
    pin: BcmPin,
    configuration: PinConfigurationBody,
    service: GpioServiceDep,
) -> PinStatus:
    """Explicitly configure a GPIO pin.

    Args:
        pin: BCM GPIO pin number.
        configuration: Requested mode and mode-specific options.
        service: Process-scoped GPIO service.

    Returns:
        Effective state after configuration.
    """
    return _to_pin_status(service.configure(pin, configuration))


@router.get(
    "/{pin}/value",
    summary="Read a digital input",
    operation_id="read_gpio_input",
    description="""
Read the current logical value of a BCM GPIO pin.

- An unopened pin is automatically configured as an input.
- Implicit input configuration uses pull mode `none`.
- Reading a pin already opened as an output or PWM returns `409 Conflict`.
- The returned value is `true` for high and `false` for low.
""",
    response_model=DigitalReadResponse,
    responses=COMMON_OPERATION_ERRORS,
)
def read_gpio(
    pin: BcmPin,
    service: GpioServiceDep,
) -> DigitalReadResponse:
    """Read a digital input, opening it implicitly when needed.

    Args:
        pin: BCM GPIO pin number.
        service: Process-scoped GPIO service.

    Returns:
        Current logical input value.
    """
    return DigitalReadResponse(pin=pin, value=service.read(pin))


@router.put(
    "/{pin}/value",
    summary="Write a digital output",
    operation_id="write_gpio_output",
    description="""
Set the logical value of a BCM GPIO output pin.

- An unopened pin is automatically configured as a digital output.
- Writing a pin already opened as an input or PWM returns `409 Conflict`.
- The response reports the stored effective value and configuration source.
- Use explicit configuration or release before changing the pin's mode.
""",
    response_model=DigitalOutputStatus,
    responses=COMMON_OPERATION_ERRORS,
)
def write_gpio(
    pin: BcmPin,
    command: DigitalWriteBody,
    service: GpioServiceDep,
) -> DigitalOutputStatus:
    """Write a digital output and return its resulting state.

    Args:
        pin: BCM GPIO pin number.
        command: Requested logical output value.
        service: Process-scoped GPIO service.

    Returns:
        Effective digital output state after the write.
    """
    result = _to_pin_status(service.write(pin, command.value))
    if not isinstance(result, DigitalOutputStatus):
        raise AssertionError("digital write produced a non-output status")
    return result


@router.put(
    "/{pin}/pwm",
    summary="Write a PWM output",
    operation_id="write_gpio_pwm",
    description="""
Set the PWM duty cycle and optionally its frequency on a BCM GPIO pin.

- An unopened pin is automatically configured as a PWM output.
- Duty cycle ranges from `0.0` (off) to `1.0` (fully on).
- Omitting `frequency_hz` preserves the active frequency or uses the provider
  default for a newly opened pin.
- Writing a pin open in another mode returns `409 Conflict`.
""",
    response_model=PwmOutputStatus,
    responses=COMMON_OPERATION_ERRORS,
)
def write_pwm(
    pin: BcmPin,
    command: PwmWriteBody,
    service: GpioServiceDep,
) -> PwmOutputStatus:
    """Write a PWM output and return its resulting state.

    Args:
        pin: BCM GPIO pin number.
        command: Requested duty cycle and optional frequency.
        service: Process-scoped GPIO service.

    Returns:
        Effective PWM state after the write.
    """
    result = _to_pin_status(
        service.write_pwm(
            pin,
            command.duty_cycle,
            frequency_hz=command.frequency_hz,
        )
    )
    if not isinstance(result, PwmOutputStatus):
        raise AssertionError("PWM write produced a non-PWM status")
    return result


@router.delete(
    "/{pin}",
    summary="Release a GPIO pin",
    operation_id="release_gpio_pin",
    description="""
Close and release one BCM GPIO pin owned by this service process.

- Releasing a pin makes it available for any supported mode.
- The response reports `released: true` when an open device was closed.
- Releasing a pin that is already absent is safe and reports `released: false`.
- The service also releases every registered pin during application shutdown.
""",
    response_model=PinReleaseResponse,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: VALIDATION_ERROR_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def release_gpio(
    pin: BcmPin,
    service: GpioServiceDep,
) -> PinReleaseResponse:
    """Release one GPIO pin if it is currently open.

    Args:
        pin: BCM GPIO pin number.
        service: Process-scoped GPIO service.

    Returns:
        Release result indicating whether a device was open.
    """
    return PinReleaseResponse(pin=pin, released=service.release(pin))
