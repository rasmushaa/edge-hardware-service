"""HTTP endpoints for camera state, controls, and shared MJPEG frames."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Response, status
from fastapi.responses import StreamingResponse

from edge_hardware_service.api.dependencies import CameraServiceDep
from edge_hardware_service.api.errors import (
    CAMERA_NOT_CONNECTED_RESPONSE,
    CONFLICT_RESPONSE,
    HARDWARE_UNAVAILABLE_RESPONSE,
    INVALID_REQUEST_RESPONSE,
    OPERATION_TIMEOUT_RESPONSE,
)
from edge_hardware_service.models.camera import (
    AutofocusResult,
    CameraCapabilities,
    CameraConnectRequest,
    CameraSettingsPatch,
    CameraStatus,
)
from edge_hardware_service.services.camera import (
    CameraFrame,
    CameraService,
    LatestFrameBroker,
)

router = APIRouter(prefix="/camera", tags=["Camera"])

FRAME_BOUNDARY = b"frame"
STREAM_MEDIA_TYPE = "multipart/x-mixed-replace; boundary=frame"
JPEG_MEDIA_TYPE = "image/jpeg"
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate",
    "Pragma": "no-cache",
    "Age": "0",
}

CameraSettingsBody = Annotated[
    CameraSettingsPatch,
    Body(
        openapi_examples={
            "frame_rate": {
                "summary": "Change the frame rate",
                "description": (
                    "Use a positive FPS supported by the selected sensor mode."
                ),
                "value": {"fps": 15},
            },
            "provider_defaults": {
                "summary": "Restore provider-managed FPS and sensor mode",
                "description": ("Null is accepted only for fps and sensor_resolution."),
                "value": {"fps": None, "sensor_resolution": None},
            },
            "sensor_hint": {
                "summary": "Prefer a sensor resolution",
                "description": (
                    "Picamera2 selects the best available sensor mode; inspect "
                    "camera status to see the applied sensor resolution."
                ),
                "value": {
                    "sensor_resolution": {
                        "width_px": 2304,
                        "height_px": 1296,
                    },
                    "fps": 30,
                },
            },
            "output_resolution": {
                "summary": "Change the encoded MJPEG dimensions",
                "description": (
                    "Both dimensions must be even and the provider must apply "
                    "the requested size exactly."
                ),
                "value": {
                    "output_resolution": {
                        "width_px": 640,
                        "height_px": 480,
                    }
                },
            },
            "portrait": {
                "summary": "Rotate display orientation clockwise",
                "description": (
                    "Writes JPEG EXIF orientation; encoded dimensions do not swap."
                ),
                "value": {"rotation_degrees": 90},
            },
            "manual_focus": {
                "summary": "Set a manual lens position",
                "value": {
                    "focus": {
                        "mode": "manual",
                        "lens_position_diopters": 2.0,
                    }
                },
            },
            "auto_focus_mode": {
                "summary": "Select one-shot autofocus mode",
                "description": (
                    "This selects auto mode; POST /api/v1/camera/autofocus "
                    "runs the scan."
                ),
                "value": {"focus": {"mode": "auto"}},
            },
            "continuous_focus": {
                "summary": "Enable continuous autofocus",
                "value": {"focus": {"mode": "continuous"}},
            },
            "provider_managed_focus": {
                "summary": "Return focus control to the provider",
                "value": {"focus": {"mode": "unmanaged"}},
            },
        }
    ),
]

CAMERA_SETTINGS_RESPONSES = {
    status.HTTP_409_CONFLICT: CAMERA_NOT_CONNECTED_RESPONSE,
    status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_REQUEST_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
}
CAMERA_AUTOFOCUS_RESPONSES = {
    status.HTTP_409_CONFLICT: CAMERA_NOT_CONNECTED_RESPONSE,
    status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_REQUEST_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    status.HTTP_504_GATEWAY_TIMEOUT: OPERATION_TIMEOUT_RESPONSE,
}


def _mjpeg_part(frame: CameraFrame) -> bytes:
    """Wrap one complete JPEG in an MJPEG multipart section."""
    return (
        b"--"
        + FRAME_BOUNDARY
        + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
        + str(len(frame.jpeg)).encode("ascii")
        + b"\r\n\r\n"
        + frame.jpeg
        + b"\r\n"
    )


def _stream_frames(
    service: CameraService,
    broker: LatestFrameBroker,
    first_frame: CameraFrame,
) -> Iterator[bytes]:
    """Yield each new broker frame once for one streaming client."""
    frame = first_frame
    while True:
        yield _mjpeg_part(frame)
        next_frame = broker.wait_for_frame(
            after_sequence=frame.sequence,
        )
        if next_frame is None:
            if service.status().state == "reconfiguring":
                continue
            # A normal 1 FPS stream publishes within this two-second wait.
            # End a stalled response cleanly instead of retaining a dead
            # connection indefinitely after a later provider failure.
            return
        frame = next_frame


@router.get(
    "",
    summary="Inspect camera state",
    operation_id="get_camera_status",
    description="""
