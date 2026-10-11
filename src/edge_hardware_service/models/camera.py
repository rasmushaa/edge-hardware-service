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

    width_px: int = Field(
        strict=True,
        ge=1,
        description="Horizontal pixel count.",
        examples=[640, 1280, 1920, 2304],
    )
    height_px: int = Field(
        strict=True,
        ge=1,
        description="Vertical pixel count.",
        examples=[480, 720, 1080, 1296],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"width_px": 1280, "height_px": 720},
                {"width_px": 2304, "height_px": 1296},
            ]
        }
    )


class UnmanagedFocus(_RequestModel):
    """Leave focus behavior to the camera provider."""

    mode: Literal["unmanaged"] = Field(
        description=(
            "Do not apply focus controls. The provider retains responsibility "
            "for its default focus behavior."
        )
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"mode": "unmanaged"}]})


class ManualFocus(_RequestModel):
    """Set a fixed lens position, expressed in diopters."""

    mode: Literal["manual"] = Field(
        description="Hold the lens at an explicit manual position."
    )
    lens_position_diopters: float = Field(
        ge=0.0,
        le=32.0,
        description=(
            "Requested lens position in diopters. The schema permits 0-32, "
            "but clients must use the narrower range advertised by "
            "camera capabilities when present."
        ),
        examples=[0.0, 2.0, 3.0, 10.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"mode": "manual", "lens_position_diopters": 2.0}]
        }
    )


class AutoFocus(_RequestModel):
    """Select the mode used by an explicit one-shot autofocus request."""

    mode: Literal["auto"] = Field(
        description=(
            "Select one-shot autofocus mode. Setting this value does not run a "
            "scan; POST /api/v1/camera/autofocus triggers it."
        )
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"mode": "auto"}]})


class ContinuousFocus(_RequestModel):
    """Continuously adjust focus as scene distance changes."""

    mode: Literal["continuous"] = Field(
        description="Continuously adjust focus while the camera is streaming."
    )

    model_config = ConfigDict(json_schema_extra={"examples": [{"mode": "continuous"}]})


FocusSettings: TypeAlias = Annotated[
    UnmanagedFocus | ManualFocus | AutoFocus | ContinuousFocus,
    Field(discriminator="mode"),
]


class CameraSettings(_ResponseModel):
    """Requested camera policy; nullable fields are provider-managed."""

    fps: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Requested frames per second. Null means the provider selects its "
            "default. The active camera must advertise frame-rate control."
        ),
        examples=[None, 15.0, 30.0],
    )
    sensor_resolution: PixelResolution | None = Field(
        default=None,
        description=(
            "Requested raw sensor mode. Null lets Picamera2 select a mode; a "
            "non-null value must be advertised by camera capabilities."
        ),
    )
    output_resolution: PixelResolution = Field(
        description=(
            "Exact dimensions of each encoded MJPEG/JPEG frame. Width and "
            "height must both be even."
        )
    )
    rotation_degrees: CameraRotation = Field(
        description=(
            "Clockwise display orientation written to JPEG EXIF metadata. "
            "Encoded width and height do not swap."
        ),
        examples=[0, 90, 180, 270],
    )
    focus: FocusSettings = Field(
        description="Effective focus policy selected from advertised focus modes."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "fps": None,
                    "sensor_resolution": None,
                    "output_resolution": {"width_px": 1280, "height_px": 720},
                    "rotation_degrees": 0,
                    "focus": {"mode": "unmanaged"},
                },
                {
                    "fps": 30.0,
                    "sensor_resolution": {"width_px": 2304, "height_px": 1296},
                    "output_resolution": {"width_px": 1280, "height_px": 720},
                    "rotation_degrees": 90,
                    "focus": {"mode": "continuous"},
                },
            ]
        }
    )

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

    fps: float | None = Field(
        default=None,
        gt=0,
        description=(
            "New positive frame rate. Explicit null restores provider-managed "
            "FPS; omission preserves the current value."
        ),
        examples=[None, 15.0, 30.0],
    )
    sensor_resolution: PixelResolution | None = Field(
        default=None,
        description=(
            "Advertised raw sensor resolution. Explicit null restores provider "
            "selection; omission preserves the current value."
        ),
    )
    output_resolution: PixelResolution | None = Field(
        default=None,
        description=(
            "Exact even-sized encoded output resolution. Null is not accepted; "
            "omit the field to preserve the current value."
        ),
    )
    rotation_degrees: CameraRotation | None = Field(
        default=None,
        description=(
            "Clockwise JPEG EXIF orientation: 0, 90, 180, or 270. Null is not "
            "accepted; omission preserves the current value."
        ),
        examples=[0, 90, 180, 270],
    )
    focus: FocusSettings | None = Field(
        default=None,
        description=(
            "Focus policy supported by the active camera. Null is not accepted; "
            "omission preserves the current value."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"fps": 15.0},
                {"fps": None, "sensor_resolution": None},
                {
                    "sensor_resolution": {"width_px": 2304, "height_px": 1296},
                    "fps": 30.0,
                },
                {"output_resolution": {"width_px": 640, "height_px": 480}},
                {"rotation_degrees": 90},
                {"focus": {"mode": "unmanaged"}},
                {"focus": {"mode": "manual", "lens_position_diopters": 2.0}},
                {"focus": {"mode": "auto"}},
                {"focus": {"mode": "continuous"}},
            ]
        }
    )

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

    sensor_temperature_c: float | None = Field(
        default=None,
        description=(
            "Latest reported sensor temperature in degrees Celsius, or null "
            "when the provider does not publish it."
        ),
        examples=[25.0, 42.5],
    )
    focus_state: FocusState | None = Field(
        default=None,
        description=(
            "Latest provider focus state: idle, scanning, focused, failed, or "
            "unavailable. Null means no focus metadata has been observed."
        ),
        examples=["idle", "scanning", "focused", "failed", "unavailable"],
    )
    lens_position_diopters: float | None = Field(
        default=None,
        description="Latest provider-reported lens position in diopters.",
        examples=[2.0, 3.0],
    )
    latest_focus_succeeded: bool | None = Field(
        default=None,
        description=(
            "Outcome of the latest completed focus scan, or null before an "
            "outcome is available."
        ),
        examples=[True, False],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sensor_temperature_c": 42.5,
                    "focus_state": "focused",
                    "lens_position_diopters": 3.0,
                    "latest_focus_succeeded": True,
                },
                {
                    "sensor_temperature_c": None,
                    "focus_state": None,
                    "lens_position_diopters": None,
                    "latest_focus_succeeded": None,
                },
            ]
        }
    )


