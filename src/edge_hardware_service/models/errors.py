"""Pydantic schema for stable API error responses."""

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue


ErrorCode: TypeAlias = Literal[
    "pin_not_open",
    "pin_mode_conflict",
    "pin_already_open",
    "validation_error",
    "hardware_unavailable",
]


class ErrorResponse(BaseModel):
    """Stable machine-readable and human-readable API error."""

    code: ErrorCode = Field(
        description="Stable machine-readable error code.",
        examples=[
            "pin_not_open",
            "pin_mode_conflict",
            "pin_already_open",
            "validation_error",
            "hardware_unavailable",
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
                    "code": "pin_not_open",
                    "message": "GPIO pin 17 is not open",
                    "details": {"pin": 17},
                },
                {
                    "code": "pin_mode_conflict",
                    "message": "GPIO pin 17 is open as output, not input",
                    "details": {
                        "pin": 17,
                        "active_mode": "output",
                        "requested_mode": "input",
                    },
                },
                {
                    "code": "pin_already_open",
                    "message": "GPIO pin 17 is already open",
                    "details": {"pin": 17},
                },
                {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {
                        "errors": [
                            {
                                "field": "body.duty_cycle",
                                "message": (
                                    "Input should be less than or equal to 1"
                                ),
                                "type": "less_than_equal",
                            }
                        ]
                    },
                },
                {
                    "code": "hardware_unavailable",
                    "message": "The GPIO provider could not access pin 18.",
                    "details": {"pin": 18, "operation": "open PWM output"},
                },
            ]
        },
    )
