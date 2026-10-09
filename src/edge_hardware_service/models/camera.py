"""Typed settings, capabilities, and status models for camera services."""

from math import isfinite
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

CameraRotation = Literal[0, 90, 180, 270]
CameraBackend = Literal["simulation", "rpi"]
CameraState = Literal[
    "starting",
    "streaming",
    "reconfiguring",
    "unavailable",
    "stopped",
]
FocusMode = Literal["unmanaged", "manual", "auto", "continuous"]
FocusState = Literal["idle", "scanning", "focused", "failed", "unavailable"]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PixelResolution(_ResponseModel):
    """A complete two-dimensional pixel size."""

    width_px: int = Field(strict=True, ge=1)
    height_px: int = Field(strict=True, ge=1)


class UnmanagedFocus(_RequestModel):
    """Leave focus behavior to the camera provider."""

    mode: Literal["unmanaged"]


class ManualFocus(_RequestModel):
    """Set a fixed lens position, expressed in diopters."""

    mode: Literal["manual"]
    lens_position_diopters: float = Field(ge=0.0, le=32.0)


class AutoFocus(_RequestModel):
    """Configure one-shot automatic focus mode."""

    mode: Literal["auto"]


class ContinuousFocus(_RequestModel):
    """Continuously adjust focus as scene distance changes."""

    mode: Literal["continuous"]


FocusSettings: TypeAlias = Annotated[
    UnmanagedFocus | ManualFocus | AutoFocus | ContinuousFocus,
    Field(discriminator="mode"),
]


class CameraSettings(_ResponseModel):
    """Requested camera policy; nullable fields are provider-managed."""

    fps: float | None = Field(default=None, gt=0)
    sensor_resolution: PixelResolution | None = None
    output_resolution: PixelResolution
    rotation_degrees: CameraRotation
    focus: FocusSettings

    @model_validator(mode="after")
    def validate_output_resolution(self) -> Self:
        """YUV420 output requires even dimensions and finite frame rates."""
        size = self.output_resolution
        if size.width_px % 2 or size.height_px % 2:
            raise ValueError("output resolution dimensions must be even")
        if self.fps is not None and not isfinite(self.fps):
            raise ValueError("fps must be finite")
        return self


class CameraSettingsPatch(_RequestModel):
    """Atomic partial camera settings update."""

    fps: float | None = Field(default=None, gt=0)
    sensor_resolution: PixelResolution | None = None
    output_resolution: PixelResolution | None = None
    rotation_degrees: CameraRotation | None = None
    focus: FocusSettings | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        """Allow null only for provider-managed FPS and sensor selection."""
        if not self.model_fields_set:
            raise ValueError("at least one camera setting must be provided")
        nullable = {"fps", "sensor_resolution"}
        if any(
            getattr(self, field) is None for field in self.model_fields_set - nullable
        ):
            raise ValueError(
                "output_resolution, rotation_degrees, and focus may not be null"
            )
        return self


class CameraTelemetry(_ResponseModel):
    """Current optional metadata reported by a camera adapter."""

    sensor_temperature_c: float | None = None
    focus_state: FocusState | None = None
    lens_position_diopters: float | None = None
    latest_focus_succeeded: bool | None = None


class SensorModeCapability(_ResponseModel):
    """One raw sensor mode advertised by Picamera2."""

    resolution: PixelResolution | None = None
    format: str | None = None
    bit_depth: int | None = Field(default=None, ge=1)
    max_fps: float | None = Field(default=None, gt=0)


class LensPositionCapability(_ResponseModel):
    """Provider-advertised manual lens control range."""

    minimum: float
    maximum: float
    default: float | None = None


class OutputCapability(_ResponseModel):
    """Stable encoded-output contract implemented by the service."""

    default_resolution: PixelResolution
    pixel_format: Literal["YUV420"] = "YUV420"
    encoding: Literal["MJPEG"] = "MJPEG"
    width_multiple: Literal[2] = 2
    height_multiple: Literal[2] = 2
    exact_resolution_required: Literal[True] = True


class FocusCapability(_ResponseModel):
    """Focus operations supported by the active provider."""

    modes: tuple[FocusMode, ...]
    lens_position_diopters: LensPositionCapability | None = None


class MetadataCapability(_ResponseModel):
    """Metadata keys observed in completed camera requests."""

    sensor_temperature_c: bool = False
    focus_state: bool = False
    lens_position_diopters: bool = False


class CameraCapabilities(_ResponseModel):
    """Runtime-discovered capabilities for the active camera."""

    backend: CameraBackend
    device_index: int | None = None
    device_model: str | None = None
    discovery_warnings: tuple[str, ...] = ()
    sensor_modes: tuple[SensorModeCapability, ...] = ()
    output: OutputCapability
    frame_rate_control: bool
    focus: FocusCapability
    rotation_degrees: tuple[CameraRotation, ...] = (0, 90, 180, 270)
    observed_metadata: MetadataCapability = MetadataCapability()


class CameraStreamInfo(_ResponseModel):
    """Effective physical and encoded stream dimensions."""

    sensor_resolution: PixelResolution | None = None
    output_resolution: PixelResolution
    media_type: Literal["multipart/x-mixed-replace; boundary=frame"] = (
        "multipart/x-mixed-replace; boundary=frame"
    )


class CameraStatus(_ResponseModel):
    """Consolidated camera availability, configuration, and telemetry."""

    backend: CameraBackend
    state: CameraState
    device_index: int | None = None
    device_model: str | None = None
    settings: CameraSettings | None
    stream: CameraStreamInfo | None
    sensor_temperature_c: float | None = None
    focus_state: FocusState | None = None
    latest_focus_succeeded: bool | None = None
    lens_position_diopters: float | None = None
    unavailable_reason: str | None = None


class AutofocusResult(_ResponseModel):
    """Result of a synchronous one-shot autofocus request."""

    success: bool
    focus_state: FocusState | None = None
    lens_position_diopters: float | None = None


DEFAULT_OUTPUT_RESOLUTION = PixelResolution(width_px=1280, height_px=720)
DEFAULT_CAMERA_SETTINGS = CameraSettings(
    fps=None,
    sensor_resolution=None,
    output_resolution=DEFAULT_OUTPUT_RESOLUTION,
    rotation_degrees=0,
    focus=UnmanagedFocus(mode="unmanaged"),
)
