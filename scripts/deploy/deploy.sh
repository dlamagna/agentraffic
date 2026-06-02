#!/usr/bin/env bash
# =============================================================================
# scripts/deploy/deploy.sh
# =============================================================================
# Start the AgenTraffic testbed.
#
# Usage:
#   scripts/deploy/deploy.sh [--monitoring]
#
# Options:
#   --monitoring   Also start Prometheus, Grafana, and cAdvisor
#   -h, --help     Show help
#
# Prerequisites:
#   1. Docker with the NVIDIA container runtime (for GPU LLM backend)
#   2. infra/.env created from infra/.env.example with HF_TOKEN set
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="${ROOT_DIR}/infra"
MONITORING=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --monitoring) MONITORING=true; shift ;;
    -h|--help)
      grep -E "^#" "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "[!] Unknown option: $1"; exit 1 ;;
  esac
done

cd "$COMPOSE_DIR"

# Create .env from example if missing
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "[!] Created infra/.env from .env.example — set HF_TOKEN before running."
    exit 1
  fi
fi

# Load network topology env if present (required for DEPLOYMENT_MODE=distributed)
ENV_FILE_ARGS=(--env-file .env)
if [[ -f network.env ]]; then
  ENV_FILE_ARGS+=(--env-file network.env)
elif [[ -f network.env.example ]]; then
  cp network.env.example network.env
  echo "[*] Created infra/network.env from network.env.example (using default subnets)."
  ENV_FILE_ARGS+=(--env-file network.env)
fi

# Read deployment mode from .env
DEPLOYMENT_MODE=$(grep -E '^DEPLOYMENT_MODE=' .env 2>/dev/null | cut -d= -f2 | tr -d '[:space:]' || echo "single")

echo "============================================================"
echo "  agentraffic — Deploy"
echo "  Mode:       $DEPLOYMENT_MODE"
echo "  Monitoring: $MONITORING"
echo "============================================================"

COMPOSE_ARGS=("${ENV_FILE_ARGS[@]}" -f docker-compose.yml)
if [[ "$MONITORING" == "true" ]]; then
  COMPOSE_ARGS+=(-f docker-compose.monitoring.yml)
fi

echo "[*] Building images..."
docker compose "${COMPOSE_ARGS[@]}" build

echo "[*] Starting services..."
docker compose "${COMPOSE_ARGS[@]}" up -d

echo ""
echo "[*] Waiting for Agent A to become ready..."
for i in $(seq 1 60); do
  code=$(curl -so /dev/null -w "%{http_code}" \
              http://localhost:8101/agentverse --max-time 3 2>/dev/null || echo "000")
  # 400 (missing task_id) means the server is up
  if [[ "$code" =~ ^(200|400|404)$ ]]; then
    echo "[✓] Agent A ready"
    break
  fi
  if [[ $i -eq 60 ]]; then
    echo "[!] Agent A did not become ready in time. Check: docker logs agent-a"
    exit 1
  fi
  sleep 5
done

echo ""
echo "============================================================"
echo "  Services:"
echo "    Agent A   : http://localhost:8101"
echo "    Jaeger UI  : http://localhost:16686"
echo "    AgentVerse viewer: http://localhost:3000/agentverse"
if [[ "$MONITORING" == "true" ]]; then
echo "    Prometheus : http://localhost:9090"
echo "    Grafana    : http://localhost:3001  (admin/admin)"
echo "    cAdvisor   : http://localhost:8080"
fi
echo ""
echo "  Run an experiment:"
echo "    scripts/experiment/run_agentverse.sh -t full_mesh -n 10"
echo "============================================================"
