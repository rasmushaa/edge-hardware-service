from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from edge_hardware_service.api.v1 import router as v1_router
from edge_hardware_service.config import Settings
from edge_hardware_service.services.gpio import GpioDeviceService


def create_app(settings: Settings | None = None) -> FastAPI:
    """ Create and configure the FastAPI application instance. 
    
    Args:
        settings (Settings | None): Optional settings object. If not provided, settings will be loaded from the environment.

    Returns:
        FastAPI: Configured FastAPI application instance.
    """

    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:

        # Initialize GPIO backend and service. The Raspberry Pi hardware is not even imported in mock mode
        if settings.hardware_backend == "mock":
            from edge_hardware_service.hardware.gpio.mock_factory import MockDeviceFactory
            gpio_factory = MockDeviceFactory()
        else:
            from edge_hardware_service.hardware.gpio.rpi_factory import RpiDeviceFactory
            gpio_factory = RpiDeviceFactory()
        gpio_service = GpioDeviceService(gpio_factory)
        app.state.gpio_service = gpio_service

        # Application startup logic can be added here if needed
        try:
            yield
        finally:
            gpio_service.close()

    app = FastAPI(
        title="Edge Hardware Service",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Include API routers
    app.include_router(v1_router)

    return app


app = create_app()
