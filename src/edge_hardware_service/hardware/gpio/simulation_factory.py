"""Pure-Python GPIO devices and factory for the simulation runtime.

The simulation implementation mirrors the lifecycle of physical devices while
remaining independent of gpiozero and Raspberry Pi system packages. State is
kept in memory for the lifetime of the application process. Input values are
deterministic and derived only from pull configuration; `True` represents HIGH
and `False` represents LOW.
"""

from logging import getLogger
from threading import Lock
from typing import TypeVar

from edge_hardware_service.hardware.gpio.exceptions import (
    PinAlreadyOpen,
    PinDeviceClosed,
)
from edge_hardware_service.models.gpio import PullMode

logger = getLogger(__name__)


class _SimulationDevice:
    """Provide lifecycle behavior shared by simulated GPIO devices."""

    def __init__(self, pin: int) -> None:
        """Initialize an open simulated device.

        Args:
            pin: BCM GPIO pin number.
        """
        self.pin = pin
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return whether the device has been closed."""
        return self._closed

    def close(self) -> None:
        """Close the device.

        Closing an already closed simulated device is a safe no-op.
        """
        if self._closed:
            return

        logger.info("Closing simulated GPIO device for pin %d", self.pin)
        self._closed = True

    def _ensure_open(self) -> None:
        """Reject access after the device has been closed.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        if self._closed:
            raise PinDeviceClosed(self.pin)


class SimulationInputDevice(_SimulationDevice):
    """In-memory GPIO input device.

    Attributes:
        pin: BCM GPIO pin number.
        closed: Whether the device has been closed.
    """

    def __init__(self, pin: int, value: bool = False) -> None:
        """Initialize an input device.

        Args:
            pin: BCM GPIO pin number.
            value: Initial electrical level, where `True` is HIGH.
        """
        super().__init__(pin)
        self._value = value

    @property
    def value(self) -> bool:
        """Return the current simulated electrical input level.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        self._ensure_open()
        logger.info(
            "Reading simulated input value for pin %d: %s",
            self.pin,
            self._value,
        )
        return self._value


class SimulationDigitalOutputDevice(_SimulationDevice):
    """In-memory GPIO digital output device.

    Attributes:
        pin: BCM GPIO pin number.
        closed: Whether the device has been closed.
    """

    def __init__(self, pin: int) -> None:
        """Initialize a digital output device.

        Args:
            pin: BCM GPIO pin number.
        """
        super().__init__(pin)
        self._value = False

    @property
    def value(self) -> bool:
        """Return the current simulated output value.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        self._ensure_open()
        logger.info(
            "Reading simulated digital output for pin %d: %s",
            self.pin,
            self._value,
        )
        return self._value

    @value.setter
    def value(self, value: bool) -> None:
        """Set the simulated output value.

        Args:
            value: Logical output value.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        self._ensure_open()
        logger.info(
            "Setting simulated digital output for pin %d: %s",
            self.pin,
            value,
        )
        self._value = value


class SimulationPwmOutputDevice(_SimulationDevice):
    """In-memory GPIO PWM output device.

    Attributes:
        pin: BCM GPIO pin number.
        closed: Whether the device has been closed.
    """

    def __init__(self, pin: int, frequency_hz: float = 100.0) -> None:
        """Initialize a PWM output device.

        Args:
            pin: BCM GPIO pin number.
            frequency_hz: Initial PWM frequency in hertz.

        Raises:
            ValueError: If the frequency is not positive.
        """
        if frequency_hz <= 0.0:
            raise ValueError("PWM frequency must be greater than 0")

        super().__init__(pin)
        self._value = 0.0
        self._frequency = frequency_hz

    @property
    def value(self) -> float:
        """Return the simulated duty cycle.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        self._ensure_open()
        logger.info(
            "Reading simulated PWM output for pin %d: %s",
            self.pin,
            self._value,
        )
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        """Set the simulated duty cycle.

        Args:
            value: Duty cycle from 0.0 to 1.0.

        Raises:
            PinDeviceClosed: If the device is closed.
            ValueError: If the duty cycle is outside the supported range.
        """
        self._ensure_open()
        if not 0.0 <= value <= 1.0:
            raise ValueError("Duty cycle must be between 0 and 1")

        logger.info(
            "Setting simulated PWM output for pin %d: %s",
            self.pin,
            value,
        )
        self._value = value

    @property
    def frequency(self) -> float:
        """Return the simulated PWM frequency.

        Raises:
            PinDeviceClosed: If the device is closed.
        """
        self._ensure_open()
        return self._frequency

    @frequency.setter
    def frequency(self, value: float) -> None:
        """Set the simulated PWM frequency.

        Args:
            value: Positive frequency in hertz.

        Raises:
            PinDeviceClosed: If the device is closed.
            ValueError: If the frequency is not positive.
        """
        self._ensure_open()
        if value <= 0.0:
            raise ValueError("PWM frequency must be greater than 0")
        self._frequency = value