Return a snapshot of the process-wide camera pipeline.

The service normally opens a camera during application startup.
While connected, every camera endpoint shares the same adapter,
configuration, encoder, and latest-frame buffer.

This operation only reads state.
It does not open, close, or reconfigure the camera.

### Camera state

- `starting`, `reconfiguring`, and `reconnecting` are temporary transitions.
- `streaming` means the camera is connected and producing JPEG frames.
- `disconnected` means a client intentionally released the camera.
- `unavailable` means a connection or provider operation failed.
- `stopped` means the application is shutting down.

### Response fields

- `settings` is the complete desired configuration.
  It is `null` only after release or shutdown.
  Failed connections keep their desired settings for inspection and retry.
- `stream` contains the provider's active sensor size, when known,
  and the exact encoded output size.
  It is present only while `state` is `streaming`.
- Temperature and focus fields are nullable.
  Camera modules do not all publish the same metadata.
- `unavailable_reason` explains the latest camera failure.
  Camera failure does not make the health or GPIO endpoints unavailable.
- `reconnect_used_defaults` tells whether reconnect had to discard saved
  settings and retry with service defaults.

Read `GET /api/v1/camera/capabilities` before presenting controls to a user
or sending hardware-specific settings.
""",
    response_model=CameraStatus,
)
def get_camera_status(service: CameraServiceDep) -> CameraStatus:
    """Return camera availability, effective settings, and telemetry."""
    return service.status()


@router.get(
    "/capabilities",
    summary="Inspect active camera capabilities",
    operation_id="get_camera_capabilities",
    description="""
Return the capabilities discovered from the active camera and provider.

The service does not use a camera-model allowlist.
It builds this response from Picamera2 and libcamera information available
for the current adapter.

Do not assume that all camera modules expose the same frame-rate control,
focus modes, manual lens range, sensor information, or telemetry.

### Choosing settings

- Set `fps` only when `frame_rate_control` is `true`.
- Send only focus modes listed in `focus.modes`.
- When `manual` focus is listed, keep the lens position within the advertised
  `lens_position_diopters` range.
- Follow `output` for encoded-image constraints.
  This service requires positive, even dimensions and exact application.
- `rotation_degrees` lists the accepted display orientations.

### Sensor resolution

`sensor_resolution` in camera settings is a best-match hint.
Picamera2 and libcamera choose the actual sensor mode.

Read `GET /api/v1/camera` after applying settings.
When the provider exposes the value,
`stream.sensor_resolution` reports the selected sensor dimensions.

`sensor_modes` is informational and may be empty.
The physical adapter deliberately avoids Picamera2's invasive exhaustive
mode enumeration because it can exhaust DMA memory.
An empty list does not prevent sensor-resolution hints.

### Runtime information

- `observed_metadata` identifies optional metadata seen in completed frames.
- `discovery_warnings` contains non-fatal discovery problems.
- Capabilities belong to this running adapter instance.
  They may change after reconnecting, replacing hardware,
  or updating the operating system or camera stack.
