"""HTTP error translation and OpenAPI error metadata for the API."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from edge_hardware_service.hardware.camera.exceptions import (
    CameraAutofocusTimeout,
    CameraCapabilityUnsupported,
    CameraNotReady,
    CameraOperationError,
    CameraSettingsInvalid,
    CameraUnavailable,
)
from edge_hardware_service.hardware.gpio.exceptions import (
    GpioHardwareError,
    GpioProviderError,
    GpioProviderUnavailable,
    PinAlreadyOpen,
    PinDeviceClosed,
    PinModeConflict,
    PinNotOpen,
)
from edge_hardware_service.models.errors import ErrorResponse

PIN_NOT_OPEN_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The requested pin is not open.",
}
PIN_CONFLICT_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The requested operation conflicts with the active pin mode.",
}
VALIDATION_ERROR_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The path or request body is invalid.",
}
HARDWARE_UNAVAILABLE_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The selected hardware provider could not complete the operation.",
}
CAMERA_TIMEOUT_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The camera operation exceeded its fixed timeout.",
}
CAMERA_CAPABILITY_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The active camera does not support the requested capability.",
}


def _json_error(status_code: int, error: ErrorResponse) -> JSONResponse:
    """Build a JSON response from the shared public error schema.

    Args:
        status_code: HTTP status code returned to the caller.
        error: Validated public error payload.

    Returns:
        JSON response containing the serialized error.
    """
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(mode="json", exclude_none=True),
    )


def _camera_hardware_error(error: Exception) -> JSONResponse:
    """Build the shared hardware-unavailable response for camera failures."""
    return _json_error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorResponse(
            code="hardware_unavailable",
            message=str(error),
            details={"component": "camera"},
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized translations from domain errors to HTTP responses.

    Args:
        app: FastAPI application receiving the exception handlers.
    """

    @app.exception_handler(CameraCapabilityUnsupported)
    async def camera_capability_unsupported_handler(
        request: Request,
        error: CameraCapabilityUnsupported,
    ) -> JSONResponse:
        """Translate unsupported camera features to an atomic 422 response."""
        del request
        return _json_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorResponse(
                code="capability_unsupported",
                message=str(error),
                details={"component": "camera"},
            ),
        )

    @app.exception_handler(CameraSettingsInvalid)
    async def camera_settings_invalid_handler(
        request: Request,
        error: CameraSettingsInvalid,
    ) -> JSONResponse:
        """Translate a rejected effective camera configuration to 422."""
        del request
        return _json_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorResponse(
                code="validation_error",
                message=str(error),
                details={"operation": "update camera settings"},
            ),
        )

    @app.exception_handler(CameraAutofocusTimeout)
    async def camera_autofocus_timeout_handler(
        request: Request,
        error: CameraAutofocusTimeout,
    ) -> JSONResponse:
        """Translate the fixed autofocus deadline to 504."""
        del request
        return _json_error(
            status.HTTP_504_GATEWAY_TIMEOUT,
            ErrorResponse(
                code="camera_timeout",
                message=str(error),
                details={"operation": "autofocus"},
            ),
        )

    @app.exception_handler(CameraUnavailable)
    async def camera_unavailable_handler(
        request: Request,
        error: CameraUnavailable,
    ) -> JSONResponse:
        """Translate unavailable camera state to 503."""
        del request
        return _camera_hardware_error(error)

    @app.exception_handler(CameraNotReady)
    async def camera_not_ready_handler(
        request: Request,
        error: CameraNotReady,
    ) -> JSONResponse:
        """Translate a missing first stream frame to 503."""
        del request
        return _camera_hardware_error(error)

    @app.exception_handler(CameraOperationError)
    async def camera_operation_error_handler(
        request: Request,
        error: CameraOperationError,
    ) -> JSONResponse:
        """Translate an expected camera provider failure to 503."""
        del request
        return _camera_hardware_error(error)

    @app.exception_handler(PinNotOpen)
    async def pin_not_open_handler(
        request: Request,
        error: PinNotOpen,
    ) -> JSONResponse:
        """Translate an unknown pin lookup to a 404 response."""
        del request
        return _json_error(
            status.HTTP_404_NOT_FOUND,
            ErrorResponse(
                code="pin_not_open",
                message=str(error),
                details={"pin": error.pin},
            ),
        )

    @app.exception_handler(PinModeConflict)
    async def pin_mode_conflict_handler(
        request: Request,
        error: PinModeConflict,
    ) -> JSONResponse:
        """Translate an incompatible pin operation to a 409 response."""
        del request
        return _json_error(
            status.HTTP_409_CONFLICT,
            ErrorResponse(
                code="pin_mode_conflict",
                message=str(error),
                details={
                    "pin": error.pin,
                    "active_mode": error.mode.value,
                    "requested_mode": error.requested_mode.value,
                },
            ),
        )

    @app.exception_handler(PinAlreadyOpen)
    async def pin_already_open_handler(
        request: Request,
        error: PinAlreadyOpen,
    ) -> JSONResponse:
        """Translate a provider reservation collision to a 409 response."""
        del request
        return _json_error(
            status.HTTP_409_CONFLICT,
            ErrorResponse(
                code="pin_already_open",
                message=str(error),
                details={"pin": error.pin},
            ),
        )

    @app.exception_handler(GpioHardwareError)
    async def gpio_hardware_error_handler(
        request: Request,
        error: GpioHardwareError,
    ) -> JSONResponse:
        """Translate a physical provider failure to a 503 response."""
        del request
        return _json_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorResponse(
                code="hardware_unavailable",
                message=str(error),
                details={"pin": error.pin, "operation": error.operation},
            ),
        )

    @app.exception_handler(PinDeviceClosed)
    async def pin_device_closed_handler(
        request: Request,
        error: PinDeviceClosed,
    ) -> JSONResponse:
        """Translate an unexpectedly closed device to a 503 response."""
        del request
        return _json_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorResponse(
                code="hardware_unavailable",
                message=str(error),
                details={"pin": error.pin, "operation": "access device"},
            ),
        )

    @app.exception_handler(GpioProviderUnavailable)
    async def gpio_provider_unavailable_handler(
        request: Request,
        error: GpioProviderUnavailable,
    ) -> JSONResponse:
        """Translate an unavailable provider to a 503 response."""
        del request
        return _json_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorResponse(
                code="hardware_unavailable",
                message=str(error),
                details={"provider": error.provider},
            ),
        )

    @app.exception_handler(GpioProviderError)
    async def gpio_provider_error_handler(
        request: Request,
        error: GpioProviderError,
    ) -> JSONResponse:
        """Translate a provider-wide lifecycle failure to a 503 response."""
        del request
        return _json_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorResponse(
                code="hardware_unavailable",
                message=str(error),
                details={
                    "provider": error.provider,
                    "operation": error.operation,
                },
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """Return FastAPI request validation failures in the shared schema."""
        del request
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return _json_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ErrorResponse(
                code="validation_error",
                message="Request validation failed",
                details={"errors": errors},
            ),
        )
