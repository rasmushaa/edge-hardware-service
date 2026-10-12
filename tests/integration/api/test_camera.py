"""HTTP contract tests for the simulation-backed camera API."""

import builtins
from collections.abc import Iterator
from types import SimpleNamespace

import piexif
import pytest
from fastapi.testclient import TestClient

from edge_hardware_service.api.dependencies import get_camera_service
from edge_hardware_service.config import Settings
from edge_hardware_service.errors import OperationTimeoutError
from edge_hardware_service.hardware.camera.jpeg import jpeg_dimensions
from edge_hardware_service.hardware.camera.protocols import CameraDevice
from edge_hardware_service.hardware.camera.simulation_factory import (
    SimulationCameraDevice,
)
from edge_hardware_service.main import create_app
from edge_hardware_service.services.camera import CameraFrame


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(hardware_backend="simulation"))
    with TestClient(app) as test_client:
        yield test_client


def test_status_returns_complete_simulation_state(client: TestClient) -> None:
    response = client.get("/api/v1/camera")

    assert response.status_code == 200
    assert response.json() == {
        "backend": "simulation",
        "state": "streaming",
        "device_index": None,
        "device_model": "simulation",
        "settings": {
            "fps": None,
            "sensor_resolution": None,
            "output_resolution": {"width_px": 1280, "height_px": 720},
            "rotation_degrees": 0,
            "focus": {"mode": "unmanaged"},
        },
        "stream": {
            "sensor_resolution": {"width_px": 1280, "height_px": 720},
            "output_resolution": {"width_px": 1280, "height_px": 720},
            "media_type": "multipart/x-mixed-replace; boundary=frame",
        },
        "sensor_temperature_c": 25.0,
        "focus_state": None,
        "latest_focus_succeeded": None,
        "lens_position_diopters": None,
        "unavailable_reason": None,
    }


