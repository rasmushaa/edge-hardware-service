"""Structural interfaces for GPIO devices and device factories.

The service layer depends on these small protocols instead of gpiozero or the
simulation implementation. This keeps runtime selection at the application
boundary and allows simulation mode to run without Raspberry Pi imports.
"""

from typing import Protocol

from edge_hardware_service.models.gpio import PullMode


class InputPinDevice(Protocol):
    """Readable GPIO input whose value represents its electrical level."""

    @property
    def value(self) -> bool:
        """Return `True` for electrical HIGH and `False` for LOW."""
        ...

    def close(self) -> None:
        """Release resources owned by the device."""
        ...


class DigitalOutputPinDevice(Protocol):
    """Readable and writable digital GPIO output device."""

    @property
    def value(self) -> bool:
        """Return the current logical output value."""
        ...

    @value.setter
    def value(self, value: bool) -> None:
        """Set the logical output value."""
        ...

    def close(self) -> None:
        """Release resources owned by the device."""
        ...


class PwmOutputPinDevice(Protocol):
    """Readable and writable PWM GPIO output device."""

    @property
    def value(self) -> float:
        """Return the current duty cycle as a value from 0.0 to 1.0."""
        ...

    @value.setter
    def value(self, value: float) -> None:
        """Set the duty cycle as a value from 0.0 to 1.0."""
        ...

    @property
    def frequency(self) -> float:
        """Return the PWM frequency in hertz."""
        ...

    @frequency.setter
    def frequency(self, value: float) -> None:
        """Set the PWM frequency in hertz."""
        ...

    def close(self) -> None:
        """Release resources owned by the device."""
        ...


class GpioDeviceFactory(Protocol):
    """Construct devices and own one runtime provider's lifecycle."""

    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> InputPinDevice:
        """Create an input device.

        Args:
            pin: BCM GPIO pin number.
            pull: Internal resistor configuration. Pull direction must not
                invert the returned electrical level.

        Returns:
            A newly opened input device.
        """
        ...

    def create_digital_output(
        self,
        pin: int,
    ) -> DigitalOutputPinDevice:
        """Create a digital output device.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            A newly opened digital output device.
        """
        ...

    def create_pwm_output(
        self,
        pin: int,
        frequency_hz: float | None = None,
    ) -> PwmOutputPinDevice:
        """Create a PWM output device.

        Args:
            pin: BCM GPIO pin number.
            frequency_hz: Requested frequency or the provider default.

        Returns:
            A newly opened PWM output device.
        """
        ...

    def close(self) -> None:
        """Release provider-level resources after all devices are closed."""
        ...
