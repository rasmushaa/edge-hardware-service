"""Device placeholder used when loading or initializing Picamera2 fails."""

from collections.abc import Callable

from edge_hardware_service.hardware.camera.exceptions import CameraUnavailable
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
        raise CameraUnavailable(self._reason)

    @property
    def stream_info(self) -> CameraStreamInfo | None:
        return None

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        del settings, publish_frame
        raise CameraUnavailable(self._reason)

    def reconfigure(self, settings: CameraSettings) -> None:
        del settings
        raise CameraUnavailable(self._reason)

    def validate_settings(self, settings: CameraSettings) -> None:
        del settings
        raise CameraUnavailable(self._reason)

    def autofocus(self, timeout_seconds: float) -> bool:
        del timeout_seconds
        raise CameraUnavailable(self._reason)

    def close(self) -> None:
        """No device was created, so there are no resources to release."""
