"""Functional GPIO library tests for unconnected Raspberry Pi pins.

Run these tests natively on prepared Raspberry Pi OS through
`make hw-test`. The suite requires three distinct, unconnected BCM
pins and no external components or wiring. It verifies:

* Input reads using the Raspberry Pi's internal pull-up and pull-down.
* GPIO Zero digital-output state changes.
* GPIO Zero PWM duty-cycle and frequency configuration.

The suite does not measure electrical output levels or PWM waveforms. All pin
selections are validated before GPIO Zero initializes, and teardown resets
outputs before closing devices and the shared provider.
"""

import os
from collections.abc import Callable, Iterator
from typing import TypeAlias

import pytest

from edge_hardware_service.hardware.gpio.protocols import (
    DigitalOutputPinDevice,
    GpioDeviceFactory,
    PwmOutputPinDevice,
)
from edge_hardware_service.models.gpio import PullMode
from tests.rpi.hardware_config import HardwarePins, load_hardware_pins

pytestmark = pytest.mark.rpi

DeviceCleanup: TypeAlias = Callable[[], None]
PWM_TEST_FREQUENCY_HZ = 500.0


def _run_cleanup(*operations: DeviceCleanup) -> None:
    """Attempt every cleanup operation and report all failures together.

    Args:
        operations: Ordered reset and close operations.

    Raises:
        ExceptionGroup: If one or more cleanup operations fail.
    """
    failures: list[Exception] = []
    for operation in operations:
        try:
            operation()
        except Exception as error:
            failures.append(error)

    if failures:
        raise ExceptionGroup("Raspberry Pi GPIO cleanup failed", failures)


@pytest.fixture(scope="session")
def hardware_pins() -> HardwarePins:
    """Validate all requested pins before initializing a GPIO provider."""
    try:
        return load_hardware_pins(os.environ)
    except ValueError as error:
        pytest.fail(str(error), pytrace=False)


@pytest.fixture(scope="session")
def gpio_factory(
    hardware_pins: HardwarePins,
    request: pytest.FixtureRequest,
) -> Iterator[GpioDeviceFactory]:
    """Own one physical GPIO Zero provider for the complete test session."""
    del hardware_pins
    pytest.importorskip("gpiozero")
    from edge_hardware_service.hardware.gpio.gpiozero_factory import (
        GpioZeroDeviceFactory,
    )

    factory = GpioZeroDeviceFactory()
    terminal_reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is not None:
        controller = (
            factory.controller if factory.controller is not None else "provider-managed"
        )
        gpiochips = ", ".join(factory.available_gpiochips) or "none"
        terminal_reporter.write_line(
            "Raspberry Pi GPIO provider: "
            f"{factory.provider_name} "
            f"(controller={controller}, gpiochips={gpiochips})"
        )

    try:
        yield factory
    finally:
        factory.close()


@pytest.fixture
def digital_output_device(
    gpio_factory: GpioDeviceFactory,
    hardware_pins: HardwarePins,
) -> Iterator[DigitalOutputPinDevice]:
    """Open a digital output and guarantee LOW cleanup."""
    device = gpio_factory.create_digital_output(hardware_pins.output)
    try:
        yield device
    finally:
        _run_cleanup(
            lambda: setattr(device, "value", False),
            device.close,
        )


@pytest.fixture
def pwm_output_device(
    gpio_factory: GpioDeviceFactory,
    hardware_pins: HardwarePins,
) -> Iterator[PwmOutputPinDevice]:
    """Open a PWM output and guarantee a zero-duty-cycle cleanup."""
    device = gpio_factory.create_pwm_output(
        hardware_pins.pwm,
        PWM_TEST_FREQUENCY_HZ,
    )
    try:
        yield device
    finally:
        _run_cleanup(
            lambda: setattr(device, "value", 0.0),
            device.close,
        )


@pytest.mark.parametrize(
    ("pull", "expected"),
    [
        (PullMode.UP, True),
        (PullMode.DOWN, False),
    ],
)
def test_rpi_input_internal_pull_sets_expected_level(
    gpio_factory: GpioDeviceFactory,
    hardware_pins: HardwarePins,
    pull: PullMode,
    expected: bool,
) -> None:
    """Read the expected level from an unconnected internally pulled pin."""
    device = gpio_factory.create_input(hardware_pins.input, pull)
    try:
        observed = device.value
        expected_name = "HIGH" if expected else "LOW"
        observed_name = "HIGH" if observed else "LOW"
        assert observed is expected, (
            f"BCM input {hardware_pins.input} with pull-{pull.value} "
            f"expected {expected_name}, observed {observed_name}. Ensure the "
            "pin is unconnected and not assigned to an active peripheral."
        )
    finally:
        device.close()


def test_rpi_digital_output_can_be_toggled(
    digital_output_device: DigitalOutputPinDevice,
) -> None:
    """Drive, inspect, and reset a physical digital output."""
    digital_output_device.value = False
    assert digital_output_device.value is False

    digital_output_device.value = True
    assert digital_output_device.value is True

    digital_output_device.value = False
    assert digital_output_device.value is False


def test_rpi_pwm_output_supports_duty_cycle_and_frequency(
    pwm_output_device: PwmOutputPinDevice,
) -> None:
    """Exercise two duty cycles at an explicit physical PWM frequency."""
    assert pwm_output_device.frequency == pytest.approx(PWM_TEST_FREQUENCY_HZ)

    pwm_output_device.value = 0.25
    assert pwm_output_device.value == pytest.approx(0.25)

    pwm_output_device.value = 0.75
    assert pwm_output_device.value == pytest.approx(0.75)

    pwm_output_device.value = 0.0
    assert pwm_output_device.value == pytest.approx(0.0)