class SensorModeCapability(_ResponseModel):
    """One raw sensor mode advertised by Picamera2."""

    resolution: PixelResolution | None = Field(
        default=None,
        description=(
            "Raw sensor dimensions, or null when Picamera2 did not expose them."
        ),
    )
    format: str | None = Field(
        default=None,
        description="Provider-reported raw sensor pixel format.",
        examples=["SRGGB10_CSI2P", "YUYV"],
    )
    bit_depth: int | None = Field(
        default=None,
        ge=1,
        description="Provider-reported sensor bit depth.",
        examples=[8, 10, 12],
    )
    max_fps: float | None = Field(
        default=None,
        gt=0,
        description="Maximum reported frames per second for this sensor mode.",
        examples=[30.0, 56.0, 120.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "resolution": {"width_px": 2304, "height_px": 1296},
                    "format": "SRGGB10_CSI2P",
                    "bit_depth": 10,
                    "max_fps": 56.0,
                }
            ]
        }
    )


class LensPositionCapability(_ResponseModel):
    """Provider-advertised manual lens control range."""

    minimum: float = Field(
        description="Smallest supported manual lens position in diopters.",
        examples=[0.0],
    )
    maximum: float = Field(
        description="Largest supported manual lens position in diopters.",
        examples=[10.0, 32.0],
    )
    default: float | None = Field(
        default=None,
        description="Provider default lens position when one is advertised.",
        examples=[1.0, 3.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"minimum": 0.0, "maximum": 10.0, "default": 1.0}]
        }
    )


class OutputCapability(_ResponseModel):
    """Stable encoded-output contract implemented by the service."""

    default_resolution: PixelResolution = Field(
        description="Encoded output size used by the default settings."
    )
    pixel_format: Literal["YUV420"] = Field(
        default="YUV420",
        description="Internal stream pixel format passed to the MJPEG encoder.",
    )
    encoding: Literal["MJPEG"] = Field(
        default="MJPEG",
        description="Encoding shared by the stream and latest-image endpoints.",
    )
    width_multiple: Literal[2] = Field(
        default=2,
        description="Output width must be divisible by this value.",
    )
    height_multiple: Literal[2] = Field(
        default=2,
        description="Output height must be divisible by this value.",
    )
    exact_resolution_required: Literal[True] = Field(
        default=True,
        description=(
            "The provider must apply requested output dimensions exactly; "
            "silent adjustment is rejected."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "default_resolution": {"width_px": 1280, "height_px": 720},
                    "pixel_format": "YUV420",
                    "encoding": "MJPEG",
                    "width_multiple": 2,
                    "height_multiple": 2,
                    "exact_resolution_required": True,
                }
            ]
        }
    )


