#!/usr/bin/env bash

# Copy the repository to a Raspberry Pi and recreate its development venv.

set -euo pipefail

readonly REMOTE_DIR="edge-hardware-service"

read -r -p "Raspberry Pi SSH host (user@host): " pi_host
if [ -z "${pi_host}" ]; then
    echo "An SSH host is required." >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "rsync is required on the development machine." >&2
    exit 1
fi

echo "Checking Raspberry Pi prerequisites..."
ssh "${pi_host}" "
    set -eu
    command -v rsync >/dev/null
    command -v uv >/dev/null
    test -x /usr/bin/python3
    mkdir -p ~/'${REMOTE_DIR}'
"

echo "Copying the repository to ${pi_host}:~/${REMOTE_DIR}..."
rsync --archive --compress \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '.git/' \
    --exclude '.cache/' \
    --exclude '.coverage' \
    --exclude '.coverage.*' \
    --exclude '.hypothesis/' \
    --exclude '.mypy_cache/' \
    --exclude '.pytest_cache/' \
    --exclude '.ruff_cache/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude 'htmlcov/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    ./ "${pi_host}:~/${REMOTE_DIR}/"

echo "Recreating the Raspberry Pi virtual environment..."
ssh "${pi_host}" "
    set -eu
    cd ~/'${REMOTE_DIR}'
    rm -rf -- .venv
    uv venv --python /usr/bin/python3 --system-site-packages
    uv sync --frozen
    .venv/bin/python -c 'import gpiozero, lgpio, libcamera, numpy, picamera2'
"

echo "Raspberry Pi development environment is ready."
echo "Run 'make pi-hardware-test' to execute the physical GPIO tests."
