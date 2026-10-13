"""Capability-driven Picamera2 camera adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from io import BufferedIOBase
from logging import getLogger
from threading import Condition, RLock
from time import monotonic
from typing import Any

from edge_hardware_service.errors import (
    HardwareUnavailableError,
    InvalidRequestError,
    OperationTimeoutError,
)
from edge_hardware_service.models.camera import (
    DEFAULT_OUTPUT_RESOLUTION,
    CameraCapabilities,
    CameraSettings,
    CameraStreamInfo,
    CameraTelemetry,
    FocusCapability,
    LensPositionCapability,
    MetadataCapability,
    OutputCapability,
    PixelResolution,
)

logger = getLogger(__name__)

DEFAULT_FOCUS_TIMEOUT_SECONDS = 10.0


def _camera_hardware_error(
    message: str,
    operation: str,
) -> HardwareUnavailableError:
    """Build a camera provider failure with consistent structured context."""
    return HardwareUnavailableError(
        message,
        details={"component": "camera", "operation": operation},
    )


def _camera_invalid_request(
    message: str,
    operation: str = "validate settings",
) -> InvalidRequestError:
    """Build a rejected camera request with consistent structured context."""
    return InvalidRequestError(
        message,
        details={"component": "camera", "operation": operation},
    )


class _JpegOutput(BufferedIOBase):
    """File-like sink called by Picamera2's MJPEG encoder output thread."""

    def __init__(self, callback: Callable[[bytes], None]) -> None:
        super().__init__()
        self._callback = callback

    def writable(self) -> bool:
        return True

    def write(self, data: bytes) -> int:
        if data:
            self._callback(bytes(data))
        return len(data)

    def flush(self) -> None:
        return None


