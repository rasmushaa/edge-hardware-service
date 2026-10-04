"""FastAPI application factory and runtime composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from edge_hardware_service.api.errors import register_exception_handlers
from edge_hardware_service.api.v1 import router as v1_router
from edge_hardware_service.config import Settings
from edge_hardware_service.hardware.gpio.exceptions import (
    GpioProviderUnavailable,
)
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
            from edge_hardware_service.hardware.gpio.simulation_factory import (
                SimulationDeviceFactory,
            )

            gpio_factory = SimulationDeviceFactory()
        else:
            try:
                from edge_hardware_service.hardware.gpio.gpiozero_factory import (
                    GpioZeroDeviceFactory,
                )
            except ModuleNotFoundError as error:
                if error.name == "gpiozero" or (
                    error.name is not None
                    and error.name.startswith("gpiozero.")
                ):
                    raise GpioProviderUnavailable(error.name) from error
                raise

            gpio_factory = GpioZeroDeviceFactory()

        gpio_service = GpioService(gpio_factory)
        app.state.gpio_service = gpio_service

        try:
            yield
        finally:
            gpio_service.close()

    app = FastAPI(
        title="Edge Hardware Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.hardware_backend = settings.hardware_backend

    register_exception_handlers(app)
    app.include_router(v1_router)

    return app


app = create_app()