SimulationDevice = (
    SimulationInputDevice | SimulationDigitalOutputDevice | SimulationPwmOutputDevice
)

DeviceT = TypeVar(
    "DeviceT",
    SimulationInputDevice,
    SimulationDigitalOutputDevice,
    SimulationPwmOutputDevice,
)


class SimulationDeviceFactory:
    """Create and reserve in-memory GPIO devices.

    The factory prevents two open devices from owning the same BCM pin. Closed
    devices may be replaced by a new device in any supported mode.
    """

    def __init__(self) -> None:
        """Initialize an empty simulated device registry."""
        self._devices: dict[int, SimulationDevice] = {}
        self._lock = Lock()

    def _register(self, pin: int, device: DeviceT) -> DeviceT:
        """Reserve a pin for a newly created device.

        Args:
            pin: BCM GPIO pin number.
            device: Device that should own the pin.

        Returns:
            The registered device.

        Raises:
            PinAlreadyOpen: If another open device owns the pin.
        """
        with self._lock:
            existing = self._devices.get(pin)

            if existing is not None and not existing.closed:
                raise PinAlreadyOpen(pin)

            self._devices[pin] = device
            return device

    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> SimulationInputDevice:
        """Create a simulated input device.

        Args:
            pin: BCM GPIO pin number.
            pull: Pull configuration used to determine the initial value.

        Returns:
            A newly opened simulated input device.

        Raises:
            PinAlreadyOpen: If another open device owns the pin.
        """
        initial_value = pull == PullMode.UP
        logger.info(
            "Creating simulated input for pin %d with initial value %s",
            pin,
            initial_value,
        )
        return self._register(
            pin,
            SimulationInputDevice(pin, initial_value),
        )

    def create_digital_output(
        self,
        pin: int,
    ) -> SimulationDigitalOutputDevice:
        """Create a simulated digital output device.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            A newly opened simulated digital output device.

        Raises:
            PinAlreadyOpen: If another open device owns the pin.
        """
        logger.info("Creating simulated digital output for pin %d", pin)
        return self._register(pin, SimulationDigitalOutputDevice(pin))

    def create_pwm_output(
        self,
        pin: int,
        frequency_hz: float | None = None,
    ) -> SimulationPwmOutputDevice:
        """Create a simulated PWM output device.

        Args:
            pin: BCM GPIO pin number.
            frequency_hz: Requested frequency or the 100 Hz default.

        Returns:
            A newly opened simulated PWM output device.

        Raises:
            PinAlreadyOpen: If another open device owns the pin.
        """
        logger.info("Creating simulated PWM output for pin %d", pin)
        return self._register(
            pin,
            SimulationPwmOutputDevice(
                pin,
                frequency_hz=(100.0 if frequency_hz is None else frequency_hz),
            ),
        )

    def close(self) -> None:
        """Release provider-level resources.

        The simulation factory owns no resource beyond the devices closed by
        `GpioService`, so this operation is intentionally a no-op.
        """
