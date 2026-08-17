#!/usr/bin/env bash
set -euo pipefail

windows_host_ip="$(getent ahostsv4 host.docker.internal | head -n 1 | cut -d ' ' -f 1)"
if [[ -z "$windows_host_ip" ]]; then
    echo "Could not resolve the Windows host from WSL." >&2
    exit 1
fi

export WINDOWS_HOST_IP="$windows_host_ip"

if [[ "${1:-}" == "--check" ]]; then
    docker compose config --quiet
    echo "Resolved Windows host: $WINDOWS_HOST_IP"
    echo "WSL startup and Compose configuration checks passed."
    exit 0
fi

echo "Connecting rtl_433 to rtl_tcp on Windows at ${WINDOWS_HOST_IP}:1234..."
docker compose up rtl433
