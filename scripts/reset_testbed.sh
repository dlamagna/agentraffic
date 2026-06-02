#!/usr/bin/env bash
set -euo pipefail

#
# reset_testbed.sh
# ----------------
# Convenience wrapper that ensures a clean slate by running the uninstall
# script first and then redeploying the full stack.
#
# Usage:
#   scripts/reset_testbed.sh [--monitoring] [--uninstall-timer HOURS]
#
# Options:
#   --monitoring         Also start Prometheus, Grafana, and cAdvisor
#   --uninstall-timer H  Schedule an auto-uninstall after H hours
#   -h, --help           Show help
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASSTHRU_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --monitoring)
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
    --uninstall-timer|--shutdown-timer|-shutdown-timer)
      if [[ $# -lt 2 ]]; then
        echo "[!] $1 requires a value in hours (decimal allowed), e.g. --uninstall-timer 1.5"
        exit 1
      fi
      PASSTHRU_ARGS+=("--uninstall-timer" "$2")
      shift 2
      ;;
    -h|--help)
      grep -E "^#" "$0" | sed 's/^# \?//'; exit 0 ;;
    *)
      echo "[!] Unknown option: $1"
      exit 1
      ;;
  esac
done

echo "[*] Resetting AgenTraffic: uninstalling existing resources..."
"${SCRIPT_DIR}/deploy/uninstall_testbed.sh"

echo "[*] Redeploying from a clean state..."
"${SCRIPT_DIR}/deploy/deploy.sh" "${PASSTHRU_ARGS[@]}"

echo "[*] Reset complete."
