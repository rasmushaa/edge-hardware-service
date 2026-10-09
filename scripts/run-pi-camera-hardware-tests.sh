#!/usr/bin/env bash

# Run the opt-in Picamera2 camera suite on the Raspberry Pi itself.

set -euo pipefail

readonly REMOTE_DIR="edge-hardware-service"

read -r -p "Raspberry Pi SSH host (user@host): " pi_host
if [ -z "${pi_host}" ]; then
    echo "An SSH host is required." >&2
    exit 1
fi

echo
echo "Native Raspberry Pi 5 Picamera2 camera validation"
echo
echo "The test requires a Picamera2-compatible camera at index 0."
echo "It tests discovered modes and focus controls, then releases the camera."
read -r -p "Confirm the camera is available for this test [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Camera hardware test cancelled."
    exit 1
fi

ssh "${pi_host}" "
    set -eu
    cd ~/'${REMOTE_DIR}'
    test -x .venv/bin/pytest
    test -r /proc/device-tree/model
    model=\$(tr -d '\\000' < /proc/device-tree/model)
    case \"\${model}\" in
        *\"Raspberry Pi 5\"*) ;;
        *) echo \"Target is not a Raspberry Pi 5: \${model}\" >&2; exit 1 ;;
    esac
    grep --quiet 'VERSION_CODENAME=bookworm' /etc/os-release
    echo \"Running natively on: \${model}\"
    .venv/bin/pytest tests/rpi/test_picamera2_camera_hardware.py \\
        -m 'rpi and camera_rpi' --verbose --showlocals
"