""",
    response_model=CameraCapabilities,
    responses={
        status.HTTP_409_CONFLICT: CAMERA_NOT_CONNECTED_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def get_camera_capabilities(service: CameraServiceDep) -> CameraCapabilities:
    """Return runtime-discovered capabilities for the active camera."""
    return service.capabilities()


@router.post(
    "/settings/reset",
    summary="Reset camera settings",
    operation_id="reset_camera_settings",
    description="""
Restore every camera setting to the service default.

### Defaults

- Sensor mode: provider managed.
- Frame rate: provider managed.
- Focus: unmanaged by this service.
- Encoded output: exactly 1280 × 720 pixels.
- JPEG orientation: 0 degrees.

This is an atomic settings operation on the existing adapter.
It does not select a different camera or rebuild the connection.

If the provider rejects the reset,
the service restores the complete previous configuration.
A rollback failure changes the camera state to `unavailable`.

Use `POST /api/v1/camera/reconnect` only when the camera connection itself
must be rebuilt.
""",
    response_model=CameraStatus,
    responses=CAMERA_SETTINGS_RESPONSES,
)
def reset_camera_settings(service: CameraServiceDep) -> CameraStatus:
    """Restore all service defaults without replacing the adapter."""
    service.reset_settings()
    return service.status()


@router.patch(
    "/settings",
    summary="Update camera settings",
    operation_id="update_camera_settings",
    description="""
Apply an atomic partial update to the shared camera pipeline.

Omitted fields keep their current values.
The service first merges the patch with the current complete settings,
then validates and applies the result.

A successful response never represents a partially applied patch.
If provider reconfiguration fails,
the service restores the previous settings before returning an error.

### Supported settings

- **`fps`** — a positive number requests a frame rate.
  `null` restores provider-managed timing.
- **`sensor_resolution`** — a complete pixel size is a best-match hint.
  `null` restores provider selection.
  Inspect camera status to learn the actual selected size.
- **`output_resolution`** — the exact encoded JPEG size.
  Both dimensions must be positive and even.
- **`rotation_degrees`** — `0`, `90`, `180`, or `270`.
  Rotation is written as JPEG EXIF orientation;
  encoded width and height do not swap.
- **`focus.mode: unmanaged`** — send no service-selected focus controls.
- **`focus.mode: manual`** — hold the lens at
  `lens_position_diopters`.
- **`focus.mode: auto`** — select one-shot autofocus mode.
  Call `POST /api/v1/camera/autofocus` to run the scan.
- **`focus.mode: continuous`** — let the camera adjust focus continuously.

`output_resolution`, `rotation_degrees`, and `focus` cannot be `null`.
Omit one of these fields to preserve its current value.

### Capability and stream behavior

Read `GET /api/v1/camera/capabilities` before requesting optional controls.
A well-formed value unsupported by the active camera returns
`422 invalid_request` and leaves the previous settings active.

Changes that restart the pipeline temporarily set camera state to
`reconfiguring`.
Existing stream clients wait and continue after the first frame from the new
configuration arrives.
""",
    response_model=CameraStatus,
    responses=CAMERA_SETTINGS_RESPONSES,
)
def update_camera_settings(
    patch: CameraSettingsBody,
    service: CameraServiceDep,
) -> CameraStatus:
    """Apply an atomic partial settings update and return effective state."""
    service.update_settings(patch)
    return service.status()


@router.delete(
    "",
    summary="Release camera",
    operation_id="release_camera",
    description="""
Intentionally stop and close the active camera without stopping this service.

### Effects

- Encoding stops and Picamera2 is closed.
- Accepted settings and buffered frames are cleared.
- Active MJPEG responses end.
- Camera status remains available and reports `disconnected`.

Release is idempotent.
Releasing an already disconnected camera also returns HTTP 204.

`disconnected` is distinct from `unavailable`.
The former is intentional;
the latter means a connection or provider operation failed.

Use `POST /api/v1/camera/connect` to acquire a camera again.
Release only closes software resources.
It does not power-cycle the sensor or change operating-system hardware
discovery.
""",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE},
)
def release_camera(service: CameraServiceDep) -> Response:
    """Release camera resources and discard its active configuration."""
    service.release()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connect",
    summary="Connect camera",
    operation_id="connect_camera",
    description="""
