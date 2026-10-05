"""Pydantic request and response schemas for the public GPIO API."""

from enum import Enum
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PinMode(str, Enum):
    """Supported operating modes for a GPIO pin."""

    INPUT = "input"
    OUTPUT = "output"
    PWM = "pwm"


class PullMode(str, Enum):
    """Supported internal resistor configurations for an input pin."""

    NONE = "none"
    UP = "up"
    DOWN = "down"


ConfigurationSource: TypeAlias = Literal["implicit", "explicit"]
HardwareBackendName: TypeAlias = Literal["simulation", "rpi"]


class _RequestModel(BaseModel):
    """Forbid undocumented fields in GPIO request payloads."""

    model_config = ConfigDict(extra="forbid")


class _ResponseModel(BaseModel):
    """Provide immutable GPIO response values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PinConfigurationRequest(_RequestModel):
    """Request explicit configuration of a BCM GPIO pin."""

    mode: PinMode = Field(
        description="Operating mode assigned to the pin.",
        examples=[PinMode.INPUT, PinMode.OUTPUT, PinMode.PWM],
    )
    pull: PullMode = Field(
        default=PullMode.NONE,
        description=(
            "Internal resistor configuration. This may differ from `none` only "
            "when mode is `input`. A no-pull input needs an external pull or "
            "driven signal for a stable value."
        ),
        examples=[PullMode.NONE, PullMode.UP, PullMode.DOWN],
    )
    frequency_hz: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "PWM frequency in hertz. This is accepted only when mode is `pwm`; "
            "omitting it uses the provider default."
        ),
        examples=[None, 100.0, 500.0, 1000.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"mode": "input", "pull": "none"},
                {"mode": "input", "pull": "up"},
                {"mode": "input", "pull": "down"},
                {"mode": "output", "pull": "none"},
                {"mode": "pwm", "pull": "none"},
                {
                    "mode": "pwm",
                    "pull": "none",
                    "frequency_hz": 500.0,
                },
            ]
        }
    )

    @model_validator(mode="after")
    def validate_mode_options(self) -> Self:
        """Reject configuration fields that do not apply to the selected mode.

        Returns:
            The validated request.

        Raises:
            ValueError: If pull or frequency is incompatible with the mode.
        """
        if self.mode != PinMode.INPUT and self.pull != PullMode.NONE:
            raise ValueError("pull may only be configured for input mode")
        if self.mode != PinMode.PWM and self.frequency_hz is not None:
            raise ValueError("frequency_hz may only be configured for PWM mode")
        return self


class DigitalWriteRequest(_RequestModel):
    """Request a logical value for a digital output pin."""

    value: bool = Field(
        strict=True,
        description="Logical output value: `true` for high or `false` for low.",
        examples=[True, False],
    )

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"value": True}, {"value": False}]}
    )


class PwmWriteRequest(_RequestModel):
    """Request a duty cycle and optional frequency for a PWM output pin."""

    duty_cycle: float = Field(
        ge=0.0,
        le=1.0,
        description="Duty cycle from `0.0` (off) to `1.0` (fully on).",
        examples=[0.0, 0.25, 0.5, 1.0],
    )
    frequency_hz: float | None = Field(
        default=None,
        gt=0.0,
        description=(
            "Optional PWM frequency in hertz. An omitted value preserves the "
            "active frequency or uses the provider default for a new pin."
        ),
        examples=[None, 100.0, 500.0, 1000.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"duty_cycle": 0.0},
                {"duty_cycle": 0.5},
                {"duty_cycle": 0.25, "frequency_hz": 500.0},
                {"duty_cycle": 1.0, "frequency_hz": 1000.0},
            ]
        }
    )


class DigitalReadResponse(_ResponseModel):
    """Current electrical level returned for an input pin."""

    pin: int = Field(
        ge=0,
        description="BCM GPIO pin number.",
        examples=[17, 18, 22],
    )
    value: bool = Field(
        description=(
            "Current electrical level: `true` for HIGH or `false` for LOW. "
            "Pull configuration does not invert this value."
        ),
        examples=[True, False],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"pin": 17, "value": True},
                {"pin": 17, "value": False},
            ]
        }
    )


class InputPinStatus(_ResponseModel):
    """Effective state and configuration of an open input pin."""

    pin: int = Field(
        ge=0,
        description="BCM GPIO pin number.",
        examples=[17, 18, 22],
    )
    mode: Literal[PinMode.INPUT] = Field(
        default=PinMode.INPUT,
        description="Active GPIO mode.",
    )
    value: bool = Field(
        description=(
            "Current electrical input level: `true` for HIGH or `false` for "
            "LOW. Pull configuration does not invert this value."
        ),
        examples=[True, False],
    )
    pull: PullMode = Field(
        description="Active internal resistor configuration.",
        examples=[PullMode.NONE, PullMode.UP, PullMode.DOWN],
    )
    configuration_source: ConfigurationSource = Field(
        description=(
            "Whether the pin was opened by its first operation or by explicit "
            "configuration."
        ),
        examples=["implicit", "explicit"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pin": 17,
                    "mode": "input",
                    "value": False,
                    "pull": "none",
                    "configuration_source": "implicit",
                },
                {
                    "pin": 17,
                    "mode": "input",
                    "value": True,
                    "pull": "up",
                    "configuration_source": "explicit",
                },
                {
                    "pin": 17,
                    "mode": "input",
                    "value": False,
                    "pull": "down",
                    "configuration_source": "explicit",
                },
            ]
        }
    )


class DigitalOutputStatus(_ResponseModel):
    """Effective state and configuration of an open digital output pin."""

    pin: int = Field(
        ge=0,
        description="BCM GPIO pin number.",
        examples=[17, 18, 22],
    )
    mode: Literal[PinMode.OUTPUT] = Field(
        default=PinMode.OUTPUT,
        description="Active GPIO mode.",
    )
    value: bool = Field(
        description="Current logical output value.",
        examples=[True, False],
    )
    configuration_source: ConfigurationSource = Field(
        description=(
            "Whether the pin was opened by its first operation or by explicit "
            "configuration."
        ),
        examples=["implicit", "explicit"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pin": 22,
                    "mode": "output",
                    "value": True,
                    "configuration_source": "implicit",
                },
                {
                    "pin": 22,
                    "mode": "output",
                    "value": False,
                    "configuration_source": "explicit",
                },
            ]
        }
    )


class PwmOutputStatus(_ResponseModel):
    """Effective state and configuration of an open PWM output pin."""

    pin: int = Field(
        ge=0,
        description="BCM GPIO pin number.",
        examples=[17, 18, 22],
    )
    mode: Literal[PinMode.PWM] = Field(
        default=PinMode.PWM,
        description="Active GPIO mode.",
    )
    duty_cycle: float = Field(
        ge=0.0,
        le=1.0,
        description="Current duty cycle from `0.0` to `1.0`.",
        examples=[0.0, 0.5, 1.0],
    )
    frequency_hz: float = Field(
        gt=0.0,
        description="Effective PWM frequency in hertz.",
        examples=[100.0, 500.0, 1000.0],
    )
    configuration_source: ConfigurationSource = Field(
        description=(
            "Whether the pin was opened by its first operation or by explicit "
            "configuration."
        ),
        examples=["implicit", "explicit"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "pin": 18,
                    "mode": "pwm",
                    "duty_cycle": 0.0,
                    "frequency_hz": 100.0,
                    "configuration_source": "implicit",
                },
                {
                    "pin": 18,
                    "mode": "pwm",
                    "duty_cycle": 0.5,
                    "frequency_hz": 500.0,
                    "configuration_source": "explicit",
                },
                {
                    "pin": 18,
                    "mode": "pwm",
                    "duty_cycle": 1.0,
                    "frequency_hz": 1000.0,
                    "configuration_source": "explicit",
                },
            ]
        }
    )


PinStatus: TypeAlias = Annotated[
    InputPinStatus | DigitalOutputStatus | PwmOutputStatus,
    Field(discriminator="mode"),
]


class PinRegistryResponse(_ResponseModel):
    """Current state of every GPIO pin open in this process."""

    backend: HardwareBackendName = Field(
        description="Runtime implementation serving the GPIO API.",
        examples=["simulation", "rpi"],
    )
    count: int = Field(
        ge=0,
        description="Number of open GPIO pins in the registry.",
    )
    pins: tuple[PinStatus, ...] = Field(
        default_factory=tuple,
        description="Open pin states ordered by BCM pin number.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"backend": "simulation", "count": 0, "pins": []},
                {
                    "backend": "simulation",
                    "count": 2,
                    "pins": [
                        {
                            "pin": 17,
                            "mode": "input",
                            "value": False,
                            "pull": "none",
                            "configuration_source": "implicit",
                        },
                        {
                            "pin": 18,
                            "mode": "pwm",
                            "duty_cycle": 0.5,
                            "frequency_hz": 100.0,
                            "configuration_source": "implicit",
                        },
                    ],
                },
                {
                    "backend": "rpi",
                    "count": 1,
                    "pins": [
                        {
                            "pin": 22,
                            "mode": "output",
                            "value": True,
                            "configuration_source": "explicit",
                        }
                    ],
                },
            ]
        }
    )

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        """Ensure the reported count matches the pin collection.

        Returns:
            The validated response.

        Raises:
            ValueError: If count does not match the number of pins.
        """
        if self.count != len(self.pins):
            raise ValueError("count must match the number of pins")
        return self


class PinReleaseResponse(_ResponseModel):
    """Result of requesting release of one GPIO pin."""

    pin: int = Field(
        ge=0,
        description="BCM GPIO pin number.",
        examples=[17, 18, 22],
    )
    released: bool = Field(
        description="Whether the pin was open and has been released.",
        examples=[True, False],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"pin": 17, "released": True},
                {"pin": 17, "released": False},
            ]
        }
    )
