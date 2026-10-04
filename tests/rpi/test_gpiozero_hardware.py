"""Opt-in smoke tests for GPIO devices on real Raspberry Pi hardware.

Run these tests only inside the prepared Bookworm container on a Raspberry Pi:

    EDGE_HARDWARE_RPI_INPUT_PIN=17 \
    EDGE_HARDWARE_RPI_OUTPUT_PIN=22 \
    EDGE_HARDWARE_RPI_PWM_PIN=18 \
    uv run pytest -m rpi

The selected output pins are actively driven during the tests. They must be
safe to toggle and must not be connected to hardware that could be damaged or
actuated unexpectedly.
"""

import os

import pytest

from edge_hardware_service.hardware.gpio.protocols import GpioDeviceFactory
from edge_hardware_service.models.gpio import PullMode


pytestmark = pytest.mark.rpi


def _configured_pin(variable: str) -> int:
    """Return an explicitly configured BCM pin or skip the hardware test.

    Args:
        variable: Environment variable containing a BCM pin number.

    Returns:
        Configured BCM pin number.
    """
    value = os.getenv(variable)
    if value is None:
        pytest.skip(f"{variable} must select a safe BCM pin")
    return int(value)


def _factory() -> GpioDeviceFactory:
    """Import and create the OS-provided gpiozero factory when selected."""
    pytest.importorskip("gpiozero")
    from edge_hardware_service.hardware.gpio.gpiozero_factory import (
        GpioZeroDeviceFactory,
    )

    return GpioZeroDeviceFactory()


def test_rpi_input_can_be_opened_and_read() -> None:
    """Open, read, and close a physical digital input."""
    pin = _configured_pin("EDGE_HARDWARE_RPI_INPUT_PIN")
    factory = _factory()
    device = factory.create_input(pin, PullMode.NONE)
    try:
        assert isinstance(device.value, bool)
    finally:
        device.close()


def test_rpi_digital_output_can_be_written() -> None:
    """Open, toggle, reset, and close a physical digital output."""
    pin = _configured_pin("EDGE_HARDWARE_RPI_OUTPUT_PIN")
    factory = _factory()
    device = factory.create_digital_output(pin)
    try:
        device.value = False
        assert device.value is False
        device.value = True
        assert device.value is True
        device.value = False
    finally:
        device.close()


def test_rpi_pwm_output_can_be_written() -> None:
    """Open, drive, stop, and close a physical PWM output."""
    pin = _configured_pin("EDGE_HARDWARE_RPI_PWM_PIN")
    factory = _factory()
    device = factory.create_pwm_output(pin, 500.0)
    try:
        device.value = 0.25
        assert device.value == pytest.approx(0.25)
        assert device.frequency == pytest.approx(500.0)
        device.value = 0.0
    finally:
        device.close()