Create a fresh Picamera2 adapter after the camera has been released.

### Camera selection

The optional request body selects a non-negative Picamera2 `device_index`.
An omitted body or omitted field selects index 0.

Connect is allowed only while camera state is `disconnected`.
It never replaces an active or failed camera implicitly.

- Release an active camera before selecting another index.
- Use reconnect to retry an `unavailable` camera with its saved index
  and desired settings.

### Successful connection

Connect always starts with the complete service defaults.
It returns HTTP 201 only after the first complete JPEG arrives.

The response contains the model, effective stream information,
settings, and current telemetry.
Read the capabilities endpoint for discovered controls.

### Failed connection

A failed attempt closes partially created resources,
records the attempted index and reason in camera status,
changes state to `unavailable`,
and returns `503 hardware_unavailable`.
""",
    response_model=CameraStatus,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: CONFLICT_RESPONSE,
        status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_REQUEST_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def connect_camera(
    service: CameraServiceDep,
    request: Annotated[CameraConnectRequest | None, Body()] = None,
) -> CameraStatus:
    """Connect a fresh adapter using defaults and wait for its first frame."""
    return service.connect(0 if request is None else request.device_index)


@router.post(
    "/reconnect",
    summary="Reconnect camera",
    operation_id="reconnect_camera",
    description="""
Replace the current or failed adapter without restarting the application.

Reconnect is available while camera state is `streaming` or `unavailable`.
It cannot be used after intentional release;
use the connect operation in that state.

### Reconnect sequence

1. Close the old adapter and end its frame broker.
2. Create a new adapter for the current or last-attempted device index.
3. Reapply the complete desired settings.
4. Return after the replacement produces its first complete JPEG.

Existing MJPEG responses end because they belong to the old camera generation.
Clients must open a new stream request.

### Incompatible saved settings

If the replacement rejects saved settings,
the service retries once with complete defaults.
The response then reports `reconnect_used_defaults: true`.

The service never applies a silent partial subset of saved settings.

If reconnect fails,
camera state becomes `unavailable`.
The desired settings and device index remain available for another retry,
and partially created resources are closed.

Reconnect rebuilds software resources.
It does not power-cycle the camera hardware.
""",
    response_model=CameraStatus,
    responses={
        status.HTTP_409_CONFLICT: CONFLICT_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def reconnect_camera(service: CameraServiceDep) -> CameraStatus:
    """Replace the adapter and preserve compatible desired settings."""
    return service.reconnect()


@router.post(
    "/autofocus",
    summary="Run one-shot autofocus",
    operation_id="autofocus_camera",
    description="""
Run one synchronous autofocus scan on the existing shared camera pipeline.

### Requirements

The active camera must list `auto` under `focus.modes` in
`GET /api/v1/camera/capabilities`.

Otherwise the request returns `422 invalid_request`
without changing camera settings.

### Focus-mode behavior

If current focus mode is not `auto`,
the service first changes it to `auto`.
That mode remains active after the request;
the previous mode is not restored.

### Completion and errors

The request waits up to 10 seconds for a terminal focus result.
The existing MJPEG producer continues to supply video frames.
No separate still capture or camera instance is created.

- HTTP 200 with `success: true` means the scan focused successfully.
- HTTP 200 with `success: false` means the scan completed without focus.
- `504 operation_timeout` means no terminal result arrived in time.
- `503 hardware_unavailable` means the provider operation failed.

Use `continuous` focus through `PATCH /api/v1/camera/settings` when the camera
should keep adjusting focus instead of running an explicit one-shot scan.
""",
    response_model=AutofocusResult,
    responses=CAMERA_AUTOFOCUS_RESPONSES,
)
def autofocus_camera(service: CameraServiceDep) -> AutofocusResult:
    """Run one autofocus scan while the continuous stream keeps running."""
    return service.autofocus()


@router.get(
    "/stream",
    summary="Stream MJPEG video",
    operation_id="stream_camera_mjpeg",
    description="""
