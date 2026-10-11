"""Unit tests for GPIO service lifecycle and mode policy."""

import pytest

from edge_hardware_service.errors import ConflictError, NotFoundError
from edge_hardware_service.models.gpio import (
    PinConfigurationRequest,
    PinMode,
    PullMode,
)
from edge_hardware_service.services.gpio import (
    DigitalOutputPinSnapshot,
    GpioService,
    InputPinSnapshot,
    PwmOutputPinSnapshot,
)


class FakeDevice:
    """Small observable device implementing every GPIO device protocol."""

    def __init__(
        self,
        value: bool | float,
        *,
        frequency: float = 100.0,
        close_error: Exception | None = None,
    ) -> None:
        """Initialize fake state used by service tests."""
        self.value = value
        self.frequency = frequency
        self.closed = False
        self.close_error = close_error

    def close(self) -> None:
        """Record closure or raise the configured failure."""
        if self.close_error is not None:
            raise self.close_error
        self.closed = True


class FakeFactory:
    """Create observable fake devices and record construction arguments."""

    def __init__(self) -> None:
        """Initialize an empty creation log."""
        self.created: list[tuple[str, int, object, FakeDevice]] = []
        self.next_close_error: Exception | None = None
        self.creation_error: Exception | None = None
        self.close_error: Exception | None = None
        self.close_calls = 0
        self.open_devices_at_close: tuple[FakeDevice, ...] = ()

    def _device(
        self,
        mode: str,
        pin: int,
        option: object,
        value: bool | float,
        frequency: float = 100.0,
    ) -> FakeDevice:
        """Create and record a device or raise a configured failure."""
        if self.creation_error is not None:
            raise self.creation_error
        device = FakeDevice(
            value,
            frequency=frequency,
            close_error=self.next_close_error,
        )
        self.next_close_error = None
        self.created.append((mode, pin, option, device))
        return device

    def create_input(self, pin: int, pull: PullMode) -> FakeDevice:
        """Create an input fake whose value follows pull-up configuration."""
        return self._device("input", pin, pull, pull == PullMode.UP)

    def create_digital_output(self, pin: int) -> FakeDevice:
        """Create a low digital output fake."""
        return self._device("output", pin, None, False)

    def create_pwm_output(
        self,
        pin: int,
        frequency_hz: float | None = None,
    ) -> FakeDevice:
        """Create a stopped PWM fake at the selected frequency."""
        frequency = 100.0 if frequency_hz is None else frequency_hz
        return self._device("pwm", pin, frequency_hz, 0.0, frequency)

    def close(self) -> None:
        """Record provider closure and the device state at that moment."""
        self.close_calls += 1
        self.open_devices_at_close = tuple(
            item[3] for item in self.created if not item[3].closed
        )
        if self.close_error is not None:
            raise self.close_error


@pytest.fixture
def factory() -> FakeFactory:
    """Return a fresh observable device factory."""
    return FakeFactory()


@pytest.fixture
def service(factory: FakeFactory) -> GpioService:
    """Return a service backed by the observable factory."""
    return GpioService(factory)


def test_first_operation_opens_each_mode_and_returns_sorted_statuses(
    service: GpioService,
    factory: FakeFactory,
) -> None:
    """Lazy operations should create the right device exactly once."""
    assert service.read(23) is False
    digital = service.write(17, True)
    pwm = service.write_pwm(18, 0.25, frequency_hz=500.0)
    updated_pwm = service.write_pwm(18, 0.75)

    assert [item[:3] for item in factory.created] == [
        ("input", 23, PullMode.NONE),
        ("output", 17, None),
        ("pwm", 18, 500.0),
    ]
    assert digital == DigitalOutputPinSnapshot(17, True, "implicit")
    assert pwm == PwmOutputPinSnapshot(18, 0.25, 500.0, "implicit")
    assert updated_pwm == PwmOutputPinSnapshot(18, 0.75, 500.0, "implicit")
    assert [snapshot.pin for snapshot in service.list_pin_statuses()] == [
        17,
        18,
        23,
    ]


def test_operation_rejects_a_pin_open_in_another_mode(
    service: GpioService,
) -> None:
    """Mode conflicts should report active and requested modes."""
    service.write(17, True)

    with pytest.raises(ConflictError) as raised:
        service.read(17)

    assert raised.value.details == {
        "component": "gpio",
        "pin": 17,
        "active_mode": "output",
        "requested_mode": "input",
    }


def test_explicit_configuration_closes_and_replaces_existing_device(
    service: GpioService,
    factory: FakeFactory,
) -> None:
    """Reconfiguration should close the old device and expose new settings."""
    service.write(17, True)
    old_device = factory.created[-1][3]

    status = service.configure(
        17,
        PinConfigurationRequest(mode=PinMode.INPUT, pull=PullMode.UP),
    )

    assert old_device.closed is True
    assert status == InputPinSnapshot(17, True, PullMode.UP, "explicit")
    assert factory.created[-1][:3] == ("input", 17, PullMode.UP)


def test_failed_replacement_leaves_pin_released(
    service: GpioService,
    factory: FakeFactory,
) -> None:
    """A failed replacement must not leave a closed handle registered."""
    service.write(17, True)
    old_device = factory.created[-1][3]
    factory.creation_error = RuntimeError("creation failed")

    with pytest.raises(RuntimeError, match="creation failed"):
        service.configure(
            17,
            PinConfigurationRequest(mode=PinMode.INPUT),
        )

    assert old_device.closed is True
    with pytest.raises(NotFoundError):
        service.get_pin_status(17)


def test_release_is_idempotent_and_closes_the_device(
    service: GpioService,
    factory: FakeFactory,
) -> None:
    """Release should close an open pin and safely report an absent pin."""
    service.write(17, False)
    device = factory.created[-1][3]

    assert service.release(17) is True
    assert device.closed is True
    assert service.release(17) is False


def test_close_attempts_every_device_and_retains_failed_handles(
    factory: FakeFactory,
) -> None:
    """Shutdown should continue closing pins after one close failure."""
    service = GpioService(factory)
    factory.next_close_error = RuntimeError("close failed")
    service.write(17, False)
    failed_device = factory.created[-1][3]
    service.write_pwm(18, 0.5)
    closed_device = factory.created[-1][3]

    with pytest.raises(ExceptionGroup) as raised:
        service.close()

    assert "close failed" in str(raised.value.exceptions[0])
    assert failed_device.closed is False
    assert closed_device.closed is True
    assert factory.close_calls == 1
    assert factory.open_devices_at_close == (failed_device,)
    remaining = service.get_pin_status(17)
    assert isinstance(remaining, DigitalOutputPinSnapshot)
    with pytest.raises(NotFoundError):
        service.get_pin_status(18)


def test_close_releases_devices_before_factory_and_is_idempotent(
    service: GpioService,
    factory: FakeFactory,
) -> None:
    """Shutdown should close every device before closing its factory once."""
    service.write(17, True)
    service.write_pwm(18, 0.5)

    service.close()
    service.close()

    assert factory.open_devices_at_close == ()
    assert factory.close_calls == 1


def test_close_reports_device_and_factory_failures_together(
    factory: FakeFactory,
) -> None:
    """Shutdown should retain every independent cleanup failure."""
    service = GpioService(factory)
    factory.next_close_error = RuntimeError("device close failed")
    factory.close_error = RuntimeError("factory close failed")
    service.write(17, False)

    with pytest.raises(ExceptionGroup) as raised:
        service.close()

    assert [str(error) for error in raised.value.exceptions] == [
        "device close failed",
        "factory close failed",
    ]
