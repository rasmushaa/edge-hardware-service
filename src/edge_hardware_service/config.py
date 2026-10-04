"""Application configuration for the edge hardware service from environment variables.

All settings must be provided through environment variables, via this module.
"""
import os
from dataclasses import dataclass
from typing import Literal


HardwareBackend = Literal["mock", "rpi"] # The main flag that chooses which backend module to import and use


@dataclass(frozen=True)
class Settings:
    hardware_backend: HardwareBackend

    @classmethod
    def from_env(cls) -> "Settings":
        backend = os.getenv("HARDWARE_BACKEND", "mock").lower()

        if backend not in {"mock", "rpi"}:
            raise ValueError(
                f"Unsupported HARDWARE_BACKEND: {backend!r}"
            )

        return cls(hardware_backend=backend)