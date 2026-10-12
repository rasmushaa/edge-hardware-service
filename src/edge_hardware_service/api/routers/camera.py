"""HTTP endpoints for camera state, controls, and shared MJPEG frames."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Response, status
from fastapi.responses import StreamingResponse

from edge_hardware_service.api.dependencies import CameraServiceDep
from edge_hardware_service.api.errors import (
    HARDWARE_UNAVAILABLE_RESPONSE,
    INVALID_REQUEST_RESPONSE,
    OPERATION_TIMEOUT_RESPONSE,
)
from edge_hardware_service.models.camera import (
    AutofocusResult,
    CameraCapabilities,
    CameraSettingsPatch,
    CameraStatus,
)
from edge_hardware_service.services.camera import CameraFrame, CameraService

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
    status.HTTP_422_UNPROCESSABLE_CONTENT: INVALID_REQUEST_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
}
CAMERA_AUTOFOCUS_RESPONSES = {
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
    first_frame: CameraFrame,
) -> Iterator[bytes]:
    """Yield each new broker frame once for one streaming client."""
    frame = first_frame
    while True:
        yield _mjpeg_part(frame)
        next_frame = service.frames.wait_for_frame(
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
Return the current state of the process-wide camera pipeline.

The service opens one camera when the application starts and keeps one encoded
MJPEG producer running. This endpoint only reads its state; it does not open,
restart, or capture from the camera.

### Reading the response

- `state` is `starting`, `streaming`, `reconfiguring`, `unavailable`, or
  `stopped`.
- `settings` contains the last complete configuration accepted by the service.
  It is `null` when the camera is unavailable.
- `stream` reports effective sensor and encoded-output dimensions only while
  the pipeline is streaming.
- Temperature and focus telemetry are nullable because cameras do not all
  publish the same metadata.
- `unavailable_reason` explains a startup or runtime failure without making the
  health and GPIO endpoints unavailable.

Use `GET /api/v1/camera/capabilities` before presenting settings to a user or
submitting hardware-specific values.
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
Discover what the active camera and provider support at runtime.

The service does not use a camera-model allowlist. It inspects Picamera2 when
the camera starts and exposes the resulting contract here. Clients should read
this endpoint instead of assuming that every camera supports the same
frame-rate control, focus controls, lens range, or metadata.

### Using capabilities

- `sensor_resolution` is a best-match hint. Picamera2/libcamera chooses the
  applied sensor mode, which is reported by `GET /api/v1/camera` under
  `stream.sensor_resolution` when available.
- Set `fps` only when `frame_rate_control` is `true`.
- `output` describes the service's encoded MJPEG contract. Output dimensions
  must be positive, even, and applied exactly.
- Choose a focus request only from `focus.modes`. When `manual` is present, use
  the advertised `lens_position_diopters` range.
- `observed_metadata` tells clients which optional telemetry fields the provider
  has actually published.
- `sensor_modes` is informational and may be empty. The physical adapter avoids
  Picamera2's invasive exhaustive enumeration because it can exhaust DMA memory;
  an empty list does not prevent sensor-resolution hints.

Capabilities describe this running camera instance and may differ after
hardware, driver, or operating-system changes.
""",
    response_model=CameraCapabilities,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE},
)
def get_camera_capabilities(service: CameraServiceDep) -> CameraCapabilities:
    """Return runtime-discovered capabilities for the active camera."""
    return service.capabilities()


