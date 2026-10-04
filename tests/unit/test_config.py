"""Unit tests for environment-based application configuration."""

import pytest

from edge_hardware_service.config import Settings


def test_backend_defaults_to_simulation(monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent runtime setting should select the portable backend."""
    monkeypatch.delenv("EDGE_HARDWARE_SERVICE_BACKEND", raising=False)

    assert Settings.from_env().hardware_backend == "simulation"


@pytest.mark.parametrize("value", ["simulation", "rpi", "RPI"])
def test_backend_is_read_from_namespaced_setting(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    """The repository-specific setting should select a supported backend."""
    monkeypatch.setenv("EDGE_HARDWARE_SERVICE_BACKEND", value)

    assert Settings.from_env().hardware_backend == value.lower()


def test_invalid_backend_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown backend names should fail during application configuration."""
    monkeypatch.setenv("EDGE_HARDWARE_SERVICE_BACKEND", "mock")

    with pytest.raises(
        ValueError,
        match="Unsupported EDGE_HARDWARE_SERVICE_BACKEND: 'mock'",
    ):
        Settings.from_env()
