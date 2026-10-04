from dataclasses import dataclass
from edge_hardware_service.models.gpio import PinMode, PullMode, PinConfig
from edge_hardware_service.hardware.exceptions import PinModeConflict
from edge_hardware_service.hardware.gpio.interface import GpioDeviceFactory, InputPinDevice, DigitalOutputPinDevice, PwmOutputPinDevice


@dataclass
class PinHandle:
    """Handle for a GPIO pin on the Raspberry Pi.

    Attributes:
        pin (int): The GPIO pin number.
        mode (PinMode): The mode of the pin (input, output, PWM).
        device (InputPinDevice | DigitalOutputPinDevice | PwmOutputPinDevice): The underlying stateful gpiozero like device.
        pull (PullMode | None): The pull-up/pull-down configuration for input pins.
    """
    pin: int
    mode: PinMode
    device: InputPinDevice | DigitalOutputPinDevice | PwmOutputPinDevice
    pull: PullMode | None = None


class GpioDeviceService:
    """Backend for managing GPIO pins (BCM numbering) on the Raspberry Pi using gpiozero.
    
    Pin modes are auto assigned based on the first operation performed on the pin.
    Later attempts to use the pin in a different mode will raise a PinModeConflict exception.
    """
    def __init__(self, pin_factory: GpioDeviceFactory):
        """Initialize the Raspberry Pi GPIO backend.

        Args:
            pin_factory (GpioDeviceFactory): The factory for creating GPIO pin devices.
        
        Attributes:
            _pins (dict[int, PinHandle]): A dictionary to store initialized pin handles statefully.
        """
        self._pins: dict[int, PinHandle] = {}
        self._pin_factory = pin_factory


    def read(self, pin: int) -> bool:
        """Read boolean value from an input pin.

        Args:
            pin (int): The GPIO pin number BCM to read from.

        Returns:
            bool: The current value of the input pin.
        """
        handle = self._pins.get(pin)

        # Auto assign pin mode if the pin has not been initialized yet.
        if handle is None:
            device = self._pin_factory.create_input(
                pin,
                PullMode.NONE,
            )
            handle = PinHandle(
                pin=pin,
                mode=PinMode.INPUT,
                device=device,
            )
            self._pins[pin] = handle

        # Force the pin to be in input mode, raise an exception if it is not.
        if handle.mode != PinMode.INPUT:
            raise PinModeConflict(pin, handle.mode)

        return bool(handle.device.value)


    def write(self, pin: int, value: bool) -> None:
        """Write boolean value to an output pin.

        Args:
            pin (int): The GPIO pin number BCM to write to.
            value (bool): The value to set on the output pin.
        """
        handle = self._pins.get(pin)

        # Auto assign pin mode if the pin has not been initialized yet.
        if handle is None:
            device = self._pin_factory.create_digital_output(pin)
            handle = PinHandle(
                pin=pin,
                mode=PinMode.OUTPUT,
                device=device,
            )
            self._pins[pin] = handle

        # Force the pin to be in output mode, raise an exception if it is not.
        if handle.mode != PinMode.OUTPUT:
            raise PinModeConflict(pin, handle.mode)

        handle.device.value = value


    def write_pwm(self, pin: int, duty_cycle: float) -> None:
        """Write a PWM duty cycle to a pin.

        Args:
            pin (int): The GPIO pin number BCM to write to.
            duty_cycle (float): The PWM duty cycle (0.0 to 1.0) to set on the pin.
        """
        handle = self._pins.get(pin)

        # Auto assign pin mode if the pin has not been initialized yet.
        if handle is None:
            device = self._pin_factory.create_pwm_output(pin)
            handle = PinHandle(
                pin=pin,
                mode=PinMode.PWM,
                device=device,
            )
            self._pins[pin] = handle

        # Force the pin to be in PWM mode, raise an exception if it is not.
        if handle.mode != PinMode.PWM:
            raise PinModeConflict(pin, handle.mode)

        handle.device.value = duty_cycle


    def configure(self, pin: int, config: PinConfig) -> None:
        """Configure a GPIO pin with the specified settings.

        Args:
            pin (int): The GPIO pin number BCM to configure.
            config (PinConfig): The configuration settings for the pin.
        """
        handle = self._pins.get(pin)

        # Auto assign pin mode if the pin has not been initialized yet.
        if handle is None:
            if config.mode == PinMode.OUTPUT:
                device = self._pin_factory.create_digital_output(pin)
            elif config.mode == PinMode.PWM:
                device = self._pin_factory.create_pwm_output(pin)
            elif config.mode == PinMode.INPUT:
                device = self._pin_factory.create_input(
                    pin,
                    config.pull,
                )
            else:
                raise ValueError(f"Unsupported pin mode: {config.mode}")

            handle = PinHandle(
                pin=pin,
                mode=config.mode,
                device=device,
                pull=config.pull,
            )
            self._pins[pin] = handle

        # Relases configuration for the pin if it has already been initialized.
        if handle is not None:
            handle.device.close()
            del self._pins[pin]

        # Re-initialize the pin with the new configuration.
        self.configure(pin, config)


    def release(self, pin: int) -> None:
        """Release a GPIO pin, cleaning up its resources.

        Args:
            pin (int): The GPIO pin number BCM to release.
        """
        handle = self._pins.pop(pin, None)
        if handle is not None:
            handle.device.close()


    def close(self) -> None:
        """Close all GPIO pins and clean up resources."""
        for pin in list(self._pins.keys()):
            self.release(pin)