def test_image_is_latest_broker_jpeg_with_no_cache_headers(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/camera/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert jpeg_dimensions(response.content) == (1280, 720)
    assert not hasattr(CameraDevice, "capture")


@pytest.mark.parametrize(
    ("rotation", "orientation"),
    [(0, 1), (90, 6), (180, 3), (270, 8)],
)
def test_rotation_changes_exif_only(
    client: TestClient,
    rotation: int,
    orientation: int,
) -> None:
    patch = client.patch(
        "/api/v1/camera/settings",
        json={"rotation_degrees": rotation},
    )
    image = client.get("/api/v1/camera/image")

    assert patch.status_code == 200
    assert image.status_code == 200
    assert jpeg_dimensions(image.content) == (1280, 720)
    assert piexif.load(image.content)["0th"][piexif.ImageIFD.Orientation] == (
        orientation
    )


def test_partial_settings_and_autofocus_keep_one_effective_configuration(
    client: TestClient,
) -> None:
    settings = client.patch(
        "/api/v1/camera/settings",
        json={
            "fps": 14,
            "sensor_resolution": {"width_px": 2000, "height_px": 1100},
        },
    )
    autofocus = client.post("/api/v1/camera/autofocus")
    status = client.get("/api/v1/camera")

    assert settings.status_code == 200
    assert settings.json()["settings"]["fps"] == 14.0
    assert settings.json()["settings"]["sensor_resolution"] == {
        "width_px": 2000,
        "height_px": 1100,
    }
    assert settings.json()["stream"]["sensor_resolution"] == {
        "width_px": 1280,
        "height_px": 720,
    }
    assert autofocus.status_code == 200
    assert autofocus.json() == {
        "success": True,
        "focus_state": "focused",
        "lens_position_diopters": 3.0,
    }
    assert status.json()["settings"]["focus"] == {"mode": "auto"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unexpected": True},
        {"fps": -1},
        {"pixel_binning": "none"},
        {"output_resolution": {"width_px": 1279, "height_px": 720}},
        {"rotation_degrees": 45},
        {"focus": {"mode": "manual", "lens_position_diopters": 33}},
    ],
)
def test_invalid_settings_use_shared_422_envelope(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    response = client.patch("/api/v1/camera/settings", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_mjpeg_stream_has_one_complete_part_and_no_cache_headers() -> None:
    app = create_app(Settings(hardware_backend="simulation"))

    class FinishedBroker:
        def wait_for_frame(self, **kwargs: object) -> None:
            del kwargs
            return None

    class FinishedStreamService:
        frames = FinishedBroker()

        def wait_for_frame(self) -> CameraFrame:
            return CameraFrame(
                jpeg=b"\xff\xd8camera-frame\xff\xd9",
                sequence=1,
                captured_at=SimpleNamespace(),  # type: ignore[arg-type]
                width=1280,
                height=720,
            )

        def status(self) -> SimpleNamespace:
            return SimpleNamespace(state="stopped")

    app.dependency_overrides[get_camera_service] = FinishedStreamService
    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/camera/stream")

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "multipart/x-mixed-replace; boundary=frame"
    )
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["x-accel-buffering"] == "no"
    assert response.content == (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: 16\r\n\r\n"
        b"\xff\xd8camera-frame\xff\xd9\r\n"
    )


def test_capabilities_are_discovered_and_complete(client: TestClient) -> None:
    response = client.get("/api/v1/camera/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["device_model"] == "simulation"
    assert body["sensor_modes"][0]["resolution"] == {
        "width_px": 1280,
        "height_px": 720,
    }
    assert body["frame_rate_control"] is True
    assert body["focus"]["modes"] == [
        "unmanaged",
        "manual",
        "auto",
        "continuous",
    ]
    assert body["observed_metadata"]["sensor_temperature_c"] is True


def test_unsupported_setting_returns_capability_error_atomically(
    client: TestClient,
) -> None:
    response = client.patch(
        "/api/v1/camera/settings",
        json={"output_resolution": {"width_px": 640, "height_px": 480}},
    )
    status_response = client.get("/api/v1/camera")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert response.json()["details"] == {
        "component": "camera",
        "operation": "validate settings",
    }
    assert status_response.json()["settings"]["output_resolution"] == {
        "width_px": 1280,
        "height_px": 720,
    }


def test_nullable_fps_resets_provider_control(client: TestClient) -> None:
    assert client.patch("/api/v1/camera/settings", json={"fps": 12}).status_code == 200
    response = client.patch("/api/v1/camera/settings", json={"fps": None})
    assert response.status_code == 200
    assert response.json()["settings"]["fps"] is None


def test_openapi_exposes_exactly_six_camera_operations(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    camera_operations = {
        (method, path)
        for path, operations in schema["paths"].items()
        if path.startswith("/api/v1/camera")
        for method in operations
    }

    assert camera_operations == {
        ("get", "/api/v1/camera"),
        ("get", "/api/v1/camera/capabilities"),
        ("patch", "/api/v1/camera/settings"),
        ("post", "/api/v1/camera/autofocus"),
        ("get", "/api/v1/camera/stream"),
        ("get", "/api/v1/camera/image"),
    }
    patch = schema["paths"]["/api/v1/camera/settings"]["patch"]
    assert set(patch["responses"]) >= {"200", "422", "503"}
    assert "504" not in patch["responses"]
    autofocus = schema["paths"]["/api/v1/camera/autofocus"]["post"]
    assert set(autofocus["responses"]) >= {"200", "422", "503", "504"}
    for status_code in ("422", "503", "504"):
        assert autofocus["responses"][status_code]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ErrorResponse"}
    examples = patch["requestBody"]["content"]["application/json"]["examples"]
    assert set(examples) == {
        "frame_rate",
        "provider_defaults",
        "sensor_hint",
        "output_resolution",
        "portrait",
        "manual_focus",
        "auto_focus_mode",
        "continuous_focus",
        "provider_managed_focus",
    }

    status_operation = schema["paths"]["/api/v1/camera"]["get"]
    capabilities_operation = schema["paths"]["/api/v1/camera/capabilities"]["get"]
    stream_operation = schema["paths"]["/api/v1/camera/stream"]["get"]
    image_operation = schema["paths"]["/api/v1/camera/image"]["get"]
    descriptions = {
        "status": " ".join(status_operation["description"].split()),
        "capabilities": " ".join(capabilities_operation["description"].split()),
        "settings": " ".join(patch["description"].split()),
        "autofocus": " ".join(autofocus["description"].split()),
        "stream": " ".join(stream_operation["description"].split()),
        "image": " ".join(image_operation["description"].split()),
    }
    assert "process-wide camera pipeline" in descriptions["status"]
    assert "does not use a camera-model allowlist" in descriptions["capabilities"]
    assert "previous settings active" in descriptions["settings"]
    assert "remains active after the request" in descriptions["autofocus"]
    assert "not a URL for another camera server" in descriptions["stream"]
    assert "not a camera still-capture" in descriptions["image"]

    components = schema["components"]["schemas"]
    for model_name in (
        "PixelResolution",
        "CameraSettings",
        "CameraSettingsPatch",
        "CameraCapabilities",
        "CameraStatus",
        "CameraStreamInfo",
        "AutofocusResult",
        "SensorModeCapability",
        "LensPositionCapability",
        "OutputCapability",
        "FocusCapability",
        "MetadataCapability",
        "UnmanagedFocus",
        "ManualFocus",
        "AutoFocus",
        "ContinuousFocus",
    ):
        assert components[model_name]["description"]
        assert components[model_name]["examples"]
        for property_schema in components[model_name].get("properties", {}).values():
            assert property_schema["description"]

    focus_schema = components["CameraSettingsPatch"]["properties"]["focus"]
    discriminator = focus_schema["anyOf"][0]["discriminator"]
    assert set(discriminator["mapping"]) == {
        "unmanaged",
        "manual",
        "auto",
        "continuous",
    }


def test_autofocus_timeout_uses_shared_504_envelope() -> None:
    app = create_app(Settings(hardware_backend="simulation"))

    class TimeoutService:
        def autofocus(self) -> None:
            raise OperationTimeoutError(
                "Autofocus did not complete within 10 seconds",
                details={"component": "camera", "operation": "autofocus"},
            )

    app.dependency_overrides[get_camera_service] = TimeoutService
    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/camera/autofocus")

    assert response.status_code == 504
    assert response.json() == {
        "code": "operation_timeout",
        "message": "Autofocus did not complete within 10 seconds",
        "details": {"component": "camera", "operation": "autofocus"},
    }


def test_camera_failure_leaves_health_and_gpio_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_start(self: SimulationCameraDevice, *args: object) -> None:
        del self, args
        raise RuntimeError("camera initialization failed")

    monkeypatch.setattr(SimulationCameraDevice, "start", fail_start)
    app = create_app(Settings(hardware_backend="simulation"))
    with TestClient(app) as test_client:
        health = test_client.get("/api/v1/health")
        gpio = test_client.get("/api/v1/gpio")
        camera = test_client.get("/api/v1/camera")
        capabilities = test_client.get("/api/v1/camera/capabilities")
        image = test_client.get("/api/v1/camera/image")

    assert health.json() == {"status": "ok"}
    assert gpio.json() == {"backend": "simulation", "count": 0, "pins": []}
    assert camera.status_code == 200
    assert camera.json()["state"] == "unavailable"
    assert capabilities.status_code == 503
    assert capabilities.json()["code"] == "hardware_unavailable"
    assert image.status_code == 503
    assert image.json()["code"] == "hardware_unavailable"


def test_simulation_startup_does_not_import_camera_provider_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "picamera2" or name.startswith("picamera2.") or name == "libcamera":
            raise AssertionError("simulation imported Raspberry Pi camera modules")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    app = create_app(Settings(hardware_backend="simulation"))
    with TestClient(app) as test_client:
        assert test_client.get("/api/v1/camera").status_code == 200
