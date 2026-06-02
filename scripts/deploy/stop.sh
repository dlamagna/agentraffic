#!/usr/bin/env bash
# =============================================================================
# scripts/deploy/stop.sh
# =============================================================================
# Stop the AgenTraffic containers.
# Images and volumes are kept so the next deploy is fast.
#
# Options:
#   --volumes   Also remove Docker volumes (clears model cache)
#   -h, --help  Show help
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="${ROOT_DIR}/infra"
REMOVE_VOLUMES=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --volumes|-v) REMOVE_VOLUMES=true; shift ;;
    -h|--help) grep -E "^#" "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "[!] Unknown option: $1"; exit 1 ;;
  esac
done

cd "$COMPOSE_DIR"

echo "[*] Stopping services..."
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down 2>/dev/null || \
docker compose -f docker-compose.yml down 2>/dev/null || true

if [[ "$REMOVE_VOLUMES" == "true" ]]; then
  echo "[*] Removing volumes..."
  docker volume prune -f
fi

echo "[✓] Done."
