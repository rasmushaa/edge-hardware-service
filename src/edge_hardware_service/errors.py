"""Application errors shared by services, hardware adapters, and the API."""

from typing import ClassVar, Literal, TypeAlias

from pydantic import JsonValue

ErrorCode: TypeAlias = Literal[
    "not_found",
    "conflict",
    "camera_not_connected",
    "invalid_request",
    "hardware_unavailable",
    "operation_timeout",
]
ErrorDetails: TypeAlias = dict[str, JsonValue]


class AppError(Exception):
    """Base class for an expected application failure.

    HTTP concerns deliberately stay outside this hierarchy. Each subclass
    selects a stable public code while the raise site supplies the useful
    domain-specific message and structured context.

    Attributes:
        code: Stable machine-readable public error code.
        message: Human-readable explanation of the failure.
        details: Optional JSON-safe context about the failed operation.
    """

    code: ClassVar[ErrorCode]

    def __init__(
        self,
        message: str,
        details: ErrorDetails | None = None,
    ) -> None:
        """Initialize an expected application failure."""
        self.message = message
        self.details = details
        super().__init__(message)


class NotFoundError(AppError):
    """An application resource required by the operation was not found."""

    code = "not_found"


class ConflictError(AppError):
    """The request conflicts with the current application state."""

    code = "conflict"


class CameraNotConnectedError(AppError):
    """A camera operation requires an intentionally disconnected camera."""

    code = "camera_not_connected"


class InvalidRequestError(AppError):
    """The request is valid JSON but cannot be applied as requested."""

    code = "invalid_request"


class HardwareUnavailableError(AppError):
    """A hardware component or provider cannot complete the operation."""

    code = "hardware_unavailable"


class OperationTimeoutError(AppError):
    """An expected hardware operation exceeded its deadline."""

    code = "operation_timeout"
