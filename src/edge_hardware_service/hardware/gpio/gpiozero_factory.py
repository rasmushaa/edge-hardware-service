"""GPIO device adapters backed by OS-provided gpiozero packages.

This module is imported only when Raspberry Pi mode is selected. Its gpiozero
dependency is installed by the Debian Bookworm container rather than managed by
the portable Python project. Provider exceptions are translated here so no
gpiozero-specific exception crosses into the service or API layers. Input
adapters expose the electrical pin level rather than gpiozero's configurable
active/inactive interpretation.
"""

from collections.abc import Callable
from glob import glob
from logging import getLogger
from typing import TypeVar

from gpiozero import Device, DigitalOutputDevice, InputDevice, PWMOutputDevice
from gpiozero.exc import GPIOZeroError
from gpiozero.pins import Factory

from edge_hardware_service.errors import HardwareUnavailableError
from edge_hardware_service.models.gpio import PullMode

ResultT = TypeVar("ResultT")
logger = getLogger(__name__)

try:
    from lgpio import error as LgpioError
except ModuleNotFoundError:
    PROVIDER_EXCEPTIONS = (GPIOZeroError, OSError, RuntimeError)
else:
    PROVIDER_EXCEPTIONS = (
        GPIOZeroError,
        LgpioError,
        OSError,
        RuntimeError,
    )


def _provider_name(pin_factory: Factory) -> str:
    """Return the fully qualified class name of a GPIO Zero pin factory.

    Args:
        pin_factory: Initialized GPIO Zero provider.

    Returns:
        Stable diagnostic name containing the module and qualified class.
    """
    provider_type = type(pin_factory)
    return f"{provider_type.__module__}.{provider_type.__qualname__}"


def _initialize_default_pin_factory() -> Factory:
    """Initialize and return GPIO Zero's normally selected pin factory.

    Returns:
        Initialized GPIO Zero provider selected by the OS environment.

    Raises:
        HardwareUnavailableError: If GPIO Zero cannot select a usable provider.
    """
    try:
        Device.ensure_pin_factory()
    except PROVIDER_EXCEPTIONS as error:
        raise HardwareUnavailableError(
            "GPIO provider 'gpiozero pin factory' is unavailable in this runtime",
            details={
                "component": "gpio",
                "provider": "gpiozero pin factory",
                "operation": "initialize provider",
            },
        ) from error

    pin_factory = Device.pin_factory
    if pin_factory is None:
        raise HardwareUnavailableError(
            "GPIO provider 'gpiozero pin factory' is unavailable in this runtime",
            details={
                "component": "gpio",
                "provider": "gpiozero pin factory",
                "operation": "initialize provider",
            },
        )
    return pin_factory


def _provider_lifecycle_call(
    provider: str,
    operation: str,
    callback: Callable[[], ResultT],
) -> ResultT:
    """Run a provider-wide lifecycle operation with domain error translation.

    Args:
        provider: Fully qualified provider class name.
        operation: Short description of the lifecycle operation.
        callback: Deferred provider operation.

    Returns:
        Value returned by the provider operation.

    Raises:
        HardwareUnavailableError: If the lower-level provider operation fails.
    """
    try:
        return callback()
    except PROVIDER_EXCEPTIONS as error:
        raise HardwareUnavailableError(
            f"GPIO provider operation {operation!r} failed for {provider!r}",
            details={
                "component": "gpio",
                "provider": provider,
                "operation": operation,
            },
        ) from error


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
        HardwareUnavailableError: If gpiozero or its provider fails.
    """
    try:
        return callback()
    except PROVIDER_EXCEPTIONS as error:
        raise HardwareUnavailableError(
            f"GPIO hardware operation {operation!r} failed for pin {pin}",
            details={
                "component": "gpio",
                "pin": pin,
                "operation": operation,
            },
        ) from error


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
        """Return the current electrical input level.

        The public API defines `True` as electrical HIGH. Reading the
        underlying pin state avoids gpiozero's active-state inversion for an
        input configured with a pull-up resistor.

        Raises:
            HardwareUnavailableError: If the provider cannot read the pin.
        """
        return bool(
            _provider_call(
                self._pin,
                "read input",
                lambda: self._device.pin.state,
            )
        )

    def close(self) -> None:
        """Close the gpiozero input device.

        Raises:
            HardwareUnavailableError: If the provider cannot release the pin.
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
            HardwareUnavailableError: If the provider cannot read the pin.
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
            HardwareUnavailableError: If the provider cannot write the pin.
        """
        _provider_call(
            self._pin,
            "write digital output",
            lambda: setattr(self._device, "value", value),
        )

    def close(self) -> None:
        """Close the gpiozero digital output device.

        Raises:
            HardwareUnavailableError: If the provider cannot release the pin.
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
            HardwareUnavailableError: If the provider cannot read the pin.
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
            HardwareUnavailableError: If the provider cannot write the pin.
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
            HardwareUnavailableError: If the provider cannot read the frequency.
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
            HardwareUnavailableError: If the provider cannot update the frequency.
        """
        _provider_call(
            self._pin,
            "write PWM frequency",
            lambda: setattr(self._device, "frequency", value),
        )

    def close(self) -> None:
        """Close the gpiozero PWM output device.

        Raises:
            HardwareUnavailableError: If the provider cannot release the pin.
        """
        _provider_call(self._pin, "close PWM output", self._device.close)


class GpioZeroDeviceFactory:
    """Own one GPIO Zero provider and create protocol-compatible devices."""

    def __init__(self, pin_factory: Factory | None = None) -> None:
        """Initialize and report the process-scoped GPIO Zero provider.

        Args:
            pin_factory: Optional initialized provider for dependency injection.
                GPIO Zero performs its normal OS-level selection when omitted.

        Raises:
            HardwareUnavailableError: If no GPIO Zero provider can initialize.
        """
        self._pin_factory = (
            _initialize_default_pin_factory() if pin_factory is None else pin_factory
        )
        self._provider_name = _provider_name(self._pin_factory)
        self._controller = getattr(self._pin_factory, "chip", None)
        self._available_gpiochips = tuple(sorted(glob("/dev/gpiochip*")))
        self._closed = False

        logger.info(
            "Initialized GPIO Zero provider %s (controller=%s, available_gpiochips=%s)",
            self._provider_name,
            (self._controller if self._controller is not None else "provider-managed"),
            ",".join(self._available_gpiochips) or "none",
        )

    @property
    def provider_name(self) -> str:
        """Return the fully qualified selected provider class name."""
        return self._provider_name

    @property
    def controller(self) -> object | None:
        """Return the provider-reported GPIO controller, when available."""
        return self._controller

    @property
    def available_gpiochips(self) -> tuple[str, ...]:
        """Return GPIO character devices visible during initialization."""
        return self._available_gpiochips

    def _ensure_open(self) -> None:
        """Reject device creation after the shared provider is closed.

        Raises:
            HardwareUnavailableError: If the provider has already been closed.
        """
        if self._closed:
            raise HardwareUnavailableError(
                (
                    "GPIO provider operation 'create device after close' failed "
                    f"for {self._provider_name!r}"
                ),
                details={
                    "component": "gpio",
                    "provider": self._provider_name,
                    "operation": "create device after close",
                },
            )

    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> _GpioZeroInputDevice:
        """Create a gpiozero input device adapter.

        Args:
            pin: BCM GPIO pin number.
            pull: Internal resistor configuration. This does not change the
                polarity of the returned electrical level.

        Returns:
            A newly opened input device adapter.

        Raises:
            HardwareUnavailableError: If the provider cannot open the pin.
        """
        self._ensure_open()
        pull_up = {
            PullMode.NONE: None,
            PullMode.UP: True,
            PullMode.DOWN: False,
        }[pull]
        input_options: dict[str, bool | None] = {"pull_up": pull_up}
        if pull == PullMode.NONE:
            # GPIO Zero cannot infer active polarity for a floating input.
            # HIGH is active so construction succeeds without changing the
            # API's electrical HIGH/LOW semantics.
            input_options["active_state"] = True

        device = _provider_call(
            pin,
            "open input",
            lambda: InputDevice(
                pin,
                pin_factory=self._pin_factory,
                **input_options,
            ),
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
            HardwareUnavailableError: If the provider cannot open the pin.
        """
        self._ensure_open()
        device = _provider_call(
            pin,
            "open digital output",
            lambda: DigitalOutputDevice(
                pin,
                pin_factory=self._pin_factory,
            ),
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
            HardwareUnavailableError: If the provider cannot open the pin.
        """
        self._ensure_open()
        kwargs = {}
        if frequency_hz is not None:
            kwargs["frequency"] = frequency_hz

        device = _provider_call(
            pin,
            "open PWM output",
            lambda: PWMOutputDevice(
                pin,
                pin_factory=self._pin_factory,
                **kwargs,
            ),
        )
        return _GpioZeroPwmOutputDevice(pin, device)

    def close(self) -> None:
        """Close the shared GPIO Zero provider exactly once.

        Device adapters must be closed before this method is called.

        Raises:
            HardwareUnavailableError: If the provider cannot release its resources.
        """
        if self._closed:
            return
        self._closed = True

        try:
            _provider_lifecycle_call(
                self._provider_name,
                "close",
                self._pin_factory.close,
            )
        finally:
            if Device.pin_factory is self._pin_factory:
                Device.pin_factory = None

        logger.info("Closed GPIO Zero provider %s", self._provider_name)
