"""Stateful GPIO service shared by physical and simulation runtimes.

The service is the sole owner of the active pin registry. It serializes device
lifecycle transitions and delegates only device construction to the selected
runtime factory.
"""

from dataclasses import dataclass, field
from threading import RLock
from typing import Literal, TypeAlias, cast

from edge_hardware_service.hardware.gpio.exceptions import (
    PinModeConflict,
    PinNotOpen,
)
from edge_hardware_service.hardware.gpio.protocols import (
    DigitalOutputPinDevice,
    GpioDeviceFactory,
    InputPinDevice,
    PwmOutputPinDevice,
)
from edge_hardware_service.models.gpio import (
    ConfigurationSource,
    PinConfigurationRequest,
    PinMode,
    PullMode,
)


@dataclass(slots=True)
class PinHandle:
    """Track one open GPIO device inside the service.

    Attributes:
        pin: BCM GPIO pin number.
        mode: Active pin mode.
        device: Stateful physical or simulated device.
        configuration_source: Whether an operation or explicit request opened
            the pin.
        pull: Pull configuration for an input device.
    """

    pin: int
    mode: PinMode
    device: InputPinDevice | DigitalOutputPinDevice | PwmOutputPinDevice
    configuration_source: ConfigurationSource
    pull: PullMode | None = None


@dataclass(frozen=True, slots=True)
class InputPinSnapshot:
    """Immutable service-level state for an open input pin."""

    pin: int
    value: bool
    pull: PullMode
    configuration_source: ConfigurationSource
    mode: Literal[PinMode.INPUT] = field(default=PinMode.INPUT, init=False)


@dataclass(frozen=True, slots=True)
class DigitalOutputPinSnapshot:
    """Immutable service-level state for an open digital output pin."""

    pin: int
    value: bool
    configuration_source: ConfigurationSource
    mode: Literal[PinMode.OUTPUT] = field(default=PinMode.OUTPUT, init=False)


@dataclass(frozen=True, slots=True)
class PwmOutputPinSnapshot:
    """Immutable service-level state for an open PWM output pin."""

    pin: int
    duty_cycle: float
    frequency_hz: float
    configuration_source: ConfigurationSource
    mode: Literal[PinMode.PWM] = field(default=PinMode.PWM, init=False)


PinSnapshot: TypeAlias = (
    InputPinSnapshot | DigitalOutputPinSnapshot | PwmOutputPinSnapshot
)


