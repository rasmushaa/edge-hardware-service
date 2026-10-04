from threading import Lock
from typing import TypeVar
from edge_hardware_service.models.gpio import PullMode
from logging import getLogger

logger = getLogger(__name__)


# -- Mock Pin Devices -------------------------
class MockInputDevice:
    def __init__(self, pin: int, value: bool = False) -> None:
        self.pin = pin
        self._value = value
        self.closed = False

    @property
    def value(self) -> bool:
        logger.info("Reading value from mock input device for pin %d: %s", self.pin, self._value)
        return self._value

    def close(self) -> None:
        logger.info("Closing mock input device for pin %d", self.pin)
        self.closed = True


class MockDigitalOutputDevice:
    def __init__(self, pin: int) -> None:
        self.pin = pin
        self._value = False
        self.closed = False

    @property
    def value(self) -> bool:
        logger.info("Reading value from mock digital output device for pin %d: %s", self.pin, self._value)
        return self._value

    @value.setter
    def value(self, value: bool) -> None:
        logger.info("Setting value on mock digital output device for pin %d: %s", self.pin, value)
        self._value = value

    def close(self) -> None:
        logger.info("Closing mock digital output device for pin %d", self.pin)
        self.closed = True


class MockPwmOutputDevice:
    def __init__(
        self,
        pin: int,
    ) -> None:
        self.pin = pin
        self._value = 0.0
        self.closed = False

    @property
    def value(self) -> float:
        logger.info("Reading value from mock PWM output device for pin %d: %s", self.pin, self._value)
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Duty cycle must be between 0 and 1")

        logger.info("Setting value on mock PWM output device for pin %d: %s", self.pin, value)
        self._value = value

    def close(self) -> None:
        logger.info("Closing mock PWM output device for pin %d", self.pin)
        self.closed = True


# -- Type Aliases and Exceptions -------------------------
MockDevice = (
    MockInputDevice
    | MockDigitalOutputDevice
    | MockPwmOutputDevice
)

DeviceT = TypeVar(
    "DeviceT",
    MockInputDevice,
    MockDigitalOutputDevice,
    MockPwmOutputDevice,
)

class PinAlreadyOpen(RuntimeError):
    def __init__(self, pin: int) -> None:
        self.pin = pin
        super().__init__(f"GPIO pin {pin} is already open")


# -- Mock Device Factory -------------------------
class MockDeviceFactory:
    """Mock device factory for GPIO pins.
    
    Validates that GPIO pins are not already open before creating new mock devices,
    like the gpiozero library does.
    """
    def __init__(self) -> None:
        self._devices: dict[int, MockDevice] = {}
        self._lock = Lock()

    def _register(
        self,
        pin: int,
        device: DeviceT,
    ) -> DeviceT:
        with self._lock:
            existing = self._devices.get(pin)

            if existing is not None and not existing.closed:
                raise PinAlreadyOpen(pin)

            # A previously closed device may be replaced.
            self._devices[pin] = device
            return device

    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> MockInputDevice:
        initial_value = pull == PullMode.UP
        logger.info("Creating mock input device for pin %d with initial value %s", pin, initial_value)
        return self._register(
            pin,
            MockInputDevice(pin, initial_value),
        )

    def create_digital_output(
        self,
        pin: int,
    ) -> MockDigitalOutputDevice:
        logger.info("Creating mock digital output device for pin %d", pin)
        return self._register(
            pin,
            MockDigitalOutputDevice(pin),
        )

    def create_pwm_output(
        self,
        pin: int,
    ) -> MockPwmOutputDevice:
        logger.info("Creating mock PWM output device for pin %d", pin)
        return self._register(
            pin,
            MockPwmOutputDevice(pin),
        )