"""Interface definitions for GPIO pin devices.

Matches standard gpiozero interfaces for pin devices,
allowing to switch between Raspberry Pi and mock GPIO backends seamlessly.
"""
from typing import Protocol
from edge_hardware_service.models.gpio import PullMode


# -- Pin Devices -------------------------
class InputPinDevice(Protocol):
    @property
    def value(self) -> bool: 
        """Read the current value of the input pin."""
        ...

    def close(self) -> None: 
        """Release the input pin BCM number and free associated resources."""
        ...

class DigitalOutputPinDevice(Protocol):
    @property
    def value(self) -> bool: 
        """Read the current value of the digital output pin."""
        ...

    @value.setter
    def value(self, value: bool) -> None: 
        """Write a boolean value to the digital output pin."""
        ...

    def close(self) -> None: 
        """Release the digital output pin BCM number and free associated resources."""
        ...

class PwmOutputPinDevice(Protocol):
    @property
    def value(self) -> float: 
        """Read the current duty cycle value of the PWM output pin."""
        ...

    @value.setter
    def value(self, value: float) -> None: 
        """Write a duty cycle value to the PWM output pin."""
        ...

    def close(self) -> None: 
        """Release the PWM output pin BCM number and free associated resources."""
        ...


# -- Factory functions -------------------------
class GpioDeviceFactory(Protocol):
    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> InputPinDevice:
        """Construct a stateful input pin device
        Args:
            pin (int): The GPIO pin number BCM to configure as an input.
            pull (PullMode): The pull-up/down configuration for the input pin.
        
        Returns:
            An instance of InputPinDevice representing the configured input pin.
        """
        ...

    def create_digital_output(
        self,
        pin: int,
    ) -> DigitalOutputPinDevice:
        """Construct a stateful digital output pin device.

        Args:
            pin (int): The GPIO pin number BCM to configure as a digital output.

        Returns:
            An instance of DigitalOutputPinDevice representing the configured digital output pin.
        """
        ...

    def create_pwm_output(
        self,
        pin: int,
    ) -> PwmOutputPinDevice:
        """Construct a stateful PWM output pin device.

        Args:
            pin (int): The GPIO pin number BCM to configure as a PWM output.

        Returns:
            An instance of PwmOutputPinDevice representing the configured PWM output pin.
        """
        ...