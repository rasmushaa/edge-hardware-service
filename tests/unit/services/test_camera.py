"""Unit tests for camera policy and the bounded latest-frame broker."""

from collections.abc import Callable
from importlib.resources import files
from threading import Event, Thread, Timer
from time import monotonic

import pytest

from edge_hardware_service.hardware.camera.exceptions import (
    CameraAutofocusTimeout,
    CameraCapabilityUnsupported,
    CameraNotReady,
    CameraOperationError,
    CameraUnavailable,
)
from edge_hardware_service.hardware.camera.simulation_factory import _split_mjpeg
from edge_hardware_service.models.camera import (
    DEFAULT_OUTPUT_RESOLUTION,
    AutoFocus,
    CameraCapabilities,
    CameraSettings,
    CameraSettingsPatch,
    CameraStreamInfo,
    CameraTelemetry,
    FocusCapability,
    LensPositionCapability,
    OutputCapability,
    PixelResolution,
)
from edge_hardware_service.services import camera as camera_module
from edge_hardware_service.services.camera import CameraService, LatestFrameBroker

RAW_CLIP = (
    files("edge_hardware_service.hardware.camera")
    .joinpath("assets/camera-simulation.mjpeg")
    .read_bytes()
)
JPEG = _split_mjpeg(RAW_CLIP)[0]


class FakeCameraDevice:
    """Controllable continuously publishing camera protocol double."""

    device_index = 0
    device_model = "generic-camera"

    def __init__(self) -> None:
        self.callback: Callable[[bytes], None] | None = None
        self.settings: CameraSettings | None = None
        self.telemetry = CameraTelemetry()
        self.capabilities = CameraCapabilities(
            backend="rpi",
            device_index=0,
            device_model=self.device_model,
            output=OutputCapability(default_resolution=DEFAULT_OUTPUT_RESOLUTION),
            frame_rate_control=True,
            focus=FocusCapability(
                modes=("unmanaged", "manual", "auto", "continuous"),
                lens_position_diopters=LensPositionCapability(
                    minimum=1.0, maximum=10.0, default=3.0
                ),
            ),
        )
        self.stream_info = CameraStreamInfo(
            sensor_resolution=None,
            output_resolution=DEFAULT_OUTPUT_RESOLUTION,
        )
        self.reconfigure_failures: list[Exception | None] = []
        self.publish_after_reconfigure: list[bool] = []
        self.autofocus_result: bool | Exception = True
        self.start_error: Exception | None = None
        self.close_calls = 0
        self.reconfigure_calls: list[CameraSettings] = []
        self.validation_calls: list[CameraSettings] = []

    def start(
        self,
        settings: CameraSettings,
        publish_frame: Callable[[bytes], None],
    ) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.settings = settings
        self.callback = publish_frame
        publish_frame(JPEG)

    def validate_settings(self, settings: CameraSettings) -> None:
        self.validation_calls.append(settings)
        if settings.focus.mode not in self.capabilities.focus.modes:
            raise CameraCapabilityUnsupported("unsupported focus mode")
        if settings.focus.mode == "manual":
            lens = self.capabilities.focus.lens_position_diopters
            assert lens is not None
            position = settings.focus.lens_position_diopters
            if not lens.minimum <= position <= lens.maximum:
                raise CameraCapabilityUnsupported("outside advertised range")

    def reconfigure(self, settings: CameraSettings) -> None:
        self.reconfigure_calls.append(settings)
        failure = (
            self.reconfigure_failures.pop(0) if self.reconfigure_failures else None
        )
        if failure is not None:
            raise failure
        self.settings = settings
        should_publish = (
            self.publish_after_reconfigure.pop(0)
            if self.publish_after_reconfigure
            else True
        )
        if should_publish and self.callback is not None:
            timer = Timer(0.01, self.callback, args=(JPEG,))
            timer.daemon = True
            timer.start()

    def autofocus(self, timeout_seconds: float) -> bool:
        assert timeout_seconds == 10.0
        if isinstance(self.autofocus_result, Exception):
            raise self.autofocus_result
        return self.autofocus_result

    def close(self) -> None:
        self.close_calls += 1


