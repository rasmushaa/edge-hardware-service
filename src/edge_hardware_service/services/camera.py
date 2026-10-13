"""Camera lifecycle policy and a process-local latest-frame broker."""

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Condition, Event, RLock
from time import monotonic

from pydantic import ValidationError

from edge_hardware_service.errors import (
    CameraNotConnectedError,
    ConflictError,
    HardwareUnavailableError,
    InvalidRequestError,
    OperationTimeoutError,
)
from edge_hardware_service.hardware.camera.jpeg import (
    jpeg_dimensions,
    set_exif_orientation,
)
from edge_hardware_service.hardware.camera.protocols import (
    CameraDevice,
    CameraDeviceFactory,
)
from edge_hardware_service.models.camera import (
    DEFAULT_CAMERA_SETTINGS,
    AutoFocus,
    AutofocusResult,
    CameraBackend,
    CameraCapabilities,
    CameraSettings,
    CameraSettingsPatch,
    CameraState,
    CameraStatus,
    CameraTelemetry,
)

FRAME_WAIT_TIMEOUT_SECONDS = 2.0
AUTOFOCUS_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """One complete JPEG frame and its broker sequence/timestamp."""

    jpeg: bytes
    sequence: int
    captured_at: datetime
    width: int
    height: int


class LatestFrameBroker:
    """Publish complete frames and wake consumers without per-client queues."""

    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._latest: CameraFrame | None = None
        self._sequence = 0
        self._closed = False

    @property
    def latest(self) -> CameraFrame | None:
        """Return the current immutable frame snapshot, if one exists."""
        with self._condition:
            return self._latest

    def publish(self, jpeg: bytes) -> CameraFrame:
        """Atomically replace the latest frame and notify all consumers."""
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise ValueError("camera frame must be a complete JPEG image")
        width, height = jpeg_dimensions(jpeg)
        with self._condition:
            if self._closed:
                raise ValueError("camera frame broker is closed")
            self._sequence += 1
            self._latest = CameraFrame(
                jpeg=jpeg,
                sequence=self._sequence,
                captured_at=datetime.now(UTC),
                width=width,
                height=height,
            )
            self._condition.notify_all()
            return self._latest

    def wait_for_frame(
        self,
        timeout_seconds: float = FRAME_WAIT_TIMEOUT_SECONDS,
        *,
        after_sequence: int = 0,
    ) -> CameraFrame | None:
        """Wait for a frame newer than `after_sequence` until the deadline."""
        deadline = monotonic() + timeout_seconds
        with self._condition:
            while self._latest is None or self._latest.sequence <= after_sequence:
                if self._closed:
                    return None
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest

    def clear_latest(self) -> int:
        """Discard buffered frames and return the last sequence number."""
        with self._condition:
            self._latest = None
            return self._sequence

    def close(self) -> None:
        """Discard the buffered frame and wake all waiting consumers."""
        with self._condition:
            self._closed = True
            self._latest = None
            self._condition.notify_all()


