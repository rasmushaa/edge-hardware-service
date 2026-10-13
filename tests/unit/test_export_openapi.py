import json
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]


def test_export_openapi_without_raspberry_pi_dependencies(tmp_path: Path) -> None:
    output = tmp_path / "api-docs" / "openapi.json"
    environment = os.environ.copy()
    environment["EDGE_HARDWARE_SERVICE_BACKEND"] = "rpi"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_openapi.py",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    schema = json.loads(output.read_text(encoding="utf-8"))
    assert schema["info"]["title"] == "Edge Hardware Service"
    assert schema["info"]["version"] == version("edge-hardware-service")
    assert schema["openapi"] == "3.1.0"
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/camera" in schema["paths"]
    assert "/api/v1/gpio" in schema["paths"]
    assert f"to {output}" in result.stdout
