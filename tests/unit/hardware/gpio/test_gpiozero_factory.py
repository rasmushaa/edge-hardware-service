"""Unit tests for the OS-owned GPIO Zero adapter and provider lifecycle.

These tests require the OS-owned gpiozero package and therefore skip in the
portable uv environment. The Bookworm container runs them without physical
hardware by injecting GPIO Zero's test pin factory.
"""

from collections.abc import Iterator
from logging import INFO
from typing import cast

import pytest

pytest.importorskip("gpiozero")

from fastapi.testclient import TestClient  # noqa: E402
from gpiozero import Device  # noqa: E402
from gpiozero.pins import Factory  # noqa: E402
from gpiozero.pins.mock import MockFactory, MockPWMPin  # noqa: E402

from edge_hardware_service.config import Settings  # noqa: E402
from edge_hardware_service.hardware.gpio import (  # noqa: E402
    gpiozero_factory as gpiozero_backend,
)
from edge_hardware_service.hardware.gpio.exceptions import (  # noqa: E402
    GpioHardwareError,
    GpioProviderError,
    GpioProviderUnavailable,
)
from edge_hardware_service.main import create_app  # noqa: E402
from edge_hardware_service.models.gpio import PullMode  # noqa: E402

GpioZeroDeviceFactory = gpiozero_backend.GpioZeroDeviceFactory


@pytest.fixture
def mock_pin_factory() -> Iterator[MockFactory]:
    """Return an isolated GPIO Zero provider without installing it globally."""
    factory = MockFactory(pin_class=MockPWMPin)
    try:
        yield factory
    finally:
        factory.close()


@pytest.mark.parametrize(
    ("pull", "expected_provider_pull"),
    [
        (PullMode.NONE, "floating"),
        (PullMode.UP, "up"),
        (PullMode.DOWN, "down"),
    ],
)
def test_input_returns_electrical_level_without_pull_inversion(
    mock_pin_factory: MockFactory,
    pull: PullMode,
    expected_provider_pull: str,
) -> None:
    """Every pull mode should construct and expose HIGH as true."""
    factory = GpioZeroDeviceFactory(mock_pin_factory)
    device = factory.create_input(17, pull)
    pin = mock_pin_factory.pin(17)

    try:
        assert pin.pull == expected_provider_pull

        pin.drive_high()
        assert device.value is True

        pin.drive_low()
        assert device.value is False
    finally:
        device.close()
        factory.close()


def test_one_injected_provider_is_shared_by_every_device_type(
    mock_pin_factory: MockFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Input, digital output, and PWM should use one reported provider."""
    with caplog.at_level(INFO, logger=gpiozero_backend.__name__):
        factory = GpioZeroDeviceFactory(mock_pin_factory)

    input_device = factory.create_input(17, PullMode.DOWN)
    output_device = factory.create_digital_output(18)
    pwm_device = factory.create_pwm_output(19, 500.0)

    try:
        assert factory.provider_name == "gpiozero.pins.mock.MockFactory"
        assert "Initialized GPIO Zero provider" in caplog.text
        assert {pin.name for pin in mock_pin_factory.pins} == {
            "GPIO17",
            "GPIO18",
            "GPIO19",
        }
    finally:
        input_device.close()
        output_device.close()
        pwm_device.close()
        factory.close()


def test_default_selection_is_initialized_and_global_reference_is_cleared(
    mock_pin_factory: MockFactory,
) -> None:
    """Normal selection should be eager and reset GPIO Zero after closure."""
    previous = Device.pin_factory
    Device.pin_factory = mock_pin_factory
    try:
        factory = GpioZeroDeviceFactory()

        assert factory.provider_name == "gpiozero.pins.mock.MockFactory"
        factory.close()
        factory.close()

        assert Device.pin_factory is None
    finally:
        Device.pin_factory = previous


def test_provider_initialization_failure_uses_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed default provider must prevent Raspberry Pi startup."""
    previous = Device.pin_factory
    Device.pin_factory = None

    def fail_initialization(cls: type[Device]) -> None:
        """Raise the kind of provider error emitted by native libraries."""
        del cls
        raise RuntimeError("provider initialization failed")

    monkeypatch.setattr(
        Device,
        "ensure_pin_factory",
        classmethod(fail_initialization),
    )
    try:
        with pytest.raises(GpioProviderUnavailable) as raised:
            GpioZeroDeviceFactory()
    finally:
        Device.pin_factory = previous

    assert raised.value.provider == "gpiozero pin factory"
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_device_operation_failure_uses_pin_scoped_domain_error(
    mock_pin_factory: MockFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native construction errors should retain their pin and operation."""
    factory = GpioZeroDeviceFactory(mock_pin_factory)

    def fail_construction(*args: object, **kwargs: object) -> None:
        """Raise a representative native-provider runtime error."""
        del args, kwargs
        raise RuntimeError("device construction failed")

    monkeypatch.setattr(
        gpiozero_backend,
        "DigitalOutputDevice",
        fail_construction,
    )

    with pytest.raises(GpioHardwareError) as raised:
        factory.create_digital_output(17)

    assert raised.value.pin == 17
    assert raised.value.operation == "open digital output"
    assert isinstance(raised.value.__cause__, RuntimeError)
    factory.close()


def test_provider_close_failure_is_translated_and_not_retried() -> None:
    """Provider cleanup should produce one provider-scoped domain error."""

    class FailingCloseFactory:
        """Small provider double whose close operation always fails."""

        def __init__(self) -> None:
            """Initialize the observable close count."""
            self.close_calls = 0

        def close(self) -> None:
            """Record and fail one provider close attempt."""
            self.close_calls += 1
            raise RuntimeError("provider close failed")

    pin_factory = FailingCloseFactory()
    factory = GpioZeroDeviceFactory(cast(Factory, pin_factory))

    with pytest.raises(GpioProviderError) as raised:
        factory.close()
    factory.close()

    assert raised.value.operation == "close"
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert pin_factory.close_calls == 1


def test_rpi_lifespan_initializes_before_health_and_closes_provider(
    mock_pin_factory: MockFactory,
) -> None:
    """The real-backend application lifespan should own provider readiness."""
    previous = Device.pin_factory
    Device.pin_factory = mock_pin_factory
    try:
        app = create_app(Settings(hardware_backend="rpi"))
        with TestClient(app) as client:
            assert client.get("/api/v1/health").json() == {"status": "ok"}
            assert Device.pin_factory is mock_pin_factory

        assert Device.pin_factory is None
    finally:
        Device.pin_factory = previous