Open a long-lived MJPEG response from this API server.

This is a normal streaming HTTP endpoint,
not a URL for another camera server, WebSocket, or HLS service.

The response media type is
`multipart/x-mixed-replace; boundary=frame`.
Every multipart section contains one complete JPEG with its own
`Content-Type` and `Content-Length` headers.

### Client usage

- Open one connection and keep reading multipart sections.
  Do not poll this endpoint for individual images.
- A browser can display the stream directly:
  `<img src=\"/api/v1/camera/stream\" alt=\"Camera stream\">`.
- Non-browser clients should use an MJPEG or multipart parser.
- All clients share one process-wide camera producer and encoded frame stream.
  Opening a client does not open another camera or encoder.
- The response is non-cacheable and asks compatible reverse proxies not to
  buffer it.

### Frame buffering and delay

The service broker stores only the newest complete JPEG.
It does not build a per-client frame queue.
A slow client can therefore skip broker frames before they are written.

After JPEG bytes enter the HTTP and TCP connection,
however, they remain ordered and cannot be replaced by newer frames.
If a browser, network, or proxy consumes bytes more slowly than the camera
produces them, downstream buffers can grow.
The displayed image may then become progressively older.

Closing and reopening the stream discards that connection-specific backlog
and resumes from the newest broker frame.

For sustained viewing, prefer camera settings that the slowest expected client
can consume continuously.
Lowering `fps` and, when appropriate, `output_resolution` reduces bandwidth
and browser decoding work.

Reconnection is a recovery measure.
Conservative stream settings are the safer way to avoid delay.

### Connection lifetime

During a settings reconfiguration the connection waits for the new stream.
It ends cleanly if frames stop because the camera becomes unavailable or the
service shuts down.

Outside reconfiguration,
the server also ends a connection when no new frame arrives within two seconds.
Open a new request to resume streaming after the camera is healthy.
""",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Long-lived multipart MJPEG response from the shared camera pipeline."
            ),
            "content": {STREAM_MEDIA_TYPE: {}},
        },
        status.HTTP_409_CONFLICT: CAMERA_NOT_CONNECTED_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def stream_camera(service: CameraServiceDep) -> StreamingResponse:
    """Stream frames from the process-wide latest-frame broker."""
    broker, first_frame = service.open_frame_source()
    return StreamingResponse(
        _stream_frames(service, broker, first_frame),
        media_type=STREAM_MEDIA_TYPE,
        headers={**NO_CACHE_HEADERS, "X-Accel-Buffering": "no"},
    )


@router.get(
    "/image",
    summary="Get the latest stream image",
    operation_id="get_camera_image",
    description="""
Return the newest complete JPEG already produced by the MJPEG pipeline.

This endpoint is a snapshot of the stream buffer,
**not a camera still-capture operation**.

It does not open the camera,
interrupt streaming,
change settings,
or request a higher-resolution frame.

The process-wide broker stores at most one immutable JPEG.
Every new stream frame atomically replaces the previous frame.
Memory use stays bounded,
and the response is as current as the producer's latest completed encode.

If no frame exists yet,
the request waits up to two seconds for one.
It returns `503 hardware_unavailable` when no frame can be obtained.

Use this endpoint for occasional previews, thumbnails, monitoring checks, or
clients that need one JPEG.

For live video,
keep one connection open to `GET /api/v1/camera/stream`
instead of repeatedly polling this endpoint.

The response is non-cacheable so callers receive the broker's current frame.
""",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Newest buffered JPEG from the stream; no still capture is taken."
            ),
            "content": {JPEG_MEDIA_TYPE: {}},
        },
        status.HTTP_409_CONFLICT: CAMERA_NOT_CONNECTED_RESPONSE,
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def get_camera_image(service: CameraServiceDep) -> Response:
    """Return the broker's latest encoded frame without taking a still."""
    frame = service.wait_for_frame()
    return Response(
        content=frame.jpeg,
        media_type=JPEG_MEDIA_TYPE,
        headers=NO_CACHE_HEADERS,
    )
