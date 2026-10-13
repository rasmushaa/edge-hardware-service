"""Tests for the shared expected-failure hierarchy and HTTP translation."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edge_hardware_service.api.errors import (
    APP_ERROR_STATUS_CODES,
    _app_error_response,
    register_exception_handlers,
)
from edge_hardware_service.errors import (
    AppError,
    CameraNotConnectedError,
    ConflictError,
    HardwareUnavailableError,
    InvalidRequestError,
    NotFoundError,
    OperationTimeoutError,
)


@pytest.mark.parametrize(
    ("error_type", "code", "status_code"),
    [
        (NotFoundError, "not_found", 404),
        (ConflictError, "conflict", 409),
        (CameraNotConnectedError, "camera_not_connected", 409),
        (InvalidRequestError, "invalid_request", 422),
        (HardwareUnavailableError, "hardware_unavailable", 503),
        (OperationTimeoutError, "operation_timeout", 504),
    ],
)
def test_app_error_categories_render_with_their_public_contract(
    error_type: type[AppError],
    code: str,
    status_code: int,
) -> None:
    error = error_type("example failure", details={"component": "camera"})

    response = _app_error_response(error)

    assert error.code == code
    assert str(error) == "example failure"
    assert response.status_code == status_code
    assert json.loads(response.body) == {
        "code": code,
        "message": "example failure",
        "details": {"component": "camera"},
    }


def test_status_mapping_is_exhaustive_and_absent_details_are_omitted() -> None:
    assert APP_ERROR_STATUS_CODES == {
        "not_found": 404,
        "conflict": 409,
        "camera_not_connected": 409,
        "invalid_request": 422,
        "hardware_unavailable": 503,
        "operation_timeout": 504,
    }

    response = _app_error_response(NotFoundError("missing"))

    assert json.loads(response.body) == {
        "code": "not_found",
        "message": "missing",
    }


def test_unexpected_exception_remains_an_opaque_500() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("private implementation detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "private implementation detail" not in response.text
