"""Portable tests for the packaged simulation camera and JPEG metadata."""

from importlib.resources import files
from threading import Event
from time import monotonic

import piexif

from edge_hardware_service.hardware.camera.jpeg import (
    jpeg_dimensions,
    set_exif_orientation,
)
from edge_hardware_service.hardware.camera.simulation_factory import (
    SIMULATION_CLIP_RESOURCE,
    SimulationCameraDevice,
    _split_mjpeg,
)
from edge_hardware_service.models.camera import (
    AutoFocus,
    CameraSettings,
    PixelResolution,
    UnmanagedFocus,
)


def settings(fps: float | None = None) -> CameraSettings:
    return CameraSettings(
        fps=fps,
        sensor_resolution=None,
        output_resolution=PixelResolution(width_px=1280, height_px=720),
        rotation_degrees=0,
        focus=UnmanagedFocus(mode="unmanaged"),
    )


def test_packaged_clip_contains_all_300_distinct_hd_jpegs() -> None:
    resource = files("edge_hardware_service.hardware.camera").joinpath(
        SIMULATION_CLIP_RESOURCE
    )
    clip = resource.read_bytes()
    frames = _split_mjpeg(clip)

    assert resource.is_file()
    assert clip.startswith(b"\xff\xd8")
    assert clip.endswith(b"\xff\xd9")
    assert len(frames) == 300
    assert len(set(frames)) == 300
    assert all(jpeg_dimensions(frame) == (1280, 720) for frame in frames)


def test_simulation_publishes_distinct_frames_at_the_configured_pace() -> None:
    observed: list[bytes] = []
    received = Event()
    device = SimulationCameraDevice()

    def publish(frame: bytes) -> None:
        observed.append(frame)
        if len(observed) >= 26:
            received.set()

    started = monotonic()
    device.start(settings(fps=56), publish)
    try:
        assert received.wait(1)
    finally:
        device.close()

    elapsed = monotonic() - started
    assert len(set(observed[:26])) == 26
    assert elapsed >= 24 / 56 * 0.8


def test_simulation_telemetry_and_focus_are_deterministic() -> None:
    device = SimulationCameraDevice()
    device.start(settings(), lambda frame: None)
    try:
        device.reconfigure(
            CameraSettings(
                fps=14,
                sensor_resolution=None,
                output_resolution=PixelResolution(width_px=1280, height_px=720),
                rotation_degrees=0,
                focus=AutoFocus(mode="auto"),
            )
        )
        assert device.autofocus(10) is True
        assert device.telemetry.sensor_temperature_c == 25.0
        assert device.telemetry.focus_state == "focused"
        assert device.telemetry.latest_focus_succeeded is True
    finally:
        device.close()


def test_all_rotations_use_exif_without_changing_encoded_dimensions() -> None:
    clip = (
        files("edge_hardware_service.hardware.camera")
        .joinpath(SIMULATION_CLIP_RESOURCE)
        .read_bytes()
    )
    frame = _split_mjpeg(clip)[0]

    for rotation, expected_orientation in {0: 1, 90: 6, 180: 3, 270: 8}.items():
        oriented = set_exif_orientation(frame, rotation)
        exif = piexif.load(oriented)
        assert exif["0th"][piexif.ImageIFD.Orientation] == expected_orientation
        assert jpeg_dimensions(oriented) == (1280, 720)
