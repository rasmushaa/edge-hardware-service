"""Unit tests for destructive Raspberry Pi test configuration."""

import pytest

from tests.rpi.hardware_config import HardwarePins, load_hardware_pins
from tests.rpi.test_gpiozero_hardware import _run_cleanup

VALID_ENVIRONMENT = {
    "EDGE_HARDWARE_RPI_INPUT_PIN": "17",
    "EDGE_HARDWARE_RPI_OUTPUT_PIN": "22",
    "EDGE_HARDWARE_RPI_PWM_PIN": "18",
}


def test_load_hardware_pins_returns_distinct_supported_pins() -> None:
    """A complete safe assignment should produce a typed configuration."""
    assert load_hardware_pins(VALID_ENVIRONMENT) == HardwarePins(
        input=17,
        output=22,
        pwm=18,
    )


@pytest.mark.parametrize(
    ("environment", "expected_message"),
    [
        (
            {
                key: value
                for key, value in VALID_ENVIRONMENT.items()
                if key != "EDGE_HARDWARE_RPI_INPUT_PIN"
            },
            "EDGE_HARDWARE_RPI_INPUT_PIN is required",
        ),
        (
            {
                **VALID_ENVIRONMENT,
                "EDGE_HARDWARE_RPI_OUTPUT_PIN": "GPIO22",
            },
            "must be a non-negative BCM pin number",
        ),
        (
            {**VALID_ENVIRONMENT, "EDGE_HARDWARE_RPI_PWM_PIN": "28"},
            "selects unsupported BCM pin 28",
        ),
        (
            {
                **VALID_ENVIRONMENT,
                "EDGE_HARDWARE_RPI_OUTPUT_PIN": "17",
            },
            "pins must be distinct",
        ),
    ],
)
def test_load_hardware_pins_rejects_unsafe_configuration(
    environment: dict[str, str],
    expected_message: str,
) -> None:
    """Every invalid configuration should fail before provider creation."""
    with pytest.raises(ValueError, match=expected_message):
        load_hardware_pins(environment)


def test_hardware_cleanup_attempts_every_operation_after_a_failure() -> None:
    """One reset failure must not prevent later devices from closing."""
    calls: list[str] = []

    def failing_reset() -> None:
        """Record the reset attempt and simulate a hardware failure."""
        calls.append("reset")
        raise RuntimeError("reset failed")

    def close_input() -> None:
        """Record input cleanup after the failed reset."""
        calls.append("close input")

    def close_output() -> None:
        """Record output cleanup after the failed reset."""
        calls.append("close output")

    with pytest.raises(ExceptionGroup) as raised:
        _run_cleanup(failing_reset, close_input, close_output)

    assert calls == ["reset", "close input", "close output"]
    assert len(raised.value.exceptions) == 1
    assert isinstance(raised.value.exceptions[0], RuntimeError)
