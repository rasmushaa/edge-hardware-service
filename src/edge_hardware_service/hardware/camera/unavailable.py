"""Device placeholder used when loading or initializing Picamera2 fails."""

from collections.abc import Callable

from edge_hardware_service.errors import HardwareUnavailableError
from edge_hardware_service.models.camera import (
    CameraCapabilities,
    CameraSettings,
    CameraStreamInfo,
    CameraTelemetry,
)


class UnavailableCameraDevice:
    """Retain a startup failure as a usable degraded camera service input."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def _error(self, operation: str) -> HardwareUnavailableError:
        return HardwareUnavailableError(
            self._reason,
            details={"component": "camera", "operation": operation},
        )

    @property
    def device_index(self) -> int | None:
        return None

    @property
    def device_model(self) -> str | None:
        return None

    @property
    def telemetry(self) -> CameraTelemetry:
        return CameraTelemetry(focus_state="unavailable")

    @property
    def capabilities(self) -> CameraCapabilities:
        raise self._error("inspect capabilities")

    @property
    def stream_info(self) -> CameraStreamInfo | None:
        return None

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        del settings, publish_frame
        raise self._error("start camera")

    def reconfigure(self, settings: CameraSettings) -> None:
        del settings
        raise self._error("update settings")

    def validate_settings(self, settings: CameraSettings) -> None:
        del settings
        raise self._error("validate settings")

    def autofocus(self, timeout_seconds: float) -> bool:
        del timeout_seconds
        raise self._error("autofocus")

    def close(self) -> None:
        """No device was created, so there are no resources to release."""
