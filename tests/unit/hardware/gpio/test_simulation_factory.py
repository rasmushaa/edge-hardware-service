"""Unit tests for the portable GPIO simulation runtime."""

import pytest

from edge_hardware_service.hardware.gpio.exceptions import (
    PinAlreadyOpen,
    PinDeviceClosed,
)
from edge_hardware_service.hardware.gpio.simulation_factory import (
    SimulationDevice,
    SimulationDeviceFactory,
    SimulationDigitalOutputDevice,
    SimulationInputDevice,
    SimulationPwmOutputDevice,
)
from edge_hardware_service.models.gpio import PullMode


@pytest.mark.parametrize(
    ("pull", "expected"),
    [
        (PullMode.NONE, False),
        (PullMode.UP, True),
        (PullMode.DOWN, False),
    ],
)
def test_input_value_is_determined_by_pull_configuration(
    pull: PullMode,
    expected: bool,
) -> None:
    """Simulation inputs should expose deterministic electrical levels."""
    device = SimulationDeviceFactory().create_input(17, pull)

    assert device.value is expected


def test_output_devices_retain_written_state() -> None:
    """Digital and PWM devices should retain values for their lifetime."""
    factory = SimulationDeviceFactory()
    digital = factory.create_digital_output(17)
    pwm = factory.create_pwm_output(18, 500.0)

    digital.value = True
    pwm.value = 0.25
    pwm.frequency = 1000.0

    assert digital.value is True
    assert pwm.value == 0.25
    assert pwm.frequency == 1000.0


def test_factory_reserves_open_pins_and_reuses_closed_pins() -> None:
    """A pin should have one owner until its device closes."""
    factory = SimulationDeviceFactory()
    first = factory.create_input(17, PullMode.NONE)

    with pytest.raises(PinAlreadyOpen):
        factory.create_digital_output(17)

    first.close()
    replacement = factory.create_digital_output(17)
    assert replacement.closed is False


@pytest.mark.parametrize(
    "device",
    [
        SimulationInputDevice(17),
        SimulationDigitalOutputDevice(18),
        SimulationPwmOutputDevice(19),
    ],
)
def test_closed_devices_reject_reads(device: SimulationDevice) -> None:
    """Every simulated device should reject access after closure."""
    device.close()

    with pytest.raises(PinDeviceClosed):
        _ = device.value


def test_closed_output_devices_reject_writes() -> None:
    """Closed simulated outputs should reject every state mutation."""
    digital = SimulationDigitalOutputDevice(17)
    pwm = SimulationPwmOutputDevice(18)
    digital.close()
    pwm.close()

    with pytest.raises(PinDeviceClosed):
        digital.value = True
    with pytest.raises(PinDeviceClosed):
        pwm.value = 0.5
    with pytest.raises(PinDeviceClosed):
        pwm.frequency = 500.0


@pytest.mark.parametrize("duty_cycle", [-0.01, 1.01])
def test_pwm_rejects_invalid_duty_cycles(duty_cycle: float) -> None:
    """PWM devices should enforce the public duty-cycle range."""
    device = SimulationPwmOutputDevice(18)

    with pytest.raises(ValueError, match="between 0 and 1"):
        device.value = duty_cycle


@pytest.mark.parametrize("frequency", [0.0, -1.0])
def test_pwm_rejects_non_positive_frequency(frequency: float) -> None:
    """PWM construction and updates should require positive frequencies."""
    with pytest.raises(ValueError, match="greater than 0"):
        SimulationPwmOutputDevice(18, frequency)

    device = SimulationPwmOutputDevice(18)
    with pytest.raises(ValueError, match="greater than 0"):
        device.frequency = frequency
