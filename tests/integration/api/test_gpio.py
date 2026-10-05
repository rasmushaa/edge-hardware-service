"""HTTP integration tests for the simulation-backed GPIO API."""

import builtins
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from edge_hardware_service.config import Settings
from edge_hardware_service.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Run the application lifespan around a simulation TestClient."""
    app = create_app(Settings(hardware_backend="simulation"))
    with TestClient(app) as test_client:
        yield test_client


def test_complete_gpio_workflow(client: TestClient) -> None:
    """Exercise registry, I/O, reconfiguration, conflict, and release behavior."""
    assert client.get("/api/v1/gpio").json() == {
        "backend": "simulation",
        "count": 0,
        "pins": [],
    }

    missing = client.get("/api/v1/gpio/17")
    assert missing.status_code == 404
    assert missing.json() == {
        "code": "pin_not_open",
        "message": "GPIO pin 17 is not open",
        "details": {"pin": 17},
    }

    digital = client.put("/api/v1/gpio/17/value", json={"value": True})
    assert digital.status_code == 200
    assert digital.json() == {
        "pin": 17,
        "mode": "output",
        "value": True,
        "configuration_source": "implicit",
    }
    assert client.get("/api/v1/gpio/17").json() == digital.json()

    conflict = client.get("/api/v1/gpio/17/value")
    assert conflict.status_code == 409
    assert conflict.json()["details"] == {
        "pin": 17,
        "active_mode": "output",
        "requested_mode": "input",
    }

    configured = client.put(
        "/api/v1/gpio/17/configuration",
        json={"mode": "input", "pull": "up"},
    )
    assert configured.status_code == 200
    assert configured.json() == {
        "pin": 17,
        "mode": "input",
        "value": True,
        "pull": "up",
        "configuration_source": "explicit",
    }
    assert client.get("/api/v1/gpio/17/value").json() == {
        "pin": 17,
        "value": True,
    }

    pwm = client.put(
        "/api/v1/gpio/18/pwm",
        json={"duty_cycle": 0.25, "frequency_hz": 500.0},
    )
    assert pwm.status_code == 200
    assert pwm.json() == {
        "pin": 18,
        "mode": "pwm",
        "duty_cycle": 0.25,
        "frequency_hz": 500.0,
        "configuration_source": "implicit",
    }

    registry = client.get("/api/v1/gpio").json()
    assert registry == {
        "backend": "simulation",
        "count": 2,
        "pins": [configured.json(), pwm.json()],
    }

    assert client.delete("/api/v1/gpio/17").json() == {
        "pin": 17,
        "released": True,
    }
    assert client.delete("/api/v1/gpio/17").json() == {
        "pin": 17,
        "released": False,
    }


@pytest.mark.parametrize(
    ("method", "path", "payload", "field"),
    [
        ("get", "/api/v1/gpio/-1", None, "path.pin"),
        (
            "put",
            "/api/v1/gpio/17/value",
            {"value": "high"},
            "body.value",
        ),
        (
            "put",
            "/api/v1/gpio/18/pwm",
            {"duty_cycle": 1.1},
            "body.duty_cycle",
        ),
        (
            "put",
            "/api/v1/gpio/17/configuration",
            {"mode": "output", "pull": "up"},
            "body",
        ),
    ],
)
def test_validation_errors_use_the_public_error_schema(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    field: str,
) -> None:
    """Path and body validation should share one stable error envelope."""
    response = client.request(method, path, json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert body["details"]["errors"][0]["field"] == field


def test_openapi_exposes_all_gpio_operations_and_named_examples(
    client: TestClient,
) -> None:
    """The generated contract should retain routes and selectable examples."""
    schema = client.get("/openapi.json").json()
    gpio_operations = {
        (method, path)
        for path, operations in schema["paths"].items()
        if path.startswith("/api/v1/gpio")
        for method in operations
    }
    assert gpio_operations == {
        ("get", "/api/v1/gpio"),
        ("get", "/api/v1/gpio/{pin}"),
        ("delete", "/api/v1/gpio/{pin}"),
        ("put", "/api/v1/gpio/{pin}/configuration"),
        ("get", "/api/v1/gpio/{pin}/value"),
        ("put", "/api/v1/gpio/{pin}/value"),
        ("put", "/api/v1/gpio/{pin}/pwm"),
    }

    configuration = schema["paths"]["/api/v1/gpio/{pin}/configuration"]["put"]
    examples = configuration["requestBody"]["content"]["application/json"]["examples"]
    assert set(examples) == {
        "input_without_pull",
        "input_with_pull_up",
        "input_with_pull_down",
        "digital_output",
        "pwm_with_provider_frequency",
        "pwm_with_custom_frequency",
    }


def test_health_endpoint_uses_the_versioned_prefix(client: TestClient) -> None:
    """The basic health route should start with the same API version prefix."""
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_simulation_startup_does_not_import_raspberry_pi_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulation lifespan must not load the optional GPIO Zero adapter."""
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        """Fail if simulation startup attempts the Raspberry Pi import."""
        if name == ("edge_hardware_service.hardware.gpio.gpiozero_factory"):
            raise AssertionError("simulation imported the Raspberry Pi backend")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    app = create_app(Settings(hardware_backend="simulation"))
    with TestClient(app) as simulation_client:
        response = simulation_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
