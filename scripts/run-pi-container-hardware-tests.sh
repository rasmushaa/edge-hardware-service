#!/usr/bin/env bash

# Transfer and run the combined GPIO and camera ARM64 hardware test image.

set -euo pipefail

readonly IMAGE="edge-hardware-service:container-hw-test"
readonly PROVIDER_PROBE='from gpiozero import Device; Device.ensure_pin_factory(); factory = Device.pin_factory; print(type(factory).__module__ + "." + type(factory).__qualname__); factory.close()'
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 0 ]; then
    echo "This command takes no arguments; it prompts for every required value." >&2
    exit 1
fi

echo "Containerized Raspberry Pi GPIO and camera hardware tests"
echo
echo "Requirements:"
echo "- Raspberry Pi 5 running Raspberry Pi OS Bookworm with Docker access."
echo "- A Picamera2-compatible camera must be available at index 0."
echo "- Choose three distinct, unconnected BCM pins from 2 through 27."
echo "- The pins must not be assigned to an overlay, peripheral, or other process."
echo "- WARNING: this command stops every running Docker container on the selected Pi."
echo
echo "What this tests:"
echo "- ARM64 image packaging and Raspberry Pi OS GPIO/camera packages."
echo "- Native/container GPIO Zero provider parity and real GPIO access."
echo "- Real Picamera2 streaming and advertised controls from inside the container."
echo "- It uses a test image, not the deployed runtime HTTP API."
echo "- It does not measure voltage or inspect PWM waveforms."
echo

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Image ${IMAGE} is unavailable; run this through 'make hw-test-docker'." >&2
    exit 1
fi

architecture="$(docker image inspect "${IMAGE}" --format '{{.Architecture}}')"
if [ "${architecture}" != "arm64" ]; then
    echo "Image ${IMAGE} is ${architecture}; expected arm64." >&2
    exit 1
fi

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
echo "The privileged test container will use:"
echo "- SSH target: ${pi_host}"
echo "- Input: BCM ${input_pin} (internal pull-up and pull-down reads)"
echo "- Digital output: BCM ${output_pin} (driven LOW and HIGH, then left LOW)"
echo "- PWM output: BCM ${pwm_pin} (duty cycle changes, then left at zero)"
echo "- Camera: Picamera2 index 0"
echo "- Device access: --privileged with /run/udev mounted read-only"
echo
echo "WARNING: continuing will stop ALL running Docker containers on ${pi_host}."
echo "Those containers will remain stopped after the test."
read -r -p "Stop all Pi containers and confirm the pins and camera [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Container hardware tests cancelled."
    exit 1
fi

"${SCRIPT_DIR}/stop-pi-containers.sh" "${pi_host}"

echo "Checking Docker and Raspberry Pi access on ${pi_host}..."
ssh "${pi_host}" "
    set -eu
    docker info >/dev/null
    test -x /usr/bin/python3
    test -r /proc/device-tree/model
    model=\$(tr -d '\\000' < /proc/device-tree/model)
    case \"\${model}\" in
        *\"Raspberry Pi 5\"*) ;;
        *) echo \"Target is not a Raspberry Pi 5: \${model}\" >&2; exit 1 ;;
    esac
    grep --quiet 'VERSION_CODENAME=bookworm' /etc/os-release
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

echo "Installed container hardware packages:"
ssh "${pi_host}" "
    for package in python3-gpiozero python3-lgpio python3-rpi-lgpio python3-libcamera python3-picamera2; do
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

echo "Running combined hardware tests inside the ARM64 image..."
ssh "${pi_host}" "
    docker run --rm \
        --privileged \
        --volume /run/udev:/run/udev:ro \
        --env EDGE_HARDWARE_RPI_INPUT_PIN='${input_pin}' \
        --env EDGE_HARDWARE_RPI_OUTPUT_PIN='${output_pin}' \
        --env EDGE_HARDWARE_RPI_PWM_PIN='${pwm_pin}' \
        '${IMAGE}'
"

echo "Containerized GPIO and camera hardware tests passed with ${container_provider}."
