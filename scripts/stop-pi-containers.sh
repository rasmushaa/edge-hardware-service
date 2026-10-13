#!/usr/bin/env bash

# Stop every running Docker container on one explicitly selected Raspberry Pi.

set -euo pipefail

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
    echo "Usage: $0 user@host" >&2
    exit 1
fi

readonly PI_HOST="$1"

echo "Stopping all running Docker containers on ${PI_HOST}..."
ssh "${PI_HOST}" '
    set -eu
    if [ ! -r /proc/device-tree/model ]; then
        echo "Refusing to stop containers: target does not identify as a Raspberry Pi." >&2
        exit 1
    fi
    model="$(tr -d "\000" < /proc/device-tree/model)"
    case "${model}" in
        *"Raspberry Pi"*) ;;
        *) echo "Refusing to stop containers: target is not a Raspberry Pi (${model})." >&2; exit 1 ;;
    esac
    docker info >/dev/null
    running_names="$(docker ps --format "{{.Names}}")"
    if [ -z "${running_names}" ]; then
        echo "No Docker containers are running."
        exit 0
    fi

    echo "Running containers to stop:"
    printf "%s\n" "${running_names}"
    docker ps --quiet | while IFS= read -r container_id; do
        [ -n "${container_id}" ] && docker stop "${container_id}"
    done

    if [ -n "$(docker ps --quiet)" ]; then
        echo "Some Docker containers are still running." >&2
        exit 1
    fi
'