def resolution(width: int, height: int) -> PixelResolution:
    return PixelResolution(width_px=width, height_px=height)


def test_camera_settings_support_provider_defaults_and_nested_resolutions() -> None:
    settings = CameraSettings(
        fps=None,
        sensor_resolution=None,
        output_resolution=resolution(1280, 720),
        rotation_degrees=0,
        focus={"mode": "unmanaged"},  # type: ignore[arg-type]
    )
    assert settings.fps is None
    assert settings.sensor_resolution is None

    with pytest.raises(ValueError, match="even"):
        CameraSettings(
            fps=29.97,
            sensor_resolution=resolution(1920, 1080),
            output_resolution=resolution(1279, 720),
            rotation_degrees=0,
            focus={"mode": "unmanaged"},  # type: ignore[arg-type]
        )


def test_broker_keeps_only_latest_frame_and_slow_consumers_skip_frames() -> None:
    broker = LatestFrameBroker()
    first = broker.publish(JPEG)
    second = broker.publish(JPEG)
    third = broker.publish(JPEG)

    observed = broker.wait_for_frame(after_sequence=first.sequence)

    assert observed is third
    assert broker.latest is third
    assert second.sequence == first.sequence + 1
    assert not hasattr(broker, "_queue")


def test_broker_wakes_multiple_consumers_and_shutdown_waiters() -> None:
    broker = LatestFrameBroker()
    observed: list[int | None] = []

    def wait() -> None:
        frame = broker.wait_for_frame(timeout_seconds=5)
        observed.append(None if frame is None else frame.sequence)

    consumers = [Thread(target=wait), Thread(target=wait)]
    for consumer in consumers:
        consumer.start()
    broker.publish(JPEG)
    for consumer in consumers:
        consumer.join(timeout=1)
    assert observed == [1, 1]

    shutdown_waiter = Thread(
        target=lambda: observed.append(
            None
            if broker.wait_for_frame(timeout_seconds=5, after_sequence=1) is None
            else -1
        )
    )
    shutdown_waiter.start()
    started = monotonic()
    broker.close()
    shutdown_waiter.join(timeout=1)
    assert not shutdown_waiter.is_alive()
    assert monotonic() - started < 1
    assert observed[-1] is None


def test_broker_times_out_without_a_frame() -> None:
    broker = LatestFrameBroker()
    assert broker.wait_for_frame(timeout_seconds=0.01) is None


def test_resolution_update_is_atomic_and_waits_for_a_new_frame() -> None:
    device = FakeCameraDevice()
    service = CameraService(device, backend="rpi")

    result = service.update_settings(
        CameraSettingsPatch(sensor_resolution=resolution(1920, 1080), fps=14)
    )

    assert result.fps == 14
    assert result.sensor_resolution == resolution(1920, 1080)
    assert service.status().state == "streaming"
    assert service.wait_for_frame().sequence >= 2
    service.close()


def test_reconfiguration_clears_stale_frame_and_is_observable() -> None:
    entered = Event()
    release = Event()

    class BlockingCamera(FakeCameraDevice):
        def reconfigure(self, settings: CameraSettings) -> None:
            entered.set()
            assert release.wait(1)
            super().reconfigure(settings)

    device = BlockingCamera()
    service = CameraService(device, backend="rpi")
    failures: list[Exception] = []

    def update() -> None:
        try:
            service.update_settings(
                CameraSettingsPatch(sensor_resolution=resolution(1920, 1080))
            )
        except Exception as error:
            failures.append(error)

    worker = Thread(target=update)
    worker.start()
    assert entered.wait(1)
    assert service.status().state == "reconfiguring"
    assert service.frames.latest is None
    release.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert failures == []
    assert service.status().state == "streaming"
    service.close()


