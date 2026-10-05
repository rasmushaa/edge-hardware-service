"""Application configuration for the edge hardware service from environment variables.

All settings must be provided through environment variables, via this module.
"""

import os
from dataclasses import dataclass
from typing import Literal, cast

HardwareBackend = Literal["simulation", "rpi"]


@dataclass(frozen=True)
class Settings:
    hardware_backend: HardwareBackend

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv(
            "EDGE_HARDWARE_SERVICE_BACKEND",
            "simulation",
        ).lower()

        if backend not in {"simulation", "rpi"}:
            raise ValueError(f"Unsupported EDGE_HARDWARE_SERVICE_BACKEND: {backend!r}")

        return cls(hardware_backend=cast(HardwareBackend, backend))
