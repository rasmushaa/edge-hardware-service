#!/usr/bin/env python3
"""Export the FastAPI OpenAPI schema without starting the application."""

import argparse
import json
from importlib.metadata import version
from pathlib import Path
from typing import Any

from edge_hardware_service.config import Settings
from edge_hardware_service.main import create_app

DEFAULT_OUTPUT = Path("build/api-docs/openapi.json")


def export_openapi(output: Path) -> dict[str, Any]:
    """Write the OpenAPI schema using the hardware-free simulation config."""
    app = create_app(Settings(hardware_backend="simulation"))
    schema = app.openapi()
    schema["info"]["version"] = version("edge-hardware-service")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{json.dumps(schema, indent=2, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    return schema


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the Edge Hardware Service OpenAPI schema.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schema = export_openapi(args.output)
    print(
        f"Exported {len(schema['paths'])} paths to {args.output}",
    )


if __name__ == "__main__":
    main()