class GpioService:
    """Manage GPIO devices and their active BCM pin assignments.

    Pin modes are assigned by the first operation performed on an unopened pin.
    Later attempts to use the pin in another mode raise `PinModeConflict`.
    Registry lookup, creation, reconfiguration, and release are serialized so a
    pin cannot be opened twice by concurrent requests.
    """

    def __init__(self, pin_factory: GpioDeviceFactory) -> None:
        """Initialize the GPIO service.

        Args:
            pin_factory: Factory for the selected runtime implementation.
        """
        self._pins: dict[int, PinHandle] = {}
        self._pin_factory = pin_factory
        self._lock = RLock()

    def read(self, pin: int) -> bool:
        """Read a digital input value.

        An unopened pin is implicitly configured as an input without a pull
        resistor.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            Current logical input value.

        Raises:
            PinModeConflict: If the pin is open in another mode.
        """
        with self._lock:
            handle = self._pins.get(pin)
            if handle is None:
                handle = self._create_handle(
                    pin,
                    PinMode.INPUT,
                    configuration_source="implicit",
                    pull=PullMode.NONE,
                )
                self._pins[pin] = handle

            self._require_mode(handle, PinMode.INPUT)
            device = cast(InputPinDevice, handle.device)
            return bool(device.value)

    def write(self, pin: int, value: bool) -> DigitalOutputPinSnapshot:
        """Write a digital output value.

        An unopened pin is implicitly configured as a digital output.

        Args:
            pin: BCM GPIO pin number.
            value: Logical output value.

        Returns:
            Snapshot of the digital output after the write.

        Raises:
            PinModeConflict: If the pin is open in another mode.
        """
        with self._lock:
            handle = self._pins.get(pin)
            if handle is None:
                handle = self._create_handle(
                    pin,
                    PinMode.OUTPUT,
                    configuration_source="implicit",
                )
                self._pins[pin] = handle

            self._require_mode(handle, PinMode.OUTPUT)
            device = cast(DigitalOutputPinDevice, handle.device)
            device.value = value
            return cast(DigitalOutputPinSnapshot, self._snapshot(handle))

    def write_pwm(
        self,
        pin: int,
        duty_cycle: float,
        frequency_hz: float | None = None,
    ) -> PwmOutputPinSnapshot:
        """Write a PWM duty cycle.

        An unopened pin is implicitly configured as a PWM output.

        Args:
            pin: BCM GPIO pin number.
            duty_cycle: Duty cycle from 0.0 to 1.0.
            frequency_hz: Optional positive PWM frequency in hertz. An omitted
                value preserves the active frequency or uses the factory default
                when opening a pin.

        Returns:
            Snapshot of the PWM output after the write.

        Raises:
            PinModeConflict: If the pin is open in another mode.
            ValueError: If the duty cycle is outside the supported range.
        """
        if not 0.0 <= duty_cycle <= 1.0:
            raise ValueError("Duty cycle must be between 0 and 1")
        if frequency_hz is not None and frequency_hz <= 0.0:
            raise ValueError("PWM frequency must be greater than 0")

        with self._lock:
            handle = self._pins.get(pin)
            if handle is None:
                handle = self._create_handle(
                    pin,
                    PinMode.PWM,
                    configuration_source="implicit",
                    frequency_hz=frequency_hz,
                )
                self._pins[pin] = handle

            self._require_mode(handle, PinMode.PWM)
            device = cast(PwmOutputPinDevice, handle.device)
            if frequency_hz is not None:
                device.frequency = frequency_hz
            device.value = duty_cycle
            return cast(PwmOutputPinSnapshot, self._snapshot(handle))

    def configure(
        self,
        pin: int,
        config: PinConfigurationRequest,
    ) -> PinSnapshot:
        """Explicitly configure or reconfigure a GPIO pin.

        An existing device is closed before its replacement is created. If
        closing fails, the existing handle remains registered and the error is
        propagated. If replacement creation fails, the pin remains released.

        Args:
            pin: BCM GPIO pin number.
            config: Requested pin mode and input pull configuration.

        Returns:
            Snapshot of the newly configured pin.

        Raises:
            Exception: If the existing device cannot be closed or the selected
                factory cannot create the replacement device.
        """
        with self._lock:
            existing = self._pins.get(pin)
            if existing is not None:
                existing.device.close()
                del self._pins[pin]

            handle = self._create_handle(
                pin,
                config.mode,
                configuration_source="explicit",
                pull=config.pull,
                frequency_hz=config.frequency_hz,
            )
            self._pins[pin] = handle
            return self._snapshot(handle)

    def get_pin_status(self, pin: int) -> PinSnapshot:
        """Return the current state of one open pin.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            Immutable snapshot of the pin's effective state.

        Raises:
            PinNotOpen: If no device owns the pin.
        """
        with self._lock:
            handle = self._pins.get(pin)
            if handle is None:
                raise PinNotOpen(pin)
            return self._snapshot(handle)

    def list_pin_statuses(self) -> tuple[PinSnapshot, ...]:
        """Return all open pins ordered by BCM pin number.

        Returns:
            Immutable tuple of pin snapshots.
        """
        with self._lock:
            return tuple(
                self._snapshot(self._pins[pin]) for pin in sorted(self._pins)
            )

    def release(self, pin: int) -> bool:
        """Release one GPIO pin.

        Args:
            pin: BCM GPIO pin number.

        Returns:
            `True` when an open pin was released, otherwise `False`.

        Raises:
            Exception: If the device cannot be closed. The handle remains
                registered when this happens.
        """
        with self._lock:
            handle = self._pins.get(pin)
            if handle is None:
                return False

            handle.device.close()
            del self._pins[pin]
            return True

    def close(self) -> None:
        """Release every registered GPIO pin.

        All devices receive a close attempt even when another device fails to
        close. Successfully closed handles are removed from the registry.

        Raises:
            ExceptionGroup: If one or more devices fail to close.
        """
        failures: list[Exception] = []

        with self._lock:
            for pin in tuple(self._pins):
                try:
                    self.release(pin)
                except Exception as error:
                    failures.append(error)

        if failures:
            raise ExceptionGroup("Failed to close GPIO devices", failures)

    def _create_handle(
        self,
        pin: int,
        mode: PinMode,
        *,
        configuration_source: ConfigurationSource,
        pull: PullMode = PullMode.NONE,
        frequency_hz: float | None = None,
    ) -> PinHandle:
        """Create an internal handle through the selected device factory.

        Args:
            pin: BCM GPIO pin number.
            mode: Device mode to create.
            configuration_source: Origin of the configuration.
            pull: Input pull configuration.
            frequency_hz: Optional PWM frequency in hertz.

        Returns:
            Unregistered handle containing the newly opened device.

        Raises:
            ValueError: If the mode is unsupported.
        """
        if mode == PinMode.INPUT:
            device = self._pin_factory.create_input(pin, pull)
            return PinHandle(
                pin=pin,
                mode=mode,
                device=device,
                configuration_source=configuration_source,
                pull=pull,
            )

        if mode == PinMode.OUTPUT:
            device = self._pin_factory.create_digital_output(pin)
            return PinHandle(
                pin=pin,
                mode=mode,
                device=device,
                configuration_source=configuration_source,
            )

        if mode == PinMode.PWM:
            device = self._pin_factory.create_pwm_output(pin, frequency_hz)
            return PinHandle(
                pin=pin,
                mode=mode,
                device=device,
                configuration_source=configuration_source,
            )

        raise ValueError(f"Unsupported pin mode: {mode}")

    @staticmethod
    def _require_mode(handle: PinHandle, expected: PinMode) -> None:
        """Ensure that a handle is open in the expected mode.

        Args:
            handle: Active pin handle.
            expected: Mode required by the operation.

        Raises:
            PinModeConflict: If the active mode does not match.
        """
        if handle.mode != expected:
            raise PinModeConflict(handle.pin, handle.mode, expected)

    @staticmethod
    def _snapshot(handle: PinHandle) -> PinSnapshot:
        """Create an immutable status value from an internal handle.

        Args:
            handle: Active pin handle.

        Returns:
            Typed snapshot matching the active mode.

        Raises:
            ValueError: If the handle contains an unsupported mode.
        """
        if handle.mode == PinMode.INPUT:
            device = cast(InputPinDevice, handle.device)
            return InputPinSnapshot(
                pin=handle.pin,
                value=bool(device.value),
                pull=handle.pull or PullMode.NONE,
                configuration_source=handle.configuration_source,
            )

        if handle.mode == PinMode.OUTPUT:
            device = cast(DigitalOutputPinDevice, handle.device)
            return DigitalOutputPinSnapshot(
                pin=handle.pin,
                value=bool(device.value),
                configuration_source=handle.configuration_source,
            )

        if handle.mode == PinMode.PWM:
            device = cast(PwmOutputPinDevice, handle.device)
            return PwmOutputPinSnapshot(
                pin=handle.pin,
                duty_cycle=float(device.value),
                frequency_hz=float(device.frequency),
                configuration_source=handle.configuration_source,
            )

        raise ValueError(f"Unsupported pin mode: {handle.mode}")
