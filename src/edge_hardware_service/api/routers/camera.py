"""HTTP endpoints for camera state, controls, and shared MJPEG frames."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Body, Response, status
from fastapi.responses import StreamingResponse

from edge_hardware_service.api.dependencies import CameraServiceDep
from edge_hardware_service.api.errors import (
    CAMERA_CAPABILITY_RESPONSE,
    CAMERA_TIMEOUT_RESPONSE,
    HARDWARE_UNAVAILABLE_RESPONSE,
    VALIDATION_ERROR_RESPONSE,
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
                "value": {"fps": 15},
            },
            "sensor_mode": {
                "summary": "Select an advertised sensor resolution",
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
                "value": {
                    "output_resolution": {
                        "width_px": 640,
                        "height_px": 480,
                    }
                },
            },
            "portrait": {
                "summary": "Rotate display orientation clockwise",
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
            "continuous_focus": {
                "summary": "Enable continuous autofocus",
                "value": {"focus": {"mode": "continuous"}},
            },
        }
    ),
]

CAMERA_SETTINGS_RESPONSES = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: VALIDATION_ERROR_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
}
CAMERA_AUTOFOCUS_RESPONSES = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: CAMERA_CAPABILITY_RESPONSE,
    status.HTTP_503_SERVICE_UNAVAILABLE: HARDWARE_UNAVAILABLE_RESPONSE,
    status.HTTP_504_GATEWAY_TIMEOUT: CAMERA_TIMEOUT_RESPONSE,
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
    response_model=CameraStatus,
)
def get_camera_status(service: CameraServiceDep) -> CameraStatus:
    """Return camera availability, effective settings, and telemetry."""
    return service.status()


@router.get(
    "/capabilities",
    summary="Inspect active camera capabilities",
    operation_id="get_camera_capabilities",
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
    response_class=StreamingResponse,
    responses={
        status.HTTP_200_OK: {
            "description": "Continuous multipart MJPEG stream.",
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
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": "Latest JPEG already produced by the MJPEG stream.",
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
