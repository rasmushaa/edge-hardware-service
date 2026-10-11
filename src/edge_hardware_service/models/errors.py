"""Pydantic schema for stable API error responses."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from edge_hardware_service.errors import ErrorCode


class ErrorResponse(BaseModel):
    """Stable machine-readable and human-readable API error."""

    code: ErrorCode = Field(
        description="Stable machine-readable error code.",
        examples=[
            "not_found",
            "conflict",
            "invalid_request",
            "hardware_unavailable",
            "operation_timeout",
        ],
    )
    message: str = Field(description="Human-readable explanation of the error.")
    details: dict[str, JsonValue] | None = Field(
        default=None,
        description="Optional structured context about the failure.",
    )

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "code": "not_found",
                    "message": "GPIO pin 17 is not open",
                    "details": {"component": "gpio", "pin": 17},
                },
                {
                    "code": "conflict",
                    "message": "GPIO pin 17 is open as output, not input",
                    "details": {
                        "component": "gpio",
                        "pin": 17,
                        "active_mode": "output",
                        "requested_mode": "input",
                    },
                },
                {
                    "code": "invalid_request",
                    "message": "Request validation failed",
                    "details": {
                        "errors": [
                            {
                                "field": "body.duty_cycle",
                                "message": ("Input should be less than or equal to 1"),
                                "type": "less_than_equal",
                            }
                        ]
                    },
                },
                {
                    "code": "hardware_unavailable",
                    "message": "The GPIO provider could not access pin 18.",
                    "details": {
                        "component": "gpio",
                        "pin": 18,
                        "operation": "open PWM output",
                    },
                },
                {
                    "code": "operation_timeout",
                    "message": "Autofocus did not complete within 10 seconds",
                    "details": {
                        "component": "camera",
                        "operation": "autofocus",
                    },
                },
            ]
        },
    )