class FocusCapability(_ResponseModel):
    """Focus operations supported by the active provider."""

    modes: tuple[FocusMode, ...] = Field(
        description=(
            "Supported focus policies. Submit only listed values in camera "
            "settings; one-shot autofocus additionally requires `auto`."
        ),
        examples=[
            ["unmanaged"],
            ["unmanaged", "manual", "auto", "continuous"],
        ],
    )
    lens_position_diopters: LensPositionCapability | None = Field(
        default=None,
        description=(
            "Allowed manual-focus range, or null when manual lens positioning "
            "is unavailable."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "modes": ["unmanaged", "manual", "auto", "continuous"],
                    "lens_position_diopters": {
                        "minimum": 0.0,
                        "maximum": 10.0,
                        "default": 1.0,
                    },
                },
                {"modes": ["unmanaged"], "lens_position_diopters": None},
            ]
        }
    )


class MetadataCapability(_ResponseModel):
    """Metadata keys observed in completed camera requests."""

    sensor_temperature_c: bool = Field(
        default=False,
        description="Whether sensor-temperature metadata has been observed.",
    )
    focus_state: bool = Field(
        default=False,
        description="Whether focus-state metadata has been observed.",
    )
    lens_position_diopters: bool = Field(
        default=False,
        description="Whether lens-position metadata has been observed.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sensor_temperature_c": True,
                    "focus_state": True,
                    "lens_position_diopters": True,
                },
                {
                    "sensor_temperature_c": False,
                    "focus_state": False,
                    "lens_position_diopters": False,
                },
            ]
        }
    )


class CameraCapabilities(_ResponseModel):
    """Runtime-discovered capabilities for the active camera."""

    backend: CameraBackend = Field(
        description="Runtime camera implementation serving this process.",
        examples=["simulation", "rpi"],
    )
    device_index: int | None = Field(
        default=None,
        description=(
            "Provider camera index. The Raspberry Pi adapter currently supports "
            "index 0; simulation has no physical index."
        ),
        examples=[0],
    )
    device_model: str | None = Field(
        default=None,
        description="Model reported by the active provider.",
        examples=["simulation", "imx708"],
    )
    discovery_warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Non-fatal capability-discovery problems. The camera may still "
            "stream with provider-managed selections."
        ),
    )
    sensor_modes: tuple[SensorModeCapability, ...] = Field(
        default=(),
        description=(
            "Raw modes discovered from Picamera2. The list may be empty when "
            "mode enumeration was unavailable; null sensor_resolution still "
            "allows provider selection."
        ),
    )
    output: OutputCapability = Field(
        description="Stable encoded-output rules implemented by this service."
    )
    frame_rate_control: bool = Field(
        description="Whether the provider accepts an explicit FPS setting.",
        examples=[True, False],
    )
    focus: FocusCapability = Field(
        description="Focus policies and manual range discovered at runtime."
    )
    rotation_degrees: tuple[CameraRotation, ...] = Field(
        default=(0, 90, 180, 270),
        description="Supported clockwise JPEG EXIF orientations.",
    )
    observed_metadata: MetadataCapability = Field(
        default=MetadataCapability(),
        description="Optional telemetry fields observed from completed frames.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "backend": "rpi",
                    "device_index": 0,
                    "device_model": "imx708",
                    "discovery_warnings": [],
                    "sensor_modes": [
                        {
                            "resolution": {"width_px": 2304, "height_px": 1296},
                            "format": "SRGGB10_CSI2P",
                            "bit_depth": 10,
                            "max_fps": 56.0,
                        }
                    ],
                    "output": {
                        "default_resolution": {
                            "width_px": 1280,
                            "height_px": 720,
                        },
                        "pixel_format": "YUV420",
                        "encoding": "MJPEG",
                        "width_multiple": 2,
                        "height_multiple": 2,
                        "exact_resolution_required": True,
                    },
                    "frame_rate_control": True,
                    "focus": {
                        "modes": [
                            "unmanaged",
                            "manual",
                            "auto",
                            "continuous",
                        ],
                        "lens_position_diopters": {
                            "minimum": 0.0,
                            "maximum": 10.0,
                            "default": 1.0,
                        },
                    },
                    "rotation_degrees": [0, 90, 180, 270],
                    "observed_metadata": {
                        "sensor_temperature_c": True,
                        "focus_state": True,
                        "lens_position_diopters": True,
                    },
                }
            ]
        }
    )


class CameraStreamInfo(_ResponseModel):
    """Effective physical and encoded stream dimensions."""

    sensor_resolution: PixelResolution | None = Field(
        default=None,
        description=(
            "Effective sensor dimensions reported after configuration, or null "
            "when the provider does not expose them."
        ),
    )
    output_resolution: PixelResolution = Field(
        description="Exact dimensions of each encoded JPEG stream frame."
    )
    media_type: Literal["multipart/x-mixed-replace; boundary=frame"] = Field(
        default="multipart/x-mixed-replace; boundary=frame",
        description="HTTP media type returned by the MJPEG stream endpoint.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sensor_resolution": {"width_px": 2304, "height_px": 1296},
                    "output_resolution": {"width_px": 1280, "height_px": 720},
                    "media_type": "multipart/x-mixed-replace; boundary=frame",
                }
            ]
        }
    )


