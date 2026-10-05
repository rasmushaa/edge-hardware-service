#!/usr/bin/env bash

# Transfer the ARM64 test image and validate GPIO access inside the container.

set -euo pipefail

readonly IMAGE="edge-hardware-service:rpi-hardware-test"
readonly RUNNING_API_CONTAINER="edge-hardware-service"
readonly PROVIDER_PROBE='from gpiozero import Device; Device.ensure_pin_factory(); factory = Device.pin_factory; print(type(factory).__module__ + "." + type(factory).__qualname__); factory.close()'

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

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Image ${IMAGE} is unavailable." >&2
    exit 1
fi

architecture="$(docker image inspect "${IMAGE}" --format '{{.Architecture}}')"
if [ "${architecture}" != "arm64" ]; then
    echo "Image ${IMAGE} is ${architecture}; expected arm64." >&2
    exit 1
fi

echo
echo "Raspberry Pi container GPIO compatibility test"
echo
echo "No external test hardware or wiring is required."
echo "Leave BCM ${input_pin}, BCM ${output_pin}, and BCM ${pwm_pin} unconnected."
echo "Stop any other process or container that may own these pins."
echo "The test image runs with --privileged and a read-only /run/udev mount."
echo "It runs as root, matching the current production container configuration."
echo "It compares native and container provider selection before opening pins."
read -r -p "Confirm these pins are unconnected and safe to drive [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Container hardware test cancelled."
    exit 1
fi

echo "Checking Docker and Raspberry Pi access on ${pi_host}..."
ssh "${pi_host}" "
    set -eu
    docker info >/dev/null
    test -x /usr/bin/python3
    test -r /proc/device-tree/model
    model=\$(tr -d '\\000' < /proc/device-tree/model)
    case \"\${model}\" in
        *\"Raspberry Pi\"*) ;;
        *) echo \"Target is not a Raspberry Pi: \${model}\" >&2; exit 1 ;;
    esac
    if docker ps --format '{{.Names}}' \
        | grep --quiet --line-regexp '${RUNNING_API_CONTAINER}'; then
        echo \"Container ${RUNNING_API_CONTAINER} is running and may own GPIO.\" >&2
        echo \"Stop it before running this test.\" >&2
        exit 1
    fi
    echo \"Target: \${model}\"
"

echo "Transferring ${IMAGE}..."
docker save "${IMAGE}" \
    | gzip -1 \
    | ssh "${pi_host}" "gzip -d | docker load"

echo "Installed native provider packages:"
ssh "${pi_host}" "
    for package in python3-gpiozero python3-lgpio python3-rpi-lgpio; do
        dpkg-query --show --showformat='\${binary:Package}=\${Version}\\n' \
            \"\${package}\" 2>/dev/null || true
    done
"

echo "Installed container provider packages:"
ssh "${pi_host}" "
    for package in python3-gpiozero python3-lgpio python3-rpi-lgpio; do
        docker run --rm '${IMAGE}' \
            dpkg-query --show \
            --showformat='\${binary:Package}=\${Version}\\n' \
            \"\${package}\" 2>/dev/null || true
    done
"

native_provider="$(
    ssh "${pi_host}" "/usr/bin/python3 -c '${PROVIDER_PROBE}'"
)"
container_provider="$(
    ssh "${pi_host}" "
        docker run --rm \
            --privileged \
            --volume /run/udev:/run/udev:ro \
            '${IMAGE}' \
            python -c '${PROVIDER_PROBE}'
    "
)"

echo "Native provider:    ${native_provider}"
echo "Container provider: ${container_provider}"

if [ "${native_provider}" != "${container_provider}" ]; then
    echo "Native and container GPIO Zero providers do not match." >&2
    exit 1
fi

echo "Running the unconnected-pin suite inside the ARM64 image..."
ssh "${pi_host}" "
    docker run --rm \
        --privileged \
        --volume /run/udev:/run/udev:ro \
        --env EDGE_HARDWARE_RPI_INPUT_PIN='${input_pin}' \
        --env EDGE_HARDWARE_RPI_OUTPUT_PIN='${output_pin}' \
        --env EDGE_HARDWARE_RPI_PWM_PIN='${pwm_pin}' \
        '${IMAGE}'
"

echo "Container GPIO compatibility test passed with ${container_provider}."
