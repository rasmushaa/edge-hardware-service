from enum import Enum

from pydantic import BaseModel, Field


class PinMode(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    PWM = "pwm"


class PullMode(str, Enum):
    NONE = "none"
    UP = "up"
    DOWN = "down"


class PinConfig(BaseModel):
    mode: PinMode
    pull: PullMode = PullMode.NONE


class DigitalWrite(BaseModel):
    value: bool

class DigitalRead(BaseModel):
    value: bool


class PwmWrite(BaseModel):
    duty_cycle: float = Field(ge=0.0, le=1.0)
    frequency_hz: float | None = None


class PinState(BaseModel):
    pin: int
    mode: PinMode
    value: bool | None = None
    duty_cycle: float | None = None