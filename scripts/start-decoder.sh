#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" == "--check" ]]; then
    docker compose config --quiet
    echo "WSL startup and Compose configuration checks passed."
    exit 0
fi

echo "Starting the direct-USB rtl_433 and dashboard containers..."
docker compose up -d --build
docker compose ps
echo "Dashboard: http://localhost:8080"