def test_unsupported_patch_is_rejected_before_reconfigure() -> None:
    device = FakeCameraDevice()
    device.capabilities = device.capabilities.model_copy(
        update={"focus": FocusCapability(modes=("unmanaged",))}
    )
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraCapabilityUnsupported, match="unsupported"):
        service.update_settings(CameraSettingsPatch(focus=AutoFocus(mode="auto")))

    assert device.reconfigure_calls == []
    assert service.settings.focus.mode == "unmanaged"
    service.close()


def test_manual_focus_uses_discovered_limits() -> None:
    device = FakeCameraDevice()
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraCapabilityUnsupported, match="advertised range"):
        service.update_settings(
            CameraSettingsPatch(
                focus={  # type: ignore[arg-type]
                    "mode": "manual",
                    "lens_position_diopters": 0.5,
                }
            )
        )

    assert device.reconfigure_calls == []
    service.close()


def test_failed_reconfiguration_rolls_back_previous_settings() -> None:
    device = FakeCameraDevice()
    device.reconfigure_failures = [RuntimeError("candidate failed"), None]
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraOperationError, match="candidate failed"):
        service.update_settings(
            CameraSettingsPatch(sensor_resolution=resolution(1920, 1080))
        )

    assert service.status().state == "streaming"
    assert service.settings.sensor_resolution is None
    assert len(device.reconfigure_calls) == 2
    service.close()


def test_rollback_failure_marks_camera_unavailable() -> None:
    device = FakeCameraDevice()
    device.reconfigure_failures = [
        RuntimeError("candidate failed"),
        RuntimeError("rollback failed"),
    ]
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraOperationError, match="rollback failed"):
        service.update_settings(
            CameraSettingsPatch(sensor_resolution=resolution(1920, 1080))
        )

    assert service.status().state == "unavailable"
    assert service.status().settings is None
    service.close()


def test_missing_reconfigured_frame_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(camera_module, "FRAME_WAIT_TIMEOUT_SECONDS", 0.03)
    device = FakeCameraDevice()
    device.publish_after_reconfigure = [False, True]
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraNotReady, match="No frame arrived"):
        service.update_settings(
            CameraSettingsPatch(sensor_resolution=resolution(1920, 1080))
        )

    assert service.status().state == "streaming"
    assert service.settings.sensor_resolution is None
    service.close()


@pytest.mark.parametrize("result", [True, False])
def test_autofocus_result_and_final_auto_mode(result: bool) -> None:
    device = FakeCameraDevice()
    device.autofocus_result = result
    service = CameraService(device, backend="rpi")

    response = service.autofocus()

    assert response.success is result
    assert service.settings.focus.mode == "auto"
    service.close()


def test_unsupported_autofocus_does_not_change_settings() -> None:
    device = FakeCameraDevice()
    device.capabilities = device.capabilities.model_copy(
        update={"focus": FocusCapability(modes=("unmanaged",))}
    )
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraCapabilityUnsupported, match="autofocus"):
        service.autofocus()

    assert service.settings.focus.mode == "unmanaged"
    assert device.reconfigure_calls == []
    service.close()


def test_autofocus_timeout_remains_a_timeout() -> None:
    device = FakeCameraDevice()
    device.autofocus_result = CameraAutofocusTimeout("timed out")
    service = CameraService(device, backend="rpi")

    with pytest.raises(CameraAutofocusTimeout, match="timed out"):
        service.autofocus()

    assert service.settings.focus.mode == "auto"
    service.close()


def test_startup_failure_degrades_status_and_capabilities() -> None:
    device = FakeCameraDevice()
    device.start_error = RuntimeError("camera missing")
    service = CameraService(device, backend="rpi")

    assert service.status().state == "unavailable"
    with pytest.raises(CameraUnavailable, match="camera missing"):
        service.capabilities()
    service.close()
    service.close()
    assert device.close_calls == 1
