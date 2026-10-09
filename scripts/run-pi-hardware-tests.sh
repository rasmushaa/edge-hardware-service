#!/usr/bin/env bash

# Run the opt-in GPIO hardware tests in the prepared Raspberry Pi repository.

set -euo pipefail

readonly REMOTE_DIR="edge-hardware-service"

read -r -p "Raspberry Pi SSH host (user@host): " pi_host
if [ -z "${pi_host}" ]; then
    echo "An SSH host is required." >&2
    exit 1
fi

read -r -p "Unconnected BCM input pin: " input_pin
read -r -p "Unconnected BCM digital-output pin: " output_pin
read -r -p "Unconnected BCM PWM-output pin: " pwm_pin

for pin in "${input_pin}" "${output_pin}" "${pwm_pin}"; do
    if ! [[ "${pin}" =~ ^[0-9]+$ ]]; then
        echo "BCM pins must be non-negative integers." >&2
        exit 1
    fi
    if [ "${pin}" -lt 2 ] || [ "${pin}" -gt 27 ]; then
        echo "Select GPIO pins from BCM 2 through BCM 27." >&2
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
echo "Native Raspberry Pi OS functional GPIO test"
echo
echo "No external test hardware or wiring is required."
echo "Leave BCM ${input_pin}, BCM ${output_pin}, and BCM ${pwm_pin} unconnected."
echo
echo "The suite checks internal pull-up/pull-down input reads, digital-output"
echo "state changes, PWM configuration, provider selection, and cleanup."
echo "It does not measure physical output voltage or the PWM waveform."
echo "It runs directly on the Raspberry Pi as the SSH user, without sudo."
read -r -p "Confirm these pins are unconnected and safe to drive [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Hardware test cancelled."
    exit 1
fi

ssh "${pi_host}" "
    set -eu
    cd ~/'${REMOTE_DIR}'
    test -x .venv/bin/pytest
    test -r /proc/device-tree/model
    model=\$(tr -d '\\000' < /proc/device-tree/model)
    case \"\${model}\" in
        *\"Raspberry Pi\"*) ;;
        *) echo \"Target is not a Raspberry Pi: \${model}\" >&2; exit 1 ;;
    esac
    echo \"Running natively on: \${model}\"
    EDGE_HARDWARE_RPI_INPUT_PIN='${input_pin}' \
    EDGE_HARDWARE_RPI_OUTPUT_PIN='${output_pin}' \
    EDGE_HARDWARE_RPI_PWM_PIN='${pwm_pin}' \
        .venv/bin/pytest -m 'rpi and not camera_rpi' --verbose --showlocals
"
