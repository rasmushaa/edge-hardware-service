"""Opt-in capability-driven camera tests on a Raspberry Pi 5."""

from __future__ import annotations

from pathlib import Path
from threading import Event, Lock
from time import monotonic

import piexif
import pytest

from edge_hardware_service.api.routers.camera import _mjpeg_part, get_camera_image
from edge_hardware_service.errors import HardwareUnavailableError
from edge_hardware_service.hardware.camera.picamera2_device import Picamera2Device
from edge_hardware_service.models.camera import (
    AutoFocus,
    CameraSettings,
    CameraSettingsPatch,
    ContinuousFocus,
    ManualFocus,
    PixelResolution,
    UnmanagedFocus,
)
from edge_hardware_service.services.camera import CameraService

pytestmark = [pytest.mark.rpi, pytest.mark.camera_rpi]


def _settings(
    *,
    sensor_resolution: PixelResolution | None = None,
    fps: float | None = None,
    focus: object | None = None,
    rotation: int = 0,
) -> CameraSettings:
    return CameraSettings(
        fps=fps,
        sensor_resolution=sensor_resolution,
        output_resolution=PixelResolution(width_px=1280, height_px=720),
        rotation_degrees=rotation,  # type: ignore[arg-type]
        focus=focus or UnmanagedFocus(mode="unmanaged"),  # type: ignore[arg-type]
    )


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read JPEG SOF dimensions without an optional imaging dependency."""
    assert data.startswith(b"\xff\xd8"), "encoder output is not a JPEG"
    position = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB}
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        position += 2
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        segment_length = int.from_bytes(data[position : position + 2], "big")
        if marker in sof_markers:
            height = int.from_bytes(data[position + 3 : position + 5], "big")
            width = int.from_bytes(data[position + 5 : position + 7], "big")
            return width, height
        position += segment_length
    raise AssertionError("JPEG frame has no supported start-of-frame marker")


def _assert_pi5_bookworm() -> None:
    model_path = Path("/proc/device-tree/model")
    assert model_path.exists(), "this test must run on a Raspberry Pi"
    model = model_path.read_bytes().replace(b"\x00", b"").decode()
    assert "Raspberry Pi 5" in model, f"expected Raspberry Pi 5, got {model!r}"
    os_release = Path("/etc/os-release").read_text(encoding="utf-8").lower()
    assert "bookworm" in os_release, "camera validation requires Bookworm"


def test_pi5_provider_selected_stream_controls_metadata_and_cleanup() -> None:
    _assert_pi5_bookworm()
    frames: list[bytes] = []
    frame_lock = Lock()
    frame_event = Event()

    def publish(frame: bytes) -> None:
        with frame_lock:
            frames.append(frame)
        frame_event.set()

    device = Picamera2Device(device_index=0)
    assert device.device_index == 0
    assert device.device_model
    try:
        device.start(_settings(), publish)
        _wait_for_frames(frames, frame_lock, frame_event, minimum=3)
        assert all(_jpeg_dimensions(frame) == (1280, 720) for frame in frames[-3:])
        capabilities = device.capabilities
        assert capabilities.device_model == device.device_model

        assert capabilities.sensor_modes == ()
        applied_sensor = (
            device.stream_info.sensor_resolution if device.stream_info else None
        )
        if applied_sensor is not None:
            fps = 30.0 if capabilities.frame_rate_control else None
            device.reconfigure(_settings(sensor_resolution=applied_sensor, fps=fps))
            _wait_for_frames(frames, frame_lock, frame_event, minimum=4)

        if "continuous" in capabilities.focus.modes:
            device.reconfigure(_settings(focus=ContinuousFocus(mode="continuous")))
        lens_range = device.lens_position_range
        if "manual" in capabilities.focus.modes and lens_range is not None:
            device.reconfigure(
                _settings(
                    focus=ManualFocus(
                        mode="manual",
                        lens_position_diopters=sum(lens_range) / 2,
                    )
                )
            )
        if "auto" in capabilities.focus.modes:
            device.reconfigure(_settings(focus=AutoFocus(mode="auto")))
            result = device.autofocus(timeout_seconds=10.0)
            assert isinstance(result, bool)
            assert device.telemetry.latest_focus_succeeded is result
        assert device.telemetry.sensor_temperature_c is None or isinstance(
            device.telemetry.sensor_temperature_c, float
        )
    finally:
        device.close()
        device.close()


def _wait_for_frames(
    frames: list[bytes],
    frame_lock: Lock,
    frame_event: Event,
    *,
    minimum: int,
) -> None:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with frame_lock:
            if len(frames) >= minimum:
                return
        frame_event.wait(0.1)
        frame_event.clear()
    with frame_lock:
        assert len(frames) >= minimum, "continuous camera stream stalled"


def test_missing_camera_is_reported_as_unavailable() -> None:
    _assert_pi5_bookworm()
    try:
        device = Picamera2Device(device_index=0)
    except HardwareUnavailableError:
        pytest.fail("a Picamera2-compatible camera at index 0 is required")
    try:
        assert device.device_model
        assert device.capabilities.device_index == 0
    finally:
        device.close()


def test_physical_broker_rotation_and_multipart_delivery() -> None:
    """Verify physical frames pass through the shared broker and EXIF path."""
    _assert_pi5_bookworm()
    service = CameraService(Picamera2Device(device_index=0), backend="rpi")
    try:
        camera_status = service.status()
        assert camera_status.state == "streaming", camera_status.unavailable_reason
        for rotation, expected_orientation in {
            0: 1,
            90: 6,
            180: 3,
            270: 8,
        }.items():
            service.update_settings(
                CameraSettingsPatch(rotation_degrees=rotation)  # type: ignore[arg-type]
            )
            frame = service.wait_for_frame()
            assert _jpeg_dimensions(frame.jpeg) == (1280, 720)
            exif = piexif.load(frame.jpeg)
            assert exif["0th"][piexif.ImageIFD.Orientation] == expected_orientation

            image_response = get_camera_image(service)
            assert image_response.body == frame.jpeg
            assert image_response.media_type == "image/jpeg"

            multipart = _mjpeg_part(frame)
            assert multipart.startswith(b"--frame\r\nContent-Type: image/jpeg\r\n")
            assert frame.jpeg in multipart
            assert multipart.endswith(b"\r\n")
    finally:
        service.close()
        service.close()
