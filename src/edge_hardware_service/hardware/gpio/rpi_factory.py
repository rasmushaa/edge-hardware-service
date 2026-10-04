from gpiozero import (
    DigitalOutputDevice,
    InputDevice,
    PWMOutputDevice,
)

from edge_hardware_service.models.gpio import PullMode


class RpiDeviceFactory:
    """Factory for creating GPIO pin devices using the gpiozero library.
    
    This only creates GPIO normal gpiozero devices, 
    but enables switching between Raspberry Pi and mock GPIO backends seamlessly.
    """
    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> InputDevice:
        pull_up = {
            PullMode.NONE: None,
            PullMode.UP: True,
            PullMode.DOWN: False,
        }[pull]

        return InputDevice(
            pin,
            pull_up=pull_up,
        )

    def create_digital_output(
        self,
        pin: int,
    ) -> DigitalOutputDevice:
        return DigitalOutputDevice(pin)

    def create_pwm_output(
        self,
        pin: int,
    ) -> PWMOutputDevice:
        return PWMOutputDevice(pin)