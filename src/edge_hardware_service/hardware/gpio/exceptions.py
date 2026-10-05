"""Domain exceptions raised while managing GPIO resources."""

from edge_hardware_service.models.gpio import PinMode


class PinModeConflict(Exception):
    """Indicate that an operation conflicts with a pin's active mode.

    Attributes:
        pin: BCM GPIO pin number.
        mode: Mode currently assigned to the pin.
        requested_mode: Mode required by the rejected operation.
    """

    def __init__(
        self,
        pin: int,
        mode: PinMode,
        requested_mode: PinMode,
    ) -> None:
        """Initialize the conflict.

        Args:
            pin: BCM GPIO pin number.
            mode: Mode currently assigned to the pin.
            requested_mode: Mode required by the rejected operation.
        """
        self.pin = pin
        self.mode = mode
        self.requested_mode = requested_mode
        super().__init__(
            f"GPIO pin {pin} is open as {mode.value}, not {requested_mode.value}"
        )


class PinAlreadyOpen(RuntimeError):
    """Indicate that a device already owns a GPIO pin.

    Attributes:
        pin: BCM GPIO pin number.
    """

    def __init__(self, pin: int) -> None:
        """Initialize the reservation error.

        Args:
            pin: BCM GPIO pin number.
        """
        self.pin = pin
        super().__init__(f"GPIO pin {pin} is already open")


class PinNotOpen(LookupError):
    """Indicate that no active device owns a requested GPIO pin.

    Attributes:
        pin: BCM GPIO pin number.
    """

    def __init__(self, pin: int) -> None:
        """Initialize the lookup error.

        Args:
            pin: BCM GPIO pin number.
        """
        self.pin = pin
        super().__init__(f"GPIO pin {pin} is not open")


class PinDeviceClosed(RuntimeError):
    """Indicate an attempted operation on a closed GPIO device.

    Attributes:
        pin: BCM GPIO pin number.
    """

    def __init__(self, pin: int) -> None:
        """Initialize the lifecycle error.

        Args:
            pin: BCM GPIO pin number.
        """
        self.pin = pin
        super().__init__(f"GPIO device for pin {pin} is closed")


class GpioHardwareError(RuntimeError):
    """Indicate that a physical GPIO provider operation failed.

    Attributes:
        pin: BCM GPIO pin number.
        operation: Hardware operation that failed.
    """

    def __init__(self, pin: int, operation: str) -> None:
        """Initialize the provider error.

        Args:
            pin: BCM GPIO pin number.
            operation: Short description of the failed operation.
        """
        self.pin = pin
        self.operation = operation
        super().__init__(f"GPIO hardware operation {operation!r} failed for pin {pin}")


class GpioProviderUnavailable(RuntimeError):
    """Indicate that the configured GPIO provider cannot be initialized."""

    def __init__(self, provider: str) -> None:
        """Initialize the provider availability error.

        Args:
            provider: Missing provider or package name.
        """
        self.provider = provider
        super().__init__(f"GPIO provider {provider!r} is unavailable in this runtime")


class GpioProviderError(RuntimeError):
    """Indicate that a provider-wide lifecycle operation failed.

    Attributes:
        provider: Fully qualified provider class name.
        operation: Provider lifecycle operation that failed.
    """

    def __init__(self, provider: str, operation: str) -> None:
        """Initialize the provider lifecycle error.

        Args:
            provider: Fully qualified provider class name.
            operation: Short description of the failed operation.
        """
        self.provider = provider
        self.operation = operation
        super().__init__(
            f"GPIO provider operation {operation!r} failed for {provider!r}"
        )
