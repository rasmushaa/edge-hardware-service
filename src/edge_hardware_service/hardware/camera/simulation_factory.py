"""Portable camera adapter that loops the packaged MJPEG sample clip."""

from collections.abc import Callable
from importlib.resources import files
from threading import Event, RLock, Thread, current_thread
from time import monotonic

from edge_hardware_service.errors import (
    HardwareUnavailableError,
    InvalidRequestError,
)
from edge_hardware_service.hardware.camera.jpeg import jpeg_dimensions
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
    SensorModeCapability,
)

SIMULATION_CLIP_RESOURCE = "assets/camera-simulation.mjpeg"


class SimulationCameraDevice:
    """Loop the packaged raw MJPEG clip at the configured frame rate."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._settings: CameraSettings | None = None
        self._frames: tuple[bytes, ...] = ()
        self._publish_frame: Callable[[bytes], None] | None = None
        self._stop = Event()
        self._thread: Thread | None = None
        self._closed = False
        self._telemetry = CameraTelemetry(sensor_temperature_c=25.0)
        self._capabilities = CameraCapabilities(
            backend="simulation",
            device_model="simulation",
            sensor_modes=(
                SensorModeCapability(
                    resolution=DEFAULT_OUTPUT_RESOLUTION,
                    format="simulation-mjpeg",
                    bit_depth=8,
                    max_fps=56.0,
                ),
            ),
            output=OutputCapability(default_resolution=DEFAULT_OUTPUT_RESOLUTION),
            frame_rate_control=True,
            focus=FocusCapability(
                modes=("unmanaged", "manual", "auto", "continuous"),
                lens_position_diopters=LensPositionCapability(
                    minimum=0.0,
                    maximum=32.0,
                    default=3.0,
                ),
            ),
            observed_metadata=MetadataCapability(sensor_temperature_c=True),
        )
        self._stream_info: CameraStreamInfo | None = None

    @property
    def device_index(self) -> int | None:
        return None

    @property
    def device_model(self) -> str | None:
        return "simulation"

    @property
    def telemetry(self) -> CameraTelemetry:
        with self._lock:
            return self._telemetry

    @property
    def capabilities(self) -> CameraCapabilities:
        with self._lock:
            return self._capabilities

    @property
    def stream_info(self) -> CameraStreamInfo | None:
        with self._lock:
            return self._stream_info

    def validate_settings(self, settings: CameraSettings) -> None:
        if settings.output_resolution != DEFAULT_OUTPUT_RESOLUTION:
            raise InvalidRequestError(
                "The simulation camera supports 1280x720 output only",
                details={
                    "component": "camera",
                    "operation": "validate settings",
                },
            )

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        """Load packaged frames and start the single looping producer thread."""
        with self._lock:
            if self._thread is not None:
                raise HardwareUnavailableError(
                    "Simulation camera is already started",
                    details={"component": "camera", "operation": "start camera"},
                )
            self.validate_settings(settings)
            try:
                raw_clip = (
                    files("edge_hardware_service.hardware.camera")
                    .joinpath(SIMULATION_CLIP_RESOURCE)
                    .read_bytes()
                )
                self._frames = _split_mjpeg(raw_clip)
            except (FileNotFoundError, OSError, ValueError) as error:
                raise HardwareUnavailableError(
                    f"Could not load packaged simulation MJPEG clip: {error}",
                    details={"component": "camera", "operation": "start camera"},
                ) from error
            self._settings = settings
            self._publish_frame = publish_frame
            self._closed = False
            self._stop.clear()
            self._set_focus_telemetry(settings)
            self._stream_info = CameraStreamInfo(
                sensor_resolution=DEFAULT_OUTPUT_RESOLUTION,
                output_resolution=DEFAULT_OUTPUT_RESOLUTION,
            )
            self._thread = Thread(
                target=self._run,
                name="simulation-camera",
                daemon=True,
            )
            self._thread.start()

    def reconfigure(self, settings: CameraSettings) -> None:
        """Update the simulated controls without interrupting the frame loop."""
        with self._lock:
            if self._closed or self._thread is None:
                raise HardwareUnavailableError(
                    "Simulation camera is not started",
                    details={
                        "component": "camera",
                        "operation": "update settings",
                    },
                )
            self.validate_settings(settings)
            self._settings = settings
            self._set_focus_telemetry(settings)

    def autofocus(self, timeout_seconds: float) -> bool:
        """Return deterministic successful one-shot autofocus in auto mode."""
        del timeout_seconds
        with self._lock:
            if self._closed or self._settings is None:
                raise HardwareUnavailableError(
                    "Simulation camera is not started",
                    details={"component": "camera", "operation": "autofocus"},
                )
            if self._settings.focus.mode != "auto":
                raise InvalidRequestError(
                    "One-shot autofocus requires auto mode",
                    details={"component": "camera", "operation": "autofocus"},
                )
            self._telemetry = CameraTelemetry(
                sensor_temperature_c=25.0,
                focus_state="focused",
                latest_focus_succeeded=True,
                lens_position_diopters=3.0,
            )
            return True

    def close(self) -> None:
        """Stop and join the producer thread exactly once."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._stop.set()
            thread = self._thread
            self._thread = None
            self._stream_info = None
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)

    def _run(self) -> None:
        frame_index = 0
        deadline = monotonic()
        while not self._stop.is_set():
            with self._lock:
                settings = self._settings
                frames = self._frames
                publish_frame = self._publish_frame
            if settings is None or publish_frame is None or not frames:
                return
            publish_frame(frames[frame_index % len(frames)])
            frame_index += 1
            deadline += 1.0 / (settings.fps or 30.0)
            self._stop.wait(max(0.0, deadline - monotonic()))

    def _set_focus_telemetry(self, settings: CameraSettings) -> None:
        if settings.focus.mode == "unmanaged":
            self._telemetry = CameraTelemetry(sensor_temperature_c=25.0)
        elif settings.focus.mode == "manual":
            self._telemetry = CameraTelemetry(
                sensor_temperature_c=25.0,
                focus_state="idle",
                lens_position_diopters=settings.focus.lens_position_diopters,
            )
        elif settings.focus.mode == "continuous":
            self._telemetry = CameraTelemetry(
                sensor_temperature_c=25.0,
                focus_state="focused",
                latest_focus_succeeded=True,
                lens_position_diopters=3.0,
            )
        else:
            self._telemetry = CameraTelemetry(
                sensor_temperature_c=25.0,
                focus_state="idle",
                lens_position_diopters=3.0,
            )
        observed = self._capabilities.observed_metadata
        self._capabilities = self._capabilities.model_copy(
            update={
                "observed_metadata": MetadataCapability(
                    sensor_temperature_c=True,
                    focus_state=(
                        observed.focus_state or settings.focus.mode != "unmanaged"
                    ),
                    lens_position_diopters=(
                        observed.lens_position_diopters
                        or settings.focus.mode != "unmanaged"
                    ),
                )
            }
        )


def _split_mjpeg(clip: bytes) -> tuple[bytes, ...]:
    """Split concatenated JPEGs and validate the encoded output dimensions."""
    frames: list[bytes] = []
    start = 0
    while True:
        end = clip.find(b"\xff\xd9", start)
        if end < 0:
            break
        jpeg = clip[start : end + 2]
        if not jpeg.startswith(b"\xff\xd8"):
            raise ValueError("raw MJPEG clip contains an invalid JPEG frame")
        if jpeg_dimensions(jpeg) != (1280, 720):
            raise ValueError("simulation JPEG frames must be 1280x720")
        frames.append(jpeg)
        start = end + 2
    if start != len(clip) or not frames:
        raise ValueError("simulation clip must contain one or more complete JPEGs")
    return tuple(frames)
