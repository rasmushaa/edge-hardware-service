#!/usr/bin/env bash

# Copy this repository to a Raspberry Pi and recreate its native test venv.

set -euo pipefail

readonly REMOTE_DIR="edge-hardware-service"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [ "$#" -gt 1 ]; then
    echo "Usage: $0 [user@host]" >&2
    exit 1
fi

if [ "$#" -eq 1 ]; then
    pi_host="$1"
else
    echo "Synchronize repository to Raspberry Pi"
    echo
    echo "Requirements:"
    echo "- Raspberry Pi 5 running Raspberry Pi OS Bookworm."
    echo "- SSH access with rsync and uv available on the Raspberry Pi."
    echo "- Raspberry Pi OS GPIO Zero, libcamera, Picamera2, and NumPy packages installed."
    echo "- This mirrors the current checkout into ~/edge-hardware-service, removes"
    echo "  non-excluded remote files absent locally, and recreates the remote .venv."
    echo
    read -r -p "Raspberry Pi SSH host (user@host): " pi_host
    if [ -z "${pi_host}" ]; then
        echo "An SSH host is required, for example pi@edgepi.local." >&2
        exit 1
    fi
    read -r -p "Copy the checkout and recreate .venv on ${pi_host} [y/N]: " confirmation
    if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
        echo "Repository synchronization cancelled."
        exit 1
    fi
fi

if [ -z "${pi_host}" ]; then
    echo "An SSH host is required, for example pi@edgepi.local." >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "rsync is required on the development machine." >&2
    exit 1
fi

echo "Checking Raspberry Pi synchronization prerequisites..."
ssh "${pi_host}" "
    set -eu
    command -v rsync >/dev/null
    command -v uv >/dev/null
    test -x /usr/bin/python3
    mkdir -p ~/'${REMOTE_DIR}'
"

echo "Copying ${REPOSITORY_ROOT} to ${pi_host}:~/${REMOTE_DIR}..."
rsync --archive --compress --delete \
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
    "${REPOSITORY_ROOT}/" "${pi_host}:~/${REMOTE_DIR}/"

echo "Recreating the Raspberry Pi virtual environment..."
ssh "${pi_host}" "
    set -eu
    cd ~/'${REMOTE_DIR}'
    rm -rf -- .venv
    uv venv --python /usr/bin/python3 --system-site-packages
    uv sync --frozen
    .venv/bin/python -c 'import gpiozero, lgpio, libcamera, numpy, picamera2'
"

echo "Repository synchronized and Raspberry Pi test environment recreated."
