"""Validate explicit pin selections for destructive Raspberry Pi tests."""

from collections.abc import Mapping
from dataclasses import dataclass

PIN_ENVIRONMENT_VARIABLES = {
    "input": "EDGE_HARDWARE_RPI_INPUT_PIN",
    "digital output": "EDGE_HARDWARE_RPI_OUTPUT_PIN",
    "PWM output": "EDGE_HARDWARE_RPI_PWM_PIN",
}

# GPIO 0 and 1 are reserved for HAT identification on the 40-pin header. The
# remaining BCM GPIO pins physically exposed by supported Raspberry Pi boards
# are eligible, but the operator must still avoid pins used by active overlays
# or peripherals.
SUPPORTED_BCM_PINS = frozenset(range(2, 28))


@dataclass(frozen=True, slots=True)
class HardwarePins:
    """Validated, unconnected BCM pins assigned to native library tests.

    Attributes:
        input: Unconnected input used to verify internal pull resistors.
        output: Unconnected digital output used for state changes.
        pwm: Unconnected PWM output used for configuration changes.
    """

    input: int
    output: int
    pwm: int


def load_hardware_pins(environment: Mapping[str, str]) -> HardwarePins:
    """Load and validate every physical-test pin before hardware is opened.

    Args:
        environment: Environment-variable mapping containing all three pin
            selections.

    Returns:
        Validated, distinct BCM pin assignments.

    Raises:
        ValueError: If a value is missing, malformed, unsupported, or reused.
    """
    pins: dict[str, int] = {}

    for role, variable in PIN_ENVIRONMENT_VARIABLES.items():
        raw_value = environment.get(variable, "").strip()
        if not raw_value:
            raise ValueError(
                f"{variable} is required; run `make pi-hardware-test` and "
                f"select a safe BCM {role} pin"
            )
        if not raw_value.isascii() or not raw_value.isdecimal():
            raise ValueError(
                f"{variable} must be a non-negative BCM pin number, got {raw_value!r}"
            )

        pin = int(raw_value)
        if pin not in SUPPORTED_BCM_PINS:
            raise ValueError(
                f"{variable} selects unsupported BCM pin {pin}; choose a "
                "GPIO pin from 2 through 27 on the 40-pin header"
            )
        pins[role] = pin

    if len(set(pins.values())) != len(pins):
        assignments = ", ".join(f"{role}={pin}" for role, pin in pins.items())
        raise ValueError(
            "Input, digital-output, and PWM pins must be distinct; "
            f"received {assignments}"
        )

    return HardwarePins(
        input=pins["input"],
        output=pins["digital output"],
        pwm=pins["PWM output"],
    )
