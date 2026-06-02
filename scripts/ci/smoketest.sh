#!/usr/bin/env bash
# =============================================================================
# scripts/ci/smoketest.sh
# =============================================================================
# Quick sanity check: one run of each topology with 1 sub-agent.
# Requires a running testbed (docker compose up -d).
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPERIMENT="${SCRIPT_DIR}/../experiment/run_agentverse.sh"

echo "=== AgentVerse smoketest ==="
for TOPO in horizontal vertical full_mesh; do
  echo "--- $TOPO ---"
  bash "$EXPERIMENT" --topology "$TOPO" --runs 1 --agents 1
done
echo ""
echo "=== Smoketest PASSED ==="
