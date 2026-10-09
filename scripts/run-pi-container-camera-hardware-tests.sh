#!/usr/bin/env bash

# Transfer and run the camera-only ARM64 hardware test image on a Raspberry Pi.

set -euo pipefail

readonly IMAGE="edge-hardware-service:rpi-camera-hardware-test"
readonly RUNNING_API_CONTAINER="edge-hardware-service"

read -r -p "Raspberry Pi SSH host (user@host): " pi_host
if [ -z "${pi_host}" ]; then
    echo "An SSH host is required." >&2
    exit 1
fi

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Image ${IMAGE} is unavailable; build it with make build-pi-camera-hardware-test." >&2
    exit 1
fi

architecture="$(docker image inspect "${IMAGE}" --format '{{.Architecture}}')"
if [ "${architecture}" != "arm64" ]; then
    echo "Image ${IMAGE} is ${architecture}; expected arm64." >&2
    exit 1
fi

echo
echo "Container Raspberry Pi 5 Picamera2 camera validation"
echo
echo "The container needs privileged access to the host camera devices and udev."
echo "The test exercises discovered modes and controls, then releases the camera."
read -r -p "Confirm the camera is available for this test [y/N]: " confirmation
if [[ ! "${confirmation}" =~ ^[Yy]$ ]]; then
    echo "Container camera hardware test cancelled."
    exit 1
fi

ssh "${pi_host}" "
    set -eu
    docker info >/dev/null
    test -r /proc/device-tree/model
    model=\$(tr -d '\\000' < /proc/device-tree/model)
    case \"\${model}\" in
        *\"Raspberry Pi 5\"*) ;;
        *) echo \"Target is not a Raspberry Pi 5: \${model}\" >&2; exit 1 ;;
    esac
    grep --quiet 'VERSION_CODENAME=bookworm' /etc/os-release
    if docker ps --format '{{.Names}}' \\
        | grep --quiet --line-regexp '${RUNNING_API_CONTAINER}'; then
        echo \"Container ${RUNNING_API_CONTAINER} may own the camera. Stop it first.\" >&2
        exit 1
    fi
    echo \"Target: \${model}\"
"

echo "Transferring ${IMAGE}..."
docker save "${IMAGE}" \
    | gzip -1 \
    | ssh "${pi_host}" "gzip -d | docker load"

ssh "${pi_host}" "
    docker run --rm \\
        --privileged \\
        --volume /run/udev:/run/udev:ro \\
        --env EDGE_HARDWARE_SERVICE_BACKEND=rpi \\
        '${IMAGE}'
"

echo "Container Picamera2 camera hardware validation passed."
