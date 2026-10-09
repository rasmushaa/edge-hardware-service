"""Portable capability-driven Picamera2 adapter tests."""

from __future__ import annotations

import sys
import threading
import time
from enum import IntEnum
from io import BufferedIOBase
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from edge_hardware_service.hardware.camera.exceptions import (
    CameraCapabilityUnsupported,
    CameraOperationError,
)
from edge_hardware_service.hardware.camera.picamera2_device import Picamera2Device
from edge_hardware_service.models.camera import (
    AutoFocus,
    CameraSettings,
    ContinuousFocus,
    ManualFocus,
    PixelResolution,
    UnmanagedFocus,
)


class AfModeEnum(IntEnum):
    Manual = 0
    Auto = 1
    Continuous = 2


class AfTriggerEnum(IntEnum):
    Start = 0
    Cancel = 1


class FakeEncoder:
    pass


class FakeFileOutput:
    def __init__(self, output: Any) -> None:
        self.output = output

    def write(self, data: bytes) -> int:
        return self.output.write(data)


class FakeCamera:
    def __init__(self) -> None:
        self.camera_num = 0
        self.camera_properties = {"Model": "imx708_wide_noir"}
        self._camera_controls = {
            "FrameDurationLimits": ((1000, 1000), (1_000_000, 1_000_000), None),
            "AfMode": (AfModeEnum.Manual, AfModeEnum.Continuous, AfModeEnum.Manual),
            "AfTrigger": (AfTriggerEnum.Start, AfTriggerEnum.Cancel, None),
            "LensPosition": (0.0, 32.0, 1.0),
        }
        self._sensor_modes: list[dict[str, Any]] = [
            {
                "size": (1920, 1080),
                "format": "RAW10",
                "bit_depth": 10,
                "fps": 60.0,
            },
            {
                "size": (1920, 1080),
                "format": "RAW12",
                "bit_depth": 12,
                "fps": 15.0,
            },
            {
                "size": (4608, 2592),
                "format": "RAW10",
                "bit_depth": 10,
                "fps": 14.0,
            },
        ]
        self.events: list[str] = []
        self.configurations: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []
        self.started = 0
        self.stopped = 0
        self.closed = 0
        self.output: Any = None
        self.post_callback: Any = None
        self.adjust_output_to: tuple[int, int] | None = None

    @property
    def sensor_modes(self) -> list[dict[str, Any]]:
        self.events.append("sensor_modes")
        return self._sensor_modes

    @property
    def camera_controls(self) -> dict[str, Any]:
        self.events.append("camera_controls")
        return self._camera_controls

    def create_video_configuration(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append("create_configuration")
        config = dict(kwargs)
        config["main"] = dict(kwargs["main"])
        if self.adjust_output_to is not None:
            config["main"]["size"] = self.adjust_output_to
        return config

    def configure(self, configuration: dict[str, Any]) -> None:
        self.configurations.append(configuration)

    def camera_configuration(self) -> dict[str, Any]:
        return self.configurations[-1]

    def start_recording(self, encoder: Any, output: Any) -> None:
        del encoder
        self.started += 1
        self.output = output

    def stop_recording(self) -> None:
        self.stopped += 1

    def set_controls(self, controls: dict[str, Any]) -> None:
        self.controls.append(controls)

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeCamera:
    camera = FakeCamera()
    picamera2 = ModuleType("picamera2")
    picamera2.__path__ = []  # type: ignore[attr-defined]
    picamera2.Picamera2 = lambda camera_num=0: camera  # type: ignore[attr-defined]
    encoders = ModuleType("picamera2.encoders")
    encoders.MJPEGEncoder = FakeEncoder  # type: ignore[attr-defined]
    outputs = ModuleType("picamera2.outputs")
    outputs.FileOutput = FakeFileOutput  # type: ignore[attr-defined]
    libcamera = ModuleType("libcamera")
    libcamera.controls = SimpleNamespace(  # type: ignore[attr-defined]
        AfModeEnum=AfModeEnum,
        AfTriggerEnum=AfTriggerEnum,
    )
    monkeypatch.setitem(sys.modules, "picamera2", picamera2)
    monkeypatch.setitem(sys.modules, "picamera2.encoders", encoders)
    monkeypatch.setitem(sys.modules, "picamera2.outputs", outputs)
    monkeypatch.setitem(sys.modules, "libcamera", libcamera)
    return camera


def settings(
    *,
    fps: float | None = None,
    sensor: tuple[int, int] | None = None,
    output: tuple[int, int] = (1280, 720),
    focus: object | None = None,
) -> CameraSettings:
    return CameraSettings(
        fps=fps,
        sensor_resolution=(
            None
            if sensor is None
            else PixelResolution(width_px=sensor[0], height_px=sensor[1])
        ),
        output_resolution=PixelResolution(width_px=output[0], height_px=output[1]),
        rotation_degrees=0,
        focus=focus or UnmanagedFocus(mode="unmanaged"),  # type: ignore[arg-type]
    )


def test_arbitrary_model_discovers_capabilities_before_default_stream(
    fake_provider: FakeCamera,
) -> None:
    received: list[bytes] = []
    device = Picamera2Device()

    device.start(settings(), received.append)

    config = fake_provider.configurations[0]
    assert fake_provider.events[:2] == ["sensor_modes", "camera_controls"]
    assert config["main"] == {"size": (1280, 720), "format": "YUV420"}
    assert "sensor" not in config
    assert "controls" not in config
    assert device.device_model == "imx708_wide_noir"
    assert device.capabilities.frame_rate_control is True
    assert device.capabilities.focus.modes == (
        "unmanaged",
        "manual",
        "auto",
        "continuous",
    )
    assert isinstance(fake_provider.output.output, BufferedIOBase)
    assert fake_provider.output.output.writable() is True
    fake_provider.output.write(b"\xff\xd8jpeg\xff\xd9")
    assert received == [b"\xff\xd8jpeg\xff\xd9"]
    device.close()


def test_requested_resolution_uses_quality_first_mode_that_meets_fps(
    fake_provider: FakeCamera,
) -> None:
    device = Picamera2Device()
    device.start(settings(sensor=(1920, 1080), fps=10), lambda _: None)
    assert fake_provider.configurations[-1]["sensor"] == {
        "output_size": (1920, 1080),
        "bit_depth": 12,
    }
    device.close()

    second = Picamera2Device()
    second.start(settings(sensor=(1920, 1080), fps=30), lambda _: None)
    assert fake_provider.configurations[-1]["sensor"] == {
        "output_size": (1920, 1080),
        "bit_depth": 10,
    }
    second.close()


def test_fixed_focus_and_non_raw_camera_starts_unmanaged(
    fake_provider: FakeCamera,
) -> None:
    fake_provider._camera_controls = {}
    fake_provider._sensor_modes = [{"format": "YUYV"}]
    device = Picamera2Device()

    device.start(settings(), lambda _: None)

    assert device.capabilities.focus.modes == ("unmanaged",)
    assert device.capabilities.sensor_modes[0].resolution is None
    with pytest.raises(CameraCapabilityUnsupported, match="focus mode"):
        device.validate_settings(settings(focus=ContinuousFocus(mode="continuous")))
    with pytest.raises(CameraCapabilityUnsupported, match="sensor resolution"):
        device.validate_settings(settings(sensor=(640, 480)))
    device.close()


def test_unsupported_settings_do_not_call_provider(fake_provider: FakeCamera) -> None:
    fake_provider._camera_controls = {}
    device = Picamera2Device()
    device.start(settings(), lambda _: None)
    before = (len(fake_provider.configurations), len(fake_provider.controls))

    with pytest.raises(CameraCapabilityUnsupported, match="frame-rate"):
        device.reconfigure(settings(fps=10))

    assert (len(fake_provider.configurations), len(fake_provider.controls)) == before
    device.close()


def test_inexact_output_is_rejected_before_configure(fake_provider: FakeCamera) -> None:
    fake_provider.adjust_output_to = (640, 478)
    device = Picamera2Device()

    with pytest.raises(CameraCapabilityUnsupported, match="adjusted"):
        device.start(settings(output=(640, 480)), lambda _: None)

    assert fake_provider.configurations == []
    device.close()


def test_reset_to_provider_defaults_restarts_without_controls(
    fake_provider: FakeCamera,
) -> None:
    device = Picamera2Device()
    device.start(
        settings(
            fps=25,
            focus=ContinuousFocus(mode="continuous"),
        ),
        lambda _: None,
    )

    device.reconfigure(settings())

    assert fake_provider.stopped == 1
    assert fake_provider.started == 2
    assert "controls" not in fake_provider.configurations[-1]
    device.close()


def test_manual_focus_and_metadata_capabilities(fake_provider: FakeCamera) -> None:
    device = Picamera2Device()
    device.start(
        settings(focus=ManualFocus(mode="manual", lens_position_diopters=4.5)),
        lambda _: None,
    )
    fake_provider.post_callback(
        SimpleNamespace(
            get_metadata=lambda: {
                "SensorTemperature": 37.25,
                "AfState": 2,
                "LensPosition": 8.0,
            }
        )
    )

    assert device.telemetry.sensor_temperature_c == 37.25
    assert device.telemetry.focus_state == "focused"
    assert device.capabilities.observed_metadata.model_dump() == {
        "sensor_temperature_c": True,
        "focus_state": True,
        "lens_position_diopters": True,
    }
    device.close()


def test_missing_metadata_stays_null(fake_provider: FakeCamera) -> None:
    device = Picamera2Device()
    device.start(settings(), lambda _: None)
    fake_provider.post_callback(SimpleNamespace(get_metadata=lambda: {}))

    assert device.telemetry.model_dump() == {
        "sensor_temperature_c": None,
        "focus_state": None,
        "lens_position_diopters": None,
        "latest_focus_succeeded": None,
    }
    device.close()


def test_autofocus_waits_for_scanning_then_terminal_metadata(
    fake_provider: FakeCamera,
) -> None:
    device = Picamera2Device()
    device.start(settings(focus=AutoFocus(mode="auto")), lambda _: None)
    result: list[bool] = []
    worker = threading.Thread(target=lambda: result.append(device.autofocus(2)))
    worker.start()
    for _ in range(100):
        if fake_provider.controls:
            break
        time.sleep(0.005)
    metadata = lambda state: SimpleNamespace(  # noqa: E731
        get_metadata=lambda: {"AfState": state, "LensPosition": 8.0}
    )
    fake_provider.post_callback(metadata(1))
    fake_provider.post_callback(metadata(2))
    worker.join(timeout=1)

    assert result == [True]
    assert fake_provider.controls[-1]["AfTrigger"] == AfTriggerEnum.Start
    device.close()


def test_close_is_idempotent_and_closed_device_rejects_start(
    fake_provider: FakeCamera,
) -> None:
    device = Picamera2Device()
    device.start(settings(), lambda _: None)
    device.close()
    device.close()

    assert fake_provider.stopped == 1
    assert fake_provider.closed == 1
    with pytest.raises(CameraOperationError, match="closed"):
        device.start(settings(), lambda _: None)


def test_capability_discovery_failure_preserves_provider_reason(
    fake_provider: FakeCamera,
) -> None:
    class BrokenModes:
        def __iter__(self) -> object:
            raise OSError(12, "Cannot allocate memory")

    fake_provider._sensor_modes = BrokenModes()  # type: ignore[assignment]
    device = Picamera2Device()

    assert device.capabilities.sensor_modes == ()
    assert device.capabilities.discovery_warnings == (
        "sensor mode discovery failed; provider-managed streaming remains "
        "available: OSError: [Errno 12] Cannot allocate memory",
    )
    assert fake_provider.closed == 1
    device.start(settings(), lambda _: None)
    assert "sensor" not in fake_provider.configurations[-1]
    device.close()
