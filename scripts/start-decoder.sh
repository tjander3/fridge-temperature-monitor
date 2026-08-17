#!/usr/bin/env bash
set -euo pipefail

windows_host_ip="$(ip route show default | awk '/default/ {print $3; exit}')"
if [[ -z "$windows_host_ip" ]]; then
    echo "Could not determine the Windows host address from WSL's default route." >&2
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
docker compose up -d --build
docker compose ps
echo "Dashboard: http://localhost:8080"
