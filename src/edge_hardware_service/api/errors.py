"""HTTP rendering and OpenAPI metadata for application errors."""

from typing import Any, Final

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from edge_hardware_service.errors import AppError, ErrorCode, InvalidRequestError
from edge_hardware_service.models.errors import ErrorResponse

APP_ERROR_STATUS_CODES: Final[dict[ErrorCode, int]] = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "conflict": status.HTTP_409_CONFLICT,
    "invalid_request": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "hardware_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "operation_timeout": status.HTTP_504_GATEWAY_TIMEOUT,
}

NOT_FOUND_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "A resource required by the operation was not found.",
}
CONFLICT_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The operation conflicts with the current resource state.",
}
INVALID_REQUEST_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The path, body, or requested capability is invalid.",
}
HARDWARE_UNAVAILABLE_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The selected hardware provider could not complete the operation.",
}
OPERATION_TIMEOUT_RESPONSE: dict[str, Any] = {
    "model": ErrorResponse,
    "description": "The hardware operation exceeded its fixed timeout.",
}


def _app_error_response(error: AppError) -> JSONResponse:
    """Render one expected application failure with the public schema."""
    payload = ErrorResponse(
        code=error.code,
        message=error.message,
        details=error.details,
    )
    return JSONResponse(
        status_code=APP_ERROR_STATUS_CODES[error.code],
        content=payload.model_dump(mode="json", exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register one application-error handler and the FastAPI adapter."""

    @app.exception_handler(AppError)
    async def app_error_handler(
        request: Request,
        error: AppError,
    ) -> JSONResponse:
        """Render every expected application failure consistently."""
        del request
        return _app_error_response(error)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        """Adapt FastAPI request validation to the application error contract."""
        del request
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"]),
                "message": item["msg"],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return _app_error_response(
            InvalidRequestError(
                "Request validation failed",
                details={"errors": errors},
            )
        )