class CameraService:
    """Own camera settings, lifecycle, focus operations, and frame delivery."""

    def __init__(
        self,
        device_factory: CameraDeviceFactory,
        backend: CameraBackend,
        device_index: int = 0,
        settings: CameraSettings = DEFAULT_CAMERA_SETTINGS,
    ) -> None:
        self._device_factory = device_factory
        self._backend = backend
        self._device: CameraDevice | None = None
        self._settings: CameraSettings | None = settings
        self._device_index = device_index
        self._frames = LatestFrameBroker()
        self._lock = RLock()
        self._state: CameraState = "starting"
        self._unavailable_reason: str | None = None
        self._reconnect_used_defaults = False
        self._closed = False
        self._accept_frames = Event()
        self._generation = 0
        try:
            self._start_new_device(device_index, settings, "starting")
        except Exception:
            # Camera failure is an independently degraded application state.
            # Status and reconnect remain available without failing app startup.
            pass

    @property
    def frames(self) -> LatestFrameBroker:
        """Return the shared broker used by stream and image routes."""
        return self._frames

    @property
    def settings(self) -> CameraSettings | None:
        """Return desired settings, or null after intentional release."""
        with self._lock:
            return self._settings

    def status(self) -> CameraStatus:
        """Return one snapshot of runtime state and device telemetry."""
        # Read immutable/reference-valued fields without the operation lock so
        # clients can observe the deliberate `reconfiguring` state while a
        # PATCH waits for the first frame from a new configuration.
        state = self._state
        settings = self._settings
        telemetry = self._read_telemetry()
        return CameraStatus(
            backend=self._backend,
            state=state,
            device_index=(
                None
                if state in {"disconnected", "stopped"}
                else self._safe_device_attribute("device_index") or self._device_index
            ),
            device_model=self._safe_device_attribute("device_model"),
            settings=None if state in {"disconnected", "stopped"} else settings,
            stream=(
                self._safe_device_attribute("stream_info")
                if state == "streaming"
                else None
            ),
            sensor_temperature_c=telemetry.sensor_temperature_c,
            focus_state=telemetry.focus_state,
            latest_focus_succeeded=telemetry.latest_focus_succeeded,
            lens_position_diopters=telemetry.lens_position_diopters,
            unavailable_reason=self._unavailable_reason,
            reconnect_used_defaults=self._reconnect_used_defaults,
        )

    def capabilities(self) -> CameraCapabilities:
        """Return capabilities for the active camera or its startup failure."""
        with self._lock:
            self._require_streaming()
            capabilities = self._safe_device_attribute("capabilities")
            if not isinstance(capabilities, CameraCapabilities):
                raise HardwareUnavailableError(
                    "Camera capabilities are unavailable",
                    details={
                        "component": "camera",
                        "operation": "inspect capabilities",
                    },
                )
            return capabilities

    def update_settings(self, patch: CameraSettingsPatch) -> CameraSettings:
        """Apply a partial update transactionally, rolling back on failure."""
        with self._lock:
            self._require_streaming()
            current = self._settings
            assert current is not None
            merged = current.model_dump()
            for field in patch.model_fields_set:
                merged[field] = getattr(patch, field)
            try:
                candidate = CameraSettings.model_validate(merged)
            except ValidationError as error:
                raise InvalidRequestError(
                    str(error),
                    details={
                        "component": "camera",
                        "operation": "update settings",
                    },
                ) from error
            return self._apply_settings(candidate)

    def reset_settings(self) -> CameraSettings:
        """Atomically restore the connected camera's complete default settings."""
        with self._lock:
            self._require_streaming()
            return self._apply_settings(DEFAULT_CAMERA_SETTINGS)

    def release(self) -> None:
        """Intentionally release camera ownership and end active streams."""
        with self._lock:
            if self._state == "disconnected":
                return
            self._require_service_open()
            self._settings = None
            self._state = "disconnected"
            self._unavailable_reason = None
            self._reconnect_used_defaults = False
            close_error = self._discard_current_device()
            if close_error is not None:
                raise HardwareUnavailableError(
                    f"Camera was released, but provider close failed: {close_error}",
                    details={"component": "camera", "operation": "release camera"},
                ) from close_error

    def connect(self, device_index: int = 0) -> CameraStatus:
        """Create a fresh camera with defaults after intentional release."""
        with self._lock:
            self._require_service_open()
            if self._state != "disconnected":
                raise ConflictError(
                    "Release the current camera before connecting another one",
                    details={
                        "component": "camera",
                        "operation": "connect camera",
                        "state": self._state,
                    },
                )
            self._reconnect_used_defaults = False
            try:
                self._start_new_device(
                    device_index, DEFAULT_CAMERA_SETTINGS, "starting"
                )
            except Exception as error:
                raise self._connection_error("connect camera", error) from error
            return self.status()

    def reconnect(self) -> CameraStatus:
        """Replace the adapter, preserving desired settings when supported."""
        with self._lock:
            self._require_service_open()
            if self._state == "disconnected":
                raise self._not_connected("reconnect camera")
            if self._state not in {"streaming", "unavailable"}:
                raise ConflictError(
                    f"Camera cannot reconnect while state is {self._state!r}",
                    details={
                        "component": "camera",
                        "operation": "reconnect camera",
                        "state": self._state,
                    },
                )

            desired = self._settings or DEFAULT_CAMERA_SETTINGS
            close_error = self._discard_current_device()
            if close_error is not None:
                self._state = "unavailable"
                self._settings = desired
                self._unavailable_reason = (
                    f"Could not close previous camera: {close_error}"
                )
                raise self._connection_error(
                    "reconnect camera", close_error
                ) from close_error

            self._reconnect_used_defaults = False
            try:
                self._start_new_device(self._device_index, desired, "reconnecting")
            except InvalidRequestError as saved_settings_error:
                if desired == DEFAULT_CAMERA_SETTINGS:
                    raise self._connection_error(
                        "reconnect camera", saved_settings_error
                    ) from saved_settings_error
                try:
                    self._start_new_device(
                        self._device_index,
                        DEFAULT_CAMERA_SETTINGS,
                        "reconnecting",
                    )
                except Exception as fallback_error:
                    self._settings = desired
                    self._reconnect_used_defaults = False
                    raise self._connection_error(
                        "reconnect camera", fallback_error
                    ) from fallback_error
                self._reconnect_used_defaults = True
            except Exception as error:
                raise self._connection_error("reconnect camera", error) from error
            return self.status()

    def _apply_settings(self, candidate: CameraSettings) -> CameraSettings:
        """Apply one already merged complete configuration transactionally."""
        current = self._settings
        device = self._device
        assert current is not None
        assert device is not None
        device.validate_settings(candidate)

        needs_fresh_frame = (
            candidate.sensor_resolution != current.sensor_resolution
            or candidate.output_resolution != current.output_resolution
            or candidate.rotation_degrees != current.rotation_degrees
            or (current.fps is not None and candidate.fps is None)
            or (
                current.focus.mode != "unmanaged"
                and candidate.focus.mode == "unmanaged"
            )
        )
        self._state = "reconfiguring"
        previous_sequence: int | None = None
        if needs_fresh_frame:
            self._accept_frames.clear()
            previous_sequence = self._frames.clear_latest()
        try:
            device.reconfigure(candidate)
        except Exception as error:
            self._restore_previous_settings(current, needs_fresh_frame, error)
            if isinstance(error, InvalidRequestError):
                raise
            raise HardwareUnavailableError(
                f"Camera settings update failed: {error}",
                details={
                    "component": "camera",
                    "operation": "update settings",
                },
            ) from error
        self._settings = candidate
        if needs_fresh_frame:
            self._accept_frames.set()
            frame = self._frames.wait_for_frame(
                FRAME_WAIT_TIMEOUT_SECONDS,
                after_sequence=previous_sequence or 0,
            )
            if frame is None:
                error = HardwareUnavailableError(
                    "No frame arrived after camera reconfiguration",
                    details={
                        "component": "camera",
                        "operation": "update settings",
                    },
                )
                self._restore_previous_settings(current, True, error)
                raise error
        self._state = "streaming"
        self._unavailable_reason = None
        self._reconnect_used_defaults = False
        return candidate

    def autofocus(self) -> AutofocusResult:
        """Run one-shot autofocus with a ten-second deadline in auto mode."""
        with self._lock:
            self._require_streaming()
            if "auto" not in self.capabilities().focus.modes:
                raise InvalidRequestError(
                    "The active camera does not support autofocus",
                    details={
                        "component": "camera",
                        "operation": "autofocus",
                    },
                )
            if self._settings.focus.mode != "auto":
                self.update_settings(CameraSettingsPatch(focus=AutoFocus(mode="auto")))
            try:
                device = self._device
                assert device is not None
                success = device.autofocus(AUTOFOCUS_TIMEOUT_SECONDS)
            except OperationTimeoutError:
                raise
            except TimeoutError as error:
                raise OperationTimeoutError(
                    "Autofocus did not complete within 10 seconds",
                    details={
                        "component": "camera",
                        "operation": "autofocus",
                    },
                ) from error
            except Exception as error:
                raise HardwareUnavailableError(
                    f"Autofocus failed: {error}",
                    details={
                        "component": "camera",
                        "operation": "autofocus",
                    },
                ) from error
            telemetry = self._read_telemetry()
            return AutofocusResult(
                success=bool(success),
                focus_state=telemetry.focus_state,
                lens_position_diopters=telemetry.lens_position_diopters,
            )

    def wait_for_frame(
        self,
        timeout_seconds: float = FRAME_WAIT_TIMEOUT_SECONDS,
    ) -> CameraFrame:
        """Wait for the first/current frame or raise the not-ready error."""
        return self.open_frame_source(timeout_seconds)[1]

    def open_frame_source(
        self,
        timeout_seconds: float = FRAME_WAIT_TIMEOUT_SECONDS,
    ) -> tuple[LatestFrameBroker, CameraFrame]:
        """Return one frame and its broker from the same camera generation."""
        with self._lock:
            self._require_streaming()
            broker = self._frames
            frame = broker.wait_for_frame(timeout_seconds)
            if frame is None:
                reason = self._unavailable_reason or "No camera frame is available"
                raise HardwareUnavailableError(
                    reason,
                    details={
                        "component": "camera",
                        "operation": "wait for frame",
                    },
                )
            return broker, frame

    def close(self) -> None:
        """Stop the pipeline and release adapter resources once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._state = "stopped"
            self._settings = None
            error = self._discard_current_device()
            if error is not None:
                raise error

    def _publish_frame(
        self,
        generation: int,
        broker: LatestFrameBroker,
        jpeg: bytes,
    ) -> None:
        """Publish a complete encoded frame from the adapter callback."""
        if (
            generation != self._generation
            or broker is not self._frames
            or not self._accept_frames.is_set()
        ):
            return
        try:
            settings = self._settings
            if settings is None:
                return
            broker.publish(set_exif_orientation(jpeg, settings.rotation_degrees))
        except ValueError:
            # An invalid or partial encoder callback is never exposed to clients.
            return

    def _require_streaming(self) -> None:
        if self._state == "disconnected":
            raise self._not_connected("access camera")
        if self._state != "streaming":
            reason = self._unavailable_reason or "Camera is not streaming"
            raise HardwareUnavailableError(
                reason,
                details={
                    "component": "camera",
                    "operation": "access camera",
                },
            )

    def _require_service_open(self) -> None:
        if self._closed:
            raise ConflictError(
                "Camera service is stopped",
                details={"component": "camera", "operation": "camera lifecycle"},
            )

    @staticmethod
    def _not_connected(operation: str) -> CameraNotConnectedError:
        return CameraNotConnectedError(
            "Camera is intentionally disconnected",
            details={"component": "camera", "operation": operation},
        )

    def _read_telemetry(self):
        device = self._device
        if device is None:
            return CameraTelemetry()
        try:
            return device.telemetry
        except Exception:
            return CameraTelemetry()

    def _safe_device_attribute(self, name: str):
        device = self._device
        if device is None:
            return None
        try:
            return getattr(device, name)
        except Exception:
            return None

    def _start_new_device(
        self,
        device_index: int,
        settings: CameraSettings,
        transitional_state: CameraState,
    ) -> None:
        """Create one adapter/broker generation and wait for its first frame."""
        previous_broker = self._frames
        broker = LatestFrameBroker()
        self._frames = broker
        previous_broker.close()
        self._generation += 1
        generation = self._generation
        self._accept_frames.set()
        self._state = transitional_state
        self._settings = settings
        self._device_index = device_index
        self._unavailable_reason = None
        device: CameraDevice | None = None
        try:
            device = self._device_factory(device_index)
            self._device = device
            device.start(
                settings,
                lambda jpeg: self._publish_frame(generation, broker, jpeg),
            )
            if broker.wait_for_frame(FRAME_WAIT_TIMEOUT_SECONDS) is None:
                raise HardwareUnavailableError(
                    "No frame arrived after camera start",
                    details={"component": "camera", "operation": "start camera"},
                )
        except Exception as error:
            self._generation += 1
            self._accept_frames.clear()
            broker.close()
            self._device = None
            if device is not None:
                try:
                    device.close()
                except Exception:
                    pass
            self._state = "unavailable"
            self._unavailable_reason = str(error) or type(error).__name__
            raise
        self._state = "streaming"
        self._unavailable_reason = None

    def _discard_current_device(self) -> Exception | None:
        """Invalidate callbacks, end streams, and close the current adapter once."""
        self._generation += 1
        self._accept_frames.clear()
        self._frames.close()
        device, self._device = self._device, None
        if device is None:
            return None
        try:
            device.close()
        except Exception as error:
            return error
        return None

    @staticmethod
    def _connection_error(operation: str, error: Exception) -> HardwareUnavailableError:
        message = str(error) or type(error).__name__
        return HardwareUnavailableError(
            message,
            details={"component": "camera", "operation": operation},
        )

    def _restore_previous_settings(
        self,
        previous: CameraSettings,
        needs_fresh_frame: bool,
        error: Exception,
    ) -> None:
        """Restore the prior complete configuration or degrade the camera."""
        device = self._device
        assert device is not None
        if needs_fresh_frame:
            self._accept_frames.clear()
        try:
            device.reconfigure(previous)
        except Exception as rollback_error:
            self._state = "unavailable"
            self._unavailable_reason = (
                f"Camera settings update and rollback failed: {rollback_error}"
            )
            self._frames.close()
            raise HardwareUnavailableError(
                self._unavailable_reason,
                details={
                    "component": "camera",
                    "operation": "rollback settings",
                },
            ) from error
        self._settings = previous
        if needs_fresh_frame:
            previous_sequence = self._frames.clear_latest()
            self._accept_frames.set()
            restored = self._frames.wait_for_frame(
                FRAME_WAIT_TIMEOUT_SECONDS,
                after_sequence=previous_sequence,
            )
            if restored is None:
                self._state = "unavailable"
                self._unavailable_reason = (
                    "Camera rollback completed but produced no frame"
                )
                self._frames.close()
                raise HardwareUnavailableError(
                    self._unavailable_reason,
                    details={
                        "component": "camera",
                        "operation": "rollback settings",
                    },
                ) from error
        self._state = "streaming"
        self._unavailable_reason = None
