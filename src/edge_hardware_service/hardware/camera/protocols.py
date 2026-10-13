"""Small structural boundary between camera policy and device adapters."""

from collections.abc import Callable
from typing import Protocol

from edge_hardware_service.models.camera import (
    CameraCapabilities,
    CameraSettings,
    CameraStreamInfo,
    CameraTelemetry,
)

CameraDeviceFactory = Callable[[int], "CameraDevice"]


class CameraDevice(Protocol):
    """One continuously running JPEG camera pipeline."""

    @property
    def device_index(self) -> int | None:
        """Return the selected hardware index, when known."""
        ...

    @property
    def device_model(self) -> str | None:
        """Return the detected sensor model, when known."""
        ...

    @property
    def telemetry(self) -> CameraTelemetry:
        """Return the latest device temperature and focus telemetry."""
        ...

    @property
    def capabilities(self) -> CameraCapabilities:
        """Return runtime-discovered settings and metadata capabilities."""
        ...

    @property
    def stream_info(self) -> CameraStreamInfo | None:
        """Return effective stream dimensions after configuration."""
        ...

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        """Start the encoder and publish complete JPEG frames to the callback."""
        ...

    def reconfigure(self, settings: CameraSettings) -> None:
        """Apply settings or raise without replacing effective settings."""
        ...

    def validate_settings(self, settings: CameraSettings) -> None:
        """Reject unsupported settings without changing device state."""
        ...

    def autofocus(self, timeout_seconds: float) -> bool:
        """Perform one-shot AF and return success; raise on timeout."""
        ...

    def close(self) -> None:
        """Stop the pipeline and release all owned resources."""
        ...
