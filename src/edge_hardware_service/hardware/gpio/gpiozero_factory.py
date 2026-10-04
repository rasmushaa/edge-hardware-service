"""GPIO device adapters backed by OS-provided gpiozero packages.

This module is imported only when Raspberry Pi mode is selected. Its gpiozero
dependency is installed by the Debian Bookworm container rather than managed by
the portable Python project. Provider exceptions are translated here so no
gpiozero-specific exception crosses into the service or API layers.
"""

from collections.abc import Callable
from typing import TypeVar

from gpiozero import DigitalOutputDevice, InputDevice, PWMOutputDevice
from gpiozero.exc import GPIOZeroError

from edge_hardware_service.hardware.gpio.exceptions import GpioHardwareError
from edge_hardware_service.models.gpio import PullMode


ResultT = TypeVar("ResultT")


def _provider_call(
    pin: int,
    operation: str,
    callback: Callable[[], ResultT],
) -> ResultT:
    """Run a gpiozero operation and translate expected provider failures.

    Args:
        pin: BCM GPIO pin number.
        operation: Short description of the provider operation.
        callback: Deferred gpiozero operation.

    Returns:
        Value returned by the provider operation.

    Raises:
        GpioHardwareError: If gpiozero or its lower-level provider fails.
    """
    try:
        return callback()
    except (GPIOZeroError, OSError) as error:
        raise GpioHardwareError(pin, operation) from error


class _GpioZeroInputDevice:
    """Adapt a gpiozero input device to the application protocol."""

    def __init__(self, pin: int, device: InputDevice) -> None:
        """Initialize the adapter.

        Args:
            pin: BCM GPIO pin number.
            device: Open gpiozero input device.
        """
        self._pin = pin
        self._device = device

    @property
    def value(self) -> bool:
        """Return the current logical input value.

        Raises:
            GpioHardwareError: If the provider cannot read the pin.
        """
        return bool(
            _provider_call(
                self._pin,
                "read input",
                lambda: self._device.value,
            )
        )

    def close(self) -> None:
        """Close the gpiozero input device.

        Raises:
            GpioHardwareError: If the provider cannot release the pin.
        """
        _provider_call(self._pin, "close input", self._device.close)


class _GpioZeroDigitalOutputDevice:
    """Adapt a gpiozero digital output device to the application protocol."""

    def __init__(self, pin: int, device: DigitalOutputDevice) -> None:
        """Initialize the adapter.

        Args:
            pin: BCM GPIO pin number.
            device: Open gpiozero digital output device.
        """
        self._pin = pin
        self._device = device

    @property
    def value(self) -> bool:
        """Return the current logical output value.

        Raises:
            GpioHardwareError: If the provider cannot read the pin.
        """
        return bool(
            _provider_call(
                self._pin,
                "read digital output",
                lambda: self._device.value,
            )
        )

    @value.setter
    def value(self, value: bool) -> None:
        """Set the logical output value.

        Args:
            value: Logical output value.

        Raises:
            GpioHardwareError: If the provider cannot write the pin.
        """
        _provider_call(
            self._pin,
            "write digital output",
            lambda: setattr(self._device, "value", value),
        )

    def close(self) -> None:
        """Close the gpiozero digital output device.

        Raises:
            GpioHardwareError: If the provider cannot release the pin.
        """
        _provider_call(
            self._pin,
            "close digital output",
            self._device.close,
        )


class _GpioZeroPwmOutputDevice:
    """Adapt a gpiozero PWM output device to the application protocol."""

    def __init__(self, pin: int, device: PWMOutputDevice) -> None:
        """Initialize the adapter.

        Args:
            pin: BCM GPIO pin number.
            device: Open gpiozero PWM output device.
        """
        self._pin = pin
        self._device = device

    @property
    def value(self) -> float:
        """Return the current duty cycle.

        Raises:
            GpioHardwareError: If the provider cannot read the pin.
        """
        return float(
            _provider_call(
                self._pin,
                "read PWM duty cycle",
                lambda: self._device.value,
            )
        )

    @value.setter
    def value(self, value: float) -> None:
        """Set the duty cycle.

        Args:
            value: Duty cycle from 0.0 to 1.0.

        Raises:
            GpioHardwareError: If the provider cannot write the pin.
        """
        _provider_call(
            self._pin,
            "write PWM duty cycle",
            lambda: setattr(self._device, "value", value),
        )

    @property
    def frequency(self) -> float:
        """Return the current PWM frequency in hertz.

        Raises:
            GpioHardwareError: If the provider cannot read the frequency.
        """
        return float(
            _provider_call(
                self._pin,
                "read PWM frequency",
                lambda: self._device.frequency,
            )
        )

    @frequency.setter
    def frequency(self, value: float) -> None:
        """Set the PWM frequency.

        Args:
            value: Positive frequency in hertz.

        Raises:
            GpioHardwareError: If the provider cannot update the frequency.
        """
        _provider_call(
            self._pin,
            "write PWM frequency",
            lambda: setattr(self._device, "frequency", value),
        )

    def close(self) -> None:
        """Close the gpiozero PWM output device.

        Raises:
            GpioHardwareError: If the provider cannot release the pin.
        """
        _provider_call(self._pin, "close PWM output", self._device.close)


class GpioZeroDeviceFactory:
    """Create protocol-compatible GPIO devices through gpiozero."""

    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> _GpioZeroInputDevice:
        """Create a gpiozero input device adapter.

        Args:
            pin: BCM GPIO pin number.
            pull: Pull-up or pull-down configuration.

        Returns:
            A newly opened input device adapter.

        Raises:
            GpioHardwareError: If the provider cannot open the pin.
        """
        pull_up = {
            PullMode.NONE: None,
            PullMode.UP: True,
            PullMode.DOWN: False,
        }[pull]
        device = _provider_call(
            pin,
            "open input",
            lambda: InputDevice(pin, pull_up=pull_up),
        )
        return _GpioZeroInputDevice(pin, device)

    def create_digital_output(
        self,
        pin: int,
    ) -> _GpioZeroDigitalOutputDevice:
        """Create a gpiozero digital output device adapter.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            A newly opened digital output device adapter.

        Raises:
            GpioHardwareError: If the provider cannot open the pin.
        """
        device = _provider_call(
            pin,
            "open digital output",
            lambda: DigitalOutputDevice(pin),
        )
        return _GpioZeroDigitalOutputDevice(pin, device)

    def create_pwm_output(
        self,
        pin: int,
        frequency_hz: float | None = None,
    ) -> _GpioZeroPwmOutputDevice:
        """Create a gpiozero PWM output device adapter.

        Args:
            pin: BCM GPIO pin number.
            frequency_hz: Requested frequency or the gpiozero default.

        Returns:
            A newly opened PWM output device adapter.

        Raises:
            GpioHardwareError: If the provider cannot open the pin.
        """
        kwargs = {}
        if frequency_hz is not None:
            kwargs["frequency"] = frequency_hz

        device = _provider_call(
            pin,
            "open PWM output",
            lambda: PWMOutputDevice(pin, **kwargs),
        )
        return _GpioZeroPwmOutputDevice(pin, device)
