"""HTTP error translation and OpenAPI error metadata for the API."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from edge_hardware_service.hardware.gpio.exceptions import (
    GpioHardwareError,
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
    "description": "The selected GPIO provider could not complete the operation.",
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


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized translations from domain errors to HTTP responses.

    Args:
        app: FastAPI application receiving the exception handlers.
    """

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