class Picamera2Device:
    """Own one selected camera and publish one continuous MJPEG stream."""

    def __init__(self, device_index: int = 0) -> None:
        if isinstance(device_index, bool) or not isinstance(device_index, int):
            raise TypeError("device_index must be an integer")
        if device_index < 0:
            raise ValueError("device_index must be non-negative")
        try:
            from libcamera import controls
            from picamera2 import Picamera2
            from picamera2.encoders import MJPEGEncoder
            from picamera2.outputs import FileOutput
        except (ImportError, OSError) as error:
            raise _camera_hardware_error(
                "Picamera2/libcamera is unavailable",
                "initialize camera",
            ) from error

        self._controls = controls
        self._encoder_type = MJPEGEncoder
        self._file_output_type = FileOutput
        self._device_index = device_index
        self._camera: Any | None = None
        self._encoder: Any | None = None
        self._output: _JpegOutput | None = None
        self._publish_frame: Callable[[bytes], None] | None = None
        self._settings: CameraSettings | None = None
        self._stream_info: CameraStreamInfo | None = None
        self._closed = False
        self._running = False
        self._lock = RLock()
        self._metadata_condition = Condition(self._lock)
        self._focus_scan_active = False
        self._focus_scan_seen = False
        self._telemetry = CameraTelemetry()

        try:
            camera = Picamera2(camera_num=device_index)
        except Exception as error:
            raise _camera_hardware_error(
                self._initialization_error("open", device_index, error),
                "initialize camera",
            ) from error

        self._camera = camera
        try:
            self._device_model = self._get_device_model(camera)
            self._camera_controls = dict(getattr(camera, "camera_controls", {}))
            self._capabilities = self._build_capabilities()
        except Exception as error:
            active_camera = self._camera
            self._camera = None
            if active_camera is not None:
                try:
                    active_camera.close()
                except Exception:
                    pass
            raise _camera_hardware_error(
                self._initialization_error(
                    "discover capabilities for", device_index, error
                ),
                "discover capabilities",
            ) from error

    @property
    def device_index(self) -> int:
        return self._device_index

    @property
    def device_model(self) -> str:
        return self._device_model

    @property
    def model(self) -> str:
        return self._device_model

    @property
    def telemetry(self) -> CameraTelemetry:
        with self._lock:
            return self._telemetry

    @property
    def metadata(self) -> CameraTelemetry:
        return self.telemetry

    @property
    def capabilities(self) -> CameraCapabilities:
        with self._lock:
            return self._capabilities

    @property
    def stream_info(self) -> CameraStreamInfo | None:
        with self._lock:
            return self._stream_info

    @property
    def lens_position_range(self) -> tuple[float, float] | None:
        lens = self._capabilities.focus.lens_position_diopters
        if lens is None:
            return None
        return lens.minimum, lens.maximum

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        with self._lock:
            if self._closed:
                raise _camera_hardware_error(
                    "Camera has been closed",
                    "start camera",
                )
            if self._running:
                return
            self.validate_settings(settings)
            self._publish_frame = publish_frame
            self._configure_and_start(settings)

    def validate_settings(self, settings: CameraSettings) -> None:
        """Reject unsupported settings without touching the camera."""
        if settings.fps is not None and not self._capabilities.frame_rate_control:
            raise _camera_invalid_request(
                "The active camera does not support frame-rate control"
            )

        focus_mode = settings.focus.mode
        if focus_mode not in self._capabilities.focus.modes:
            raise _camera_invalid_request(
                f"The active camera does not support focus mode {focus_mode!r}"
            )
        if focus_mode == "manual":
            lens = self._capabilities.focus.lens_position_diopters
            if lens is None:
                raise _camera_invalid_request(
                    "The active camera does not support manual lens positioning"
                )
            position = settings.focus.lens_position_diopters
            if not lens.minimum <= position <= lens.maximum:
                raise _camera_invalid_request(
                    "lens_position_diopters must be within the camera's "
                    f"advertised range [{lens.minimum}, {lens.maximum}]"
                )

    def reconfigure(self, settings: CameraSettings) -> None:
        """Apply settings live when safe, otherwise restart the pipeline."""
        with self._lock:
            if self._closed or self._camera is None:
                raise _camera_hardware_error(
                    "Camera is not open",
                    "update settings",
                )
            self.validate_settings(settings)
            if not self._running or self._settings is None:
                self._configure_and_start(settings)
                return

            previous = self._settings
            restart = (
                settings.sensor_resolution != previous.sensor_resolution
                or settings.output_resolution != previous.output_resolution
                or (previous.fps is not None and settings.fps is None)
                or (
                    previous.focus.mode != "unmanaged"
                    and settings.focus.mode == "unmanaged"
                )
            )
            if not restart:
                self._apply_live_controls(settings)
                self._settings = settings
                return

            self._stop_recording()
            try:
                self._configure_and_start(settings)
            except InvalidRequestError:
                raise
            except Exception as error:
                raise self._translate_error("reconfigure camera", error) from error

    def apply_settings(self, settings: CameraSettings) -> None:
        self.reconfigure(settings)

    def autofocus(
        self,
        timeout_seconds: float = DEFAULT_FOCUS_TIMEOUT_SECONDS,
    ) -> bool:
        """Trigger autofocus and wait for terminal autofocus metadata."""
        with self._metadata_condition:
            self._ensure_running()
            if "auto" not in self._capabilities.focus.modes:
                raise _camera_invalid_request(
                    "The active camera does not support autofocus",
                    "autofocus",
                )
            if timeout_seconds <= 0:
                raise ValueError("timeout_seconds must be positive")
            self._focus_scan_active = True
            self._focus_scan_seen = False
            try:
                self._camera.set_controls(
                    {
                        "AfMode": self._controls.AfModeEnum.Auto,
                        "AfTrigger": self._controls.AfTriggerEnum.Start,
                    }
                )
            except Exception as error:
                self._focus_scan_active = False
                raise self._translate_error("start autofocus", error) from error

            deadline = monotonic() + timeout_seconds
            while self._focus_scan_active:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    try:
                        self._camera.set_controls(
                            {"AfTrigger": self._controls.AfTriggerEnum.Cancel}
                        )
                    except Exception as error:
                        self._focus_scan_active = False
                        raise self._translate_error(
                            "cancel autofocus", error
                        ) from error
                    self._focus_scan_active = False
                    self._focus_scan_seen = False
                    self._telemetry = self._telemetry.model_copy(
                        update={
                            "focus_state": "failed",
                            "latest_focus_succeeded": False,
                        }
                    )
                    raise OperationTimeoutError(
                        "Camera autofocus did not finish in time",
                        details={
                            "component": "camera",
                            "operation": "autofocus",
                        },
                    )
                self._metadata_condition.wait(remaining)
            return self._telemetry.latest_focus_succeeded is True

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            error: Exception | None = None
            try:
                self._stop_recording()
            except Exception as failure:
                error = failure
            camera, self._camera = self._camera, None
            if camera is not None:
                try:
                    camera.close()
                except Exception as failure:
                    error = error or failure
            self._stream_info = None
            self._telemetry = CameraTelemetry(focus_state="unavailable")
            if error is not None:
                raise self._translate_error("close camera", error) from error

    def _configure_and_start(self, settings: CameraSettings) -> None:
        camera = self._camera
        if camera is None:
            raise _camera_hardware_error("Camera is not open", "start camera stream")
        output_size = self._resolution_tuple(settings.output_resolution)
        kwargs: dict[str, Any] = {
            "main": {"size": output_size, "format": "YUV420"},
            "buffer_count": 4,
        }
        controls = self._controls_for(settings)
        if controls:
            kwargs["controls"] = controls
        if settings.sensor_resolution is not None:
            kwargs["sensor"] = {
                "output_size": self._resolution_tuple(settings.sensor_resolution)
            }

        try:
            configuration = camera.create_video_configuration(**kwargs)
            self._assert_exact_output(configuration, output_size)
            camera.configure(configuration)
            applied = self._applied_configuration(camera, configuration)
            self._assert_exact_output(applied, output_size)
            camera.post_callback = self._on_metadata
            self._encoder = self._encoder_type()
            sink = _JpegOutput(self._publish_encoded_frame)
            self._output = self._file_output_type(sink)
            camera.start_recording(self._encoder, self._output)
            self._stream_info = CameraStreamInfo(
                sensor_resolution=self._effective_sensor_resolution(applied),
                output_resolution=settings.output_resolution,
            )
            self._settings = settings
            self._running = True
        except InvalidRequestError:
            self._running = False
            raise
        except Exception as error:
            self._running = False
            raise self._translate_error("start camera stream", error) from error

    def _stop_recording(self) -> None:
        if not self._running:
            return
        camera = self._camera
        self._running = False
        self._encoder = None
        self._output = None
        self._stream_info = None
        if camera is not None:
            camera.stop_recording()

    def _build_capabilities(self) -> CameraCapabilities:
        modes: list[str] = ["unmanaged"]
        lens = self._lens_capability()
        if lens is not None and self._af_mode_supported("Manual"):
            modes.append("manual")
        if self._af_mode_supported("Auto") and "AfTrigger" in self._camera_controls:
            modes.append("auto")
        if self._af_mode_supported("Continuous"):
            modes.append("continuous")
        return CameraCapabilities(
            backend="rpi",
            device_index=self._device_index,
            device_model=self._device_model,
            output=OutputCapability(default_resolution=DEFAULT_OUTPUT_RESOLUTION),
            frame_rate_control="FrameDurationLimits" in self._camera_controls,
            focus=FocusCapability(
                modes=tuple(modes),  # type: ignore[arg-type]
                lens_position_diopters=lens,
            ),
        )

    def _lens_capability(self) -> LensPositionCapability | None:
        advertised = self._camera_controls.get("LensPosition")
        if not isinstance(advertised, Sequence) or len(advertised) < 2:
            return None
        default = advertised[2] if len(advertised) >= 3 else None
        return LensPositionCapability(
            minimum=float(advertised[0]),
            maximum=float(advertised[1]),
            default=None if default is None else float(default),
        )

    def _af_mode_supported(self, name: str) -> bool:
        advertised = self._camera_controls.get("AfMode")
        enum_type = getattr(self._controls, "AfModeEnum", None)
        requested = getattr(enum_type, name, None)
        if advertised is None or requested is None:
            return False
        if not isinstance(advertised, Sequence) or len(advertised) < 2:
            return True
        minimum = self._enum_value(advertised[0])
        maximum = self._enum_value(advertised[1])
        value = self._enum_value(requested)
        try:
            return minimum <= value <= maximum
        except TypeError:
            return True

    def _controls_for(self, settings: CameraSettings) -> dict[str, Any]:
        controls: dict[str, Any] = {}
        if settings.fps is not None:
            duration = round(1_000_000 / settings.fps)
            controls["FrameDurationLimits"] = (duration, duration)

        focus = settings.focus
        if focus.mode == "manual":
            controls["AfMode"] = self._controls.AfModeEnum.Manual
            controls["LensPosition"] = float(focus.lens_position_diopters)
        elif focus.mode == "auto":
            controls["AfMode"] = self._controls.AfModeEnum.Auto
        elif focus.mode == "continuous":
            controls["AfMode"] = self._controls.AfModeEnum.Continuous
        return controls

    def _apply_live_controls(self, settings: CameraSettings) -> None:
        camera = self._camera
        if camera is None:
            raise _camera_hardware_error("Camera is not open", "apply controls")
        controls = self._controls_for(settings)
        if not controls:
            return
        try:
            camera.set_controls(controls)
        except Exception as error:
            raise self._translate_error("apply camera controls", error) from error

    @staticmethod
    def _assert_exact_output(configuration: Any, requested: tuple[int, int]) -> None:
        try:
            actual = tuple(configuration["main"]["size"])
        except (KeyError, TypeError, AttributeError):
            return
        if actual != requested:
            raise _camera_invalid_request(
                f"Requested output resolution {requested[0]}x{requested[1]} "
                f"was adjusted to {actual[0]}x{actual[1]}"
            )

    @staticmethod
    def _applied_configuration(camera: Any, fallback: Any) -> Any:
        getter = getattr(camera, "camera_configuration", None)
        if callable(getter):
            return getter()
        return fallback

    @staticmethod
    def _effective_sensor_resolution(
        configuration: Any,
    ) -> PixelResolution | None:
        try:
            raw = configuration.get("raw") or {}
            sensor = configuration.get("sensor") or {}
        except AttributeError:
            return None
        # The validated raw stream is the strongest evidence of the sensor mode
        # that libcamera actually selected. Some Picamera2 versions may retain
        # the requested best-match hint in the sensor configuration.
        possible = [raw.get("size"), sensor.get("output_size")]
        for raw_size in possible:
            if isinstance(raw_size, Sequence) and len(raw_size) == 2:
                try:
                    width, height = int(raw_size[0]), int(raw_size[1])
                except (TypeError, ValueError):
                    continue
                if width < 1 or height < 1:
                    continue
                return PixelResolution(
                    width_px=width,
                    height_px=height,
                )
        return None

    def _publish_encoded_frame(self, frame: bytes) -> None:
        callback = self._publish_frame
        if callback is None or not frame:
            return
        try:
            callback(frame)
        except Exception:
            logger.exception("camera frame publication failed")

    def _on_metadata(self, request: Any) -> None:
        try:
            metadata = request.get_metadata()
        except Exception:
            logger.debug("could not read camera frame metadata", exc_info=True)
            return
        temperature = metadata.get("SensorTemperature")
        lens_position = metadata.get("LensPosition")
        raw_af_state = metadata.get("AfState")
        focus_state = (
            self._normalize_af_state(raw_af_state) if "AfState" in metadata else None
        )
        with self._metadata_condition:
            if self._focus_scan_active and focus_state == "scanning":
                self._focus_scan_seen = True
            latest_success = self._telemetry.latest_focus_succeeded
            if focus_state in {"focused", "failed"}:
                latest_success = focus_state == "focused"
            if (
                self._focus_scan_active
                and self._focus_scan_seen
                and focus_state in {"focused", "failed"}
            ):
                self._focus_scan_active = False
                self._focus_scan_seen = False
            self._telemetry = CameraTelemetry(
                sensor_temperature_c=(
                    float(temperature) if temperature is not None else None
                ),
                focus_state=focus_state,
                lens_position_diopters=(
                    float(lens_position) if lens_position is not None else None
                ),
                latest_focus_succeeded=latest_success,
            )
            observed = self._capabilities.observed_metadata
            self._capabilities = self._capabilities.model_copy(
                update={
                    "observed_metadata": MetadataCapability(
                        sensor_temperature_c=(
                            observed.sensor_temperature_c
                            or "SensorTemperature" in metadata
                        ),
                        focus_state=observed.focus_state or "AfState" in metadata,
                        lens_position_diopters=(
                            observed.lens_position_diopters
                            or "LensPosition" in metadata
                        ),
                    )
                }
            )
            self._metadata_condition.notify_all()

    @staticmethod
    def _get_device_model(camera: Any) -> str:
        properties: Mapping[str, Any] = getattr(camera, "camera_properties", {})
        model = properties.get("Model") or properties.get("model")
        return str(model) if model else "unknown"

    @staticmethod
    def _normalize_af_state(value: Any) -> str:
        value = getattr(value, "value", value)
        if isinstance(value, str):
            normalized = value.lower()
            if "scan" in normalized:
                return "scanning"
            if "focus" in normalized and "not" not in normalized:
                return "focused"
            if "fail" in normalized:
                return "failed"
            if "idle" in normalized:
                return "idle"
        try:
            return {0: "idle", 1: "scanning", 2: "focused", 3: "failed"}[int(value)]
        except (TypeError, ValueError, KeyError):
            return "unavailable"

    def _ensure_running(self) -> None:
        if self._closed:
            raise _camera_hardware_error("Camera has been closed", "access camera")
        if not self._running or self._camera is None:
            raise _camera_hardware_error(
                "Camera stream is not running",
                "access camera",
            )

    @staticmethod
    def _resolution_tuple(resolution: PixelResolution) -> tuple[int, int]:
        return resolution.width_px, resolution.height_px

    @staticmethod
    def _enum_value(value: Any) -> Any:
        return getattr(value, "value", value)

    @staticmethod
    def _initialization_error(
        operation: str, device_index: int, error: Exception
    ) -> str:
        reason = str(error).strip() or "no additional detail"
        return (
            f"could not {operation} camera index {device_index}: "
            f"{type(error).__name__}: {reason}"
        )

    @staticmethod
    def _translate_error(
        operation: str,
        error: Exception,
    ) -> HardwareUnavailableError:
        if isinstance(error, HardwareUnavailableError):
            return error
        return _camera_hardware_error(
            f"Camera operation {operation!r} failed: {error}",
            operation,
        )