class CameraStatus(_ResponseModel):
    """Consolidated camera availability, configuration, and telemetry."""

    backend: CameraBackend = Field(
        description="Runtime camera implementation serving this process.",
        examples=["simulation", "rpi"],
    )
    state: CameraState = Field(
        description=(
            "Pipeline lifecycle state: starting, streaming, reconfiguring, "
            "unavailable, or stopped."
        ),
        examples=["starting", "streaming", "reconfiguring", "unavailable"],
    )
    device_index: int | None = Field(
        default=None,
        description="Provider camera index, or null for simulation/unavailable state.",
        examples=[0],
    )
    device_model: str | None = Field(
        default=None,
        description="Provider-reported camera model when available.",
        examples=["simulation", "imx708"],
    )
    settings: CameraSettings | None = Field(
        description=(
            "Last complete configuration accepted by the service, or null when "
            "the camera is unavailable."
        )
    )
    stream: CameraStreamInfo | None = Field(
        description=(
            "Effective active stream configuration. Present only in the "
            "streaming state."
        )
    )
    sensor_temperature_c: float | None = Field(
        default=None,
        description="Latest sensor temperature in degrees Celsius when reported.",
        examples=[25.0, 42.5],
    )
    focus_state: FocusState | None = Field(
        default=None,
        description="Latest provider focus state when reported.",
        examples=["idle", "scanning", "focused", "failed", "unavailable"],
    )
    latest_focus_succeeded: bool | None = Field(
        default=None,
        description="Outcome of the latest completed autofocus scan.",
        examples=[True, False],
    )
    lens_position_diopters: float | None = Field(
        default=None,
        description="Latest provider-reported lens position in diopters.",
        examples=[2.0, 3.0],
    )
    unavailable_reason: str | None = Field(
        default=None,
        description=(
            "Camera startup/runtime failure when state is unavailable; null "
            "during normal operation."
        ),
        examples=["Picamera2/libcamera is unavailable"],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "backend": "simulation",
                    "state": "streaming",
                    "device_index": None,
                    "device_model": "simulation",
                    "settings": {
                        "fps": None,
                        "sensor_resolution": None,
                        "output_resolution": {
                            "width_px": 1280,
                            "height_px": 720,
                        },
                        "rotation_degrees": 0,
                        "focus": {"mode": "unmanaged"},
                    },
                    "stream": {
                        "sensor_resolution": {
                            "width_px": 1280,
                            "height_px": 720,
                        },
                        "output_resolution": {
                            "width_px": 1280,
                            "height_px": 720,
                        },
                        "media_type": ("multipart/x-mixed-replace; boundary=frame"),
                    },
                    "sensor_temperature_c": 25.0,
                    "focus_state": None,
                    "latest_focus_succeeded": None,
                    "lens_position_diopters": None,
                    "unavailable_reason": None,
                },
                {
                    "backend": "rpi",
                    "state": "unavailable",
                    "device_index": None,
                    "device_model": None,
                    "settings": None,
                    "stream": None,
                    "sensor_temperature_c": None,
                    "focus_state": "unavailable",
                    "latest_focus_succeeded": None,
                    "lens_position_diopters": None,
                    "unavailable_reason": "Picamera2/libcamera is unavailable",
                },
            ]
        }
    )


class AutofocusResult(_ResponseModel):
    """Result of a synchronous one-shot autofocus request."""

    success: bool = Field(
        description=(
            "Whether the provider reported a successful completed scan. False "
            "is still an HTTP 200 result, not a transport error."
        ),
        examples=[True, False],
    )
    focus_state: FocusState | None = Field(
        default=None,
        description="Terminal provider focus state when metadata is available.",
        examples=["focused", "failed"],
    )
    lens_position_diopters: float | None = Field(
        default=None,
        description="Lens position after the scan when metadata is available.",
        examples=[2.0, 3.0],
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "success": True,
                    "focus_state": "focused",
                    "lens_position_diopters": 3.0,
                },
                {
                    "success": False,
                    "focus_state": "failed",
                    "lens_position_diopters": 3.0,
                },
            ]
        }
    )


DEFAULT_OUTPUT_RESOLUTION = PixelResolution(width_px=1280, height_px=720)
DEFAULT_CAMERA_SETTINGS = CameraSettings(
    fps=None,
    sensor_resolution=None,
    output_resolution=DEFAULT_OUTPUT_RESOLUTION,
    rotation_degrees=0,
    focus=UnmanagedFocus(mode="unmanaged"),
)
