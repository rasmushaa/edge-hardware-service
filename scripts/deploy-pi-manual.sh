#!/usr/bin/env bash

# Transfer the development image to a Raspberry Pi and start the hardware API.

set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 user@host" >&2
    exit 1
fi

readonly PI_HOST="$1"
readonly IMAGE="edge-hardware-service:dev"
readonly CONTAINER_NAME="edge-hardware-service"
readonly API_PORT="8000"
readonly PUBLIC_API_URL="http://${PI_HOST#*@}:${API_PORT}"

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Image ${IMAGE} is unavailable. Run 'make build' first." >&2
    exit 1
fi

architecture="$(docker image inspect "${IMAGE}" --format '{{.Architecture}}')"
if [ "${architecture}" != "arm64" ]; then
    echo "Image ${IMAGE} is ${architecture}; expected arm64." >&2
    exit 1
fi

echo "Checking Docker access on ${PI_HOST}..."
ssh "${PI_HOST}" "docker info >/dev/null"

echo "Transferring ${IMAGE}..."
docker save "${IMAGE}" \
    | gzip -1 \
    | ssh "${PI_HOST}" "gzip -d | docker load"

echo "Starting ${CONTAINER_NAME}..."
ssh "${PI_HOST}" "
    set -eu
    docker rm --force '${CONTAINER_NAME}' >/dev/null 2>&1 || true
    docker run --detach \
        --name '${CONTAINER_NAME}' \
        --restart unless-stopped \
        --privileged \
        --volume /run/udev:/run/udev:ro \
        --publish '${API_PORT}:8000' \
        --env EDGE_HARDWARE_SERVICE_BACKEND=rpi \
        --env GPIOZERO_PIN_FACTORY=lgpio \
        '${IMAGE}'
"

echo "Waiting for the API..."
if ! ssh "${PI_HOST}" "
    set -eu
    for attempt in \$(seq 1 30); do
        if docker exec '${CONTAINER_NAME}' python -c \
            \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).read()\" \
            >/dev/null 2>&1; then
            exit 0
        fi
        sleep 2
    done
    docker logs --tail=100 '${CONTAINER_NAME}'
    exit 1
"; then
    echo "Deployment failed: the API did not become healthy." >&2
    exit 1
fi

echo "Deployment succeeded."
echo "Health:  ${PUBLIC_API_URL}/api/v1/health"
echo "Swagger: ${PUBLIC_API_URL}/docs"