@router.patch(
    "/settings",
    summary="Update camera settings",
    operation_id="update_camera_settings",
    description="""
Apply an atomic partial update to the shared camera pipeline.

Omitted fields keep their current values. The service validates the merged
configuration before committing it and rolls back if reconfiguration fails, so
clients never receive a successful partially applied configuration.

### Supported settings

| Field | Accepted value | Meaning |
| --- | --- | --- |
| `fps` | Positive number or `null` | Target frames per second; `null` restores provider control. |
| `sensor_resolution` | `{width_px, height_px}` or `null` | Give Picamera2 a best-match sensor-size hint; `null` leaves selection entirely to the provider. |
| `output_resolution` | Positive even `{width_px, height_px}` | Exact dimensions of every encoded MJPEG/JPEG frame. |
| `rotation_degrees` | `0`, `90`, `180`, or `270` | Clockwise JPEG EXIF orientation; encoded dimensions are unchanged. |
| `focus.mode` | `unmanaged` | Leave focus behavior to the provider. |
| `focus.mode` | `manual` plus `lens_position_diopters` | Hold the lens at an advertised manual position. |
| `focus.mode` | `auto` | Select one-shot autofocus mode; call `/api/v1/camera/autofocus` to run a scan. |
| `focus.mode` | `continuous` | Let the camera continually adjust focus. |

Read `/api/v1/camera/capabilities` before requesting optional controls. A
provider-rejected configuration leaves the previous settings active. Changes
that require a pipeline restart temporarily set the state to `reconfiguring`;
connected stream clients wait and continue when the first frame from the new
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


@router.post(
    "/autofocus",
    summary="Run one-shot autofocus",
    operation_id="autofocus_camera",
    description="""
Run one synchronous autofocus scan on the existing shared camera pipeline.

- The active camera must advertise `auto` in
  `GET /api/v1/camera/capabilities` under `focus.modes`. Otherwise the request
  returns `422 invalid_request` without changing camera settings.
- If the current focus mode is not `auto`, the service first changes it to
  `auto`. That setting remains active after the request; it is not restored to
  the previous mode.
- The endpoint triggers the scan and waits up to 10 seconds for terminal focus
  metadata. The existing MJPEG producer remains the source of video frames; no
  separate still capture or camera instance is created.
- A completed scan returns HTTP 200 even when `success` is `false`. A missed
  deadline returns `504 operation_timeout`; provider failures return
  `503 hardware_unavailable`.

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

This is a normal streaming HTTP endpoint, not a URL for another camera server,
WebSocket, or HLS service. The response uses
`multipart/x-mixed-replace; boundary=frame`; every part is one complete JPEG
with its own `Content-Type` and `Content-Length` headers.

### Efficient consumption

- Open one connection and keep reading parts. Reconnecting or polling this
  endpoint for individual frames is inefficient.
- Browsers can display it directly with
  `<img src=\"/api/v1/camera/stream\" alt=\"Camera stream\">`; other clients
  should use an MJPEG/multipart parser.
- All clients share the same process-wide camera producer and already encoded
  frames. Opening another client does not open another camera or start another
  encoding pipeline.
- The broker retains only the newest complete JPEG. Each client receives new
  sequence values as they arrive; a slow client skips overwritten frames rather
  than building an unbounded queue or increasing capture latency.
- The response is explicitly non-cacheable and proxy buffering is disabled.
  Preserve streaming behavior in any reverse proxy placed in front of it.

During a settings reconfiguration the connection waits for the new stream. It
ends cleanly if frames stop because the camera becomes unavailable or the
service shuts down.
""",
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Long-lived multipart MJPEG response from the shared camera pipeline."
            ),
            "content": {STREAM_MEDIA_TYPE: {}},
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    },
)
def stream_camera(service: CameraServiceDep) -> StreamingResponse:
    """Stream frames from the process-wide latest-frame broker."""
    first_frame = service.wait_for_frame()
    return StreamingResponse(
        _stream_frames(service, first_frame),
        media_type=STREAM_MEDIA_TYPE,
        headers={**NO_CACHE_HEADERS, "X-Accel-Buffering": "no"},
    )


@router.get(
    "/image",
    summary="Get the latest stream image",
    operation_id="get_camera_image",
    description="""
Return the newest complete JPEG already produced by the MJPEG pipeline.

This endpoint is a snapshot of the stream buffer, **not a camera still-capture operation**.
It does not open the camera, interrupt streaming, change settings, or request a higher-resolution frame.

The process-wide broker stores at most one immutable JPEG.
Every new stream frame atomically replaces the previous frame, so memory use stays bounded and
the response is as current as the producer's latest completed encode.
If no frame exists yet, the request waits up to two seconds for one; it returns
`503 hardware_unavailable` when a frame cannot be obtained.

Use this endpoint for occasional previews, thumbnails, monitoring checks, or
clients that need one JPEG. For live video, keep one connection open to
`GET /api/v1/camera/stream` instead of repeatedly polling this endpoint. The
response is non-cacheable so callers receive the broker's current frame.
""",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Newest buffered JPEG from the stream; no still capture is taken."
            ),
            "content": {JPEG_MEDIA_TYPE: {}},
        },
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
