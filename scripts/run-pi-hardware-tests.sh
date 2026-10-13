#!/usr/bin/env bash

# Run the combined native GPIO and camera suites on a prepared Raspberry Pi.

set -euo pipefail

readonly REMOTE_DIR="edge-hardware-service"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 0 ]; then
    echo "This command takes no arguments; it prompts for every required value." >&2
    exit 1
fi

echo "Native Raspberry Pi GPIO and camera hardware tests"
echo
echo "Requirements:"
echo "- Raspberry Pi 5 running Raspberry Pi OS Bookworm."
echo "- SSH access with rsync and uv available on the Raspberry Pi."
echo "- Raspberry Pi OS GPIO Zero, libcamera, Picamera2, and NumPy packages installed."
echo "- A Picamera2-compatible camera must be available at index 0."
echo "- Choose three distinct, unconnected BCM pins from 2 through 27."
echo "- The pins must not be assigned to an overlay, peripheral, or other process."
echo "- WARNING: this command stops every running Docker container on the selected Pi."
echo
echo "What this tests:"
echo "- First, the current checkout is mirrored to ~/edge-hardware-service; stale"
echo "  non-excluded remote files are removed and the remote .venv is recreated."
echo "- Native GPIO Zero provider selection, pull-up/down input, digital output, PWM, and cleanup."
echo "- Native Picamera2 discovery, MJPEG frames, advertised controls, focus, broker behavior, and cleanup."
echo "- It does not start FastAPI, call HTTP endpoints, measure voltage, or inspect PWM waveforms."
echo

read -r -p "Raspberry Pi SSH host (user@host): " pi_host
if [ -z "${pi_host}" ]; then
    echo "An SSH host is required, for example pi@edgepi.local." >&2
    exit 1
fi

read -r -p "Unconnected BCM input pin (2-27): " input_pin
read -r -p "Unconnected BCM digital-output pin (2-27): " output_pin
read -r -p "Unconnected BCM PWM-output pin (2-27): " pwm_pin

for selected_pin in "${input_pin}" "${output_pin}" "${pwm_pin}"; do
    if ! [[ "${selected_pin}" =~ ^[0-9]+$ ]]; then
        echo "BCM pins must be integers from 2 through 27." >&2
        exit 1
    fi
    if [ "${selected_pin}" -lt 2 ] || [ "${selected_pin}" -gt 27 ]; then
        echo "BCM pin ${selected_pin} is outside the supported range 2 through 27." >&2
        exit 1
    fi
done

if [ "${input_pin}" = "${output_pin}" ] \
    || [ "${input_pin}" = "${pwm_pin}" ] \
    || [ "${output_pin}" = "${pwm_pin}" ]; then
    echo "Input, digital-output, and PWM pins must be different." >&2
    exit 1
fi

echo
echo "The test will use:"
echo "- SSH target: ${pi_host}"
echo "- Input: BCM ${input_pin} (internal pull-up and pull-down reads)"
echo "- Digital output: BCM ${output_pin} (driven LOW and HIGH, then left LOW)"
echo "- PWM output: BCM ${pwm_pin} (duty cycle changes, then left at zero)"
echo "- Camera: Picamera2 index 0"
echo "- Repository: mirrored before tests; remote .venv: deleted and recreated"
echo
echo "WARNING: continuing will stop ALL running Docker containers on ${pi_host}."
echo "Those containers will remain stopped after the test."
read -r -p "Stop all Pi containers and confirm synchronization, pins, and camera [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Hardware tests cancelled."
    exit 1
fi

"${SCRIPT_DIR}/stop-pi-containers.sh" "${pi_host}"

"${SCRIPT_DIR}/sync-repo-to-pi.sh" "${pi_host}"

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
    echo \"Running native hardware tests on: \${model}\"
    EDGE_HARDWARE_RPI_INPUT_PIN='${input_pin}' \
    EDGE_HARDWARE_RPI_OUTPUT_PIN='${output_pin}' \
    EDGE_HARDWARE_RPI_PWM_PIN='${pwm_pin}' \
        .venv/bin/pytest tests/rpi \
            -o 'addopts=--import-mode=importlib' \
            -m rpi \
            --verbose \
            --showlocals
"

echo "Native GPIO and camera hardware tests passed."
