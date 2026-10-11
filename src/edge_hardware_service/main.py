"""FastAPI application factory and runtime composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from edge_hardware_service.api.errors import register_exception_handlers
from edge_hardware_service.api.v1 import router as v1_router
from edge_hardware_service.config import Settings
from edge_hardware_service.errors import HardwareUnavailableError
from edge_hardware_service.services.camera import CameraService
from edge_hardware_service.services.gpio import GpioService


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional explicit settings. Environment variables are used
            when settings are not provided.

    Returns:
        The configured FastAPI application.
    """
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Raspberry Pi packages must not be imported in simulation mode.
        if settings.hardware_backend == "simulation":
            from edge_hardware_service.hardware.camera.simulation_factory import (
                SimulationCameraDevice,
            )
            from edge_hardware_service.hardware.gpio.simulation_factory import (
                SimulationDeviceFactory,
            )

            gpio_factory = SimulationDeviceFactory()
            camera_service = CameraService(
                SimulationCameraDevice(),
                backend="simulation",
            )
        else:
            try:
                from edge_hardware_service.hardware.gpio.gpiozero_factory import (
                    GpioZeroDeviceFactory,
                )
            except ModuleNotFoundError as error:
                if error.name == "gpiozero" or (
                    error.name is not None and error.name.startswith("gpiozero.")
                ):
                    raise HardwareUnavailableError(
                        f"GPIO provider {error.name!r} is unavailable in this runtime",
                        details={
                            "component": "gpio",
                            "provider": error.name,
                            "operation": "initialize provider",
                        },
                    ) from error
                raise

            gpio_factory = GpioZeroDeviceFactory()
            try:
                from edge_hardware_service.hardware.camera.picamera2_device import (
                    Picamera2Device,
                )

                camera_service = CameraService(
                    Picamera2Device(device_index=0),
                    backend="rpi",
                )
            except Exception as error:
                # Camera capability degrades independently. GPIO remains a
                # required provider for the Raspberry Pi backend.
                reason = str(error) or type(error).__name__
                camera_service = CameraService.unavailable("rpi", reason)

        gpio_service = GpioService(gpio_factory)
        app.state.gpio_service = gpio_service
        app.state.camera_service = camera_service

        try:
            yield
        finally:
            camera_error: Exception | None = None
            try:
                camera_service.close()
            except Exception as error:
                camera_error = error
            try:
                gpio_service.close()
            except Exception as gpio_error:
                if camera_error is not None:
                    raise ExceptionGroup(
                        "Hardware shutdown failed",
                        [camera_error, gpio_error],
                    ) from gpio_error
                raise
            if camera_error is not None:
                raise camera_error

    app = FastAPI(
        title="Edge Hardware Service",
        lifespan=lifespan,
    )
    app.state.hardware_backend = settings.hardware_backend

    register_exception_handlers(app)
    app.include_router(v1_router)

    return app


app = create_app()
