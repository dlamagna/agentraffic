#!/usr/bin/env bash
set -euo pipefail

#
# uninstall_testbed.sh
# --------------------
# Completely removes the AgenTraffic testbed, including:
#   - All Docker containers (via stop.sh)
#   - Docker volumes and networks
#   - Generated logs
#   - GPU cache artifacts
#
# USAGE:
#   ./scripts/deploy/uninstall_testbed.sh [OPTIONS]
#
# OPTIONS:
#   --wait HOURS      Schedule uninstall to run after HOURS (decimal allowed)
#   --keep-logs       Don't remove the logs directory (default)
#   --delete-logs     Remove the logs directory
#   --prune-images    Also prune unused Docker images
#   -h, --help        Show this help
#

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="${ROOT_DIR}/infra"
LOG_DIR="${ROOT_DIR}/logs"
STOP_SCRIPT="${ROOT_DIR}/scripts/deploy/stop.sh"
SELF_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

KEEP_LOGS=true
PRUNE_IMAGES=false
WAIT_HOURS=""
_SCHEDULE_ONLY=false
PASSTHRU_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wait)
      if [[ $# -lt 2 ]]; then
        echo "[!] --wait requires a value in hours (decimal allowed), e.g. --wait 1.5"
        exit 1
      fi
      WAIT_HOURS="$2"
      shift 2
      ;;
    --keep-logs)
      KEEP_LOGS=true
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
    --delete-logs)
      KEEP_LOGS=false
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
    --prune-images)
      PRUNE_IMAGES=true
      PASSTHRU_ARGS+=("$1")
      shift
      ;;
    --scheduled-run)
      _SCHEDULE_ONLY=true
      shift
      ;;
    -h|--help)
      head -30 "$0" | grep -E "^#" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "[!] Unknown option: $1"
      exit 1
      ;;
  esac
done

_is_valid_hours() {
  local v="$1"
  [[ -n "$v" ]] || return 1
  [[ "$v" =~ ^[0-9]+([.][0-9]+)?$ ]] || return 1
  awk -v h="$v" 'BEGIN { if (h+0 > 0) exit 0; exit 1 }' >/dev/null 2>&1
}

_schedule_uninstall() {
  local hours="$1"
  if ! _is_valid_hours "$hours"; then
    echo "[!] Invalid --wait value: '${hours}'. Expected hours > 0 (decimal allowed), e.g. 0.25 or 2"
    exit 1
  fi

  mkdir -p "${LOG_DIR}"

  local now_ts job_id delay_seconds delay_minutes schedule_log job_script cron_tag
  now_ts="$(date +%Y-%m-%d_%H-%M-%S)"
  job_id="uninstall_${now_ts}_$$"
  schedule_log="${LOG_DIR}/${job_id}.log"
  job_script="${LOG_DIR}/.${job_id}.sh"
  cron_tag="# agentraffic-uninstall-wait ${job_id}"

  delay_seconds="$(awk -v h="$hours" 'BEGIN { printf "%.0f", (h * 3600) }')"
  if [[ -z "${delay_seconds}" || "${delay_seconds}" -le 0 ]]; then
    echo "[!] Failed to compute delay seconds from --wait ${hours}"
    exit 1
  fi
  delay_minutes="$(( (delay_seconds + 59) / 60 ))"

  cat > "${job_script}" <<EOF
#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="${ROOT_DIR}"
LOG_DIR="${LOG_DIR}"
JOB_ID="${job_id}"
CRON_TAG="${cron_tag}"
SCHEDULE_LOG="${schedule_log}"

cleanup() {
  if command -v crontab >/dev/null 2>&1; then
    (crontab -l 2>/dev/null || true) | grep -vF "\${CRON_TAG}" | crontab - 2>/dev/null || true
  fi
  rm -f "\$0" 2>/dev/null || true
}
trap cleanup EXIT

{
  echo "[*] Scheduled uninstall job started at: \$(date -Is)"
  echo "[*] Job id: \${JOB_ID}"
  echo "[*] Working dir: \${ROOT_DIR}"
  echo
} >> "\${SCHEDULE_LOG}" 2>&1

cd "\${ROOT_DIR}"

set +e
"${SELF_SCRIPT}" --scheduled-run ${PASSTHRU_ARGS[*]-} >> "\${SCHEDULE_LOG}" 2>&1
rc=\$?
set -e

{
  echo
  echo "[*] Scheduled uninstall finished at: \$(date -Is) (exit=\${rc})"
} >> "\${SCHEDULE_LOG}" 2>&1

exit "\${rc}"
EOF

  chmod 700 "${job_script}"

  echo "[*] Scheduling uninstall to run in ~${hours} hours (${delay_minutes} minutes)."
  echo "[*] Log will be written to: ${schedule_log}"

  if command -v at >/dev/null 2>&1; then
    echo "[*] Using 'at' for scheduling."
    echo "bash \"${job_script}\"" | at now +"${delay_minutes}" minutes >/dev/null
    echo "[✓] Scheduled via at. Check queued jobs with: atq"
    return 0
  fi

  if command -v crontab >/dev/null 2>&1; then
    echo "[*] 'at' not found; falling back to one-shot crontab entry."
    local run_at
    run_at="$(date -d "+${delay_minutes} minutes" "+%M %H %d %m *" 2>/dev/null || true)"
    if [[ -z "${run_at}" ]]; then
      echo "[!] Failed to compute cron schedule time."
      exit 1
    fi
    (crontab -l 2>/dev/null || true; echo "${run_at} bash \"${job_script}\" ${cron_tag}") | crontab -
    echo "[✓] Scheduled via cron. It will self-remove after running."
    return 0
  fi

  echo "[!] Neither 'at' nor 'crontab' available. Install 'at' or run in tmux/screen."
  exit 1
}

if [[ -n "${WAIT_HOURS}" && "${_SCHEDULE_ONLY}" == "false" ]]; then
  _schedule_uninstall "${WAIT_HOURS}"
  exit 0
fi

clear_gpu_resources() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[*] nvidia-smi not found; skipping GPU cleanup."
    return
  fi

  local run_user
  run_user="${USER:-$(id -un 2>/dev/null || echo unknown)}"
  echo "[*] Clearing GPU VRAM and cache artifacts for USER=${run_user}..."

  local gpu_indices
  gpu_indices="$(nvidia-smi --query-gpu=index --format=csv,noheader 2>/dev/null || true)"
  if [[ -z "${gpu_indices}" ]]; then
    echo "[*] No NVIDIA GPUs detected."
    return
  fi

  local pids
  pids="$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null || true)"

  _pid_is_user_vllm() {
    local p="$1"
    while [[ -n "$p" && "$p" != "1" ]]; do
      local owner cmd
      owner="$(ps -o user= -p "$p" 2>/dev/null | tr -d ' ')"
      cmd="$(ps -o args= -p "$p" 2>/dev/null || true)"
      if [[ "$owner" == "${USER}" ]] && echo "$cmd" | grep -q "vllm"; then
        return 0
      fi
      p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
    done
    return 1
  }

  if [[ -n "${pids}" ]]; then
    local pid
    for pid in ${pids}; do
      local owner
      owner="$(ps -o user= -p "${pid}" 2>/dev/null | tr -d ' ')"
      if [[ "$owner" == "${run_user}" ]]; then
        echo "[*] Stopping GPU process PID ${pid} (owned by ${run_user})..."
        kill -TERM "${pid}" 2>/dev/null || true
      elif _pid_is_user_vllm "${pid}"; then
        echo "[*] Stopping GPU process PID ${pid} (root-owned vllm subprocess)..."
        kill -TERM "${pid}" 2>/dev/null || true
      else
        echo "[*] Skipping GPU PID ${pid} (not owned by ${run_user})."
      fi
    done
    sleep 2
    for pid in ${pids}; do
      local owner
      owner="$(ps -o user= -p "${pid}" 2>/dev/null | tr -d ' ')"
      if [[ "$owner" == "${run_user}" ]] || _pid_is_user_vllm "${pid}"; then
        kill -KILL "${pid}" 2>/dev/null || true
      fi
    done
  fi

  rm -rf "${HOME}/.nv/ComputeCache" "${HOME}/.cache/nvidia" 2>/dev/null || true
}

echo "============================================================"
echo "  AgenTraffic — Uninstall"
echo "============================================================"
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "[!] docker is not installed or not on PATH."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[!] docker compose is not available. Please install Docker Compose v2."
  exit 1
fi

echo "[1/4] Stopping all services..."
if [[ -x "${STOP_SCRIPT}" ]]; then
  "${STOP_SCRIPT}" --volumes
else
  echo "[!] stop.sh not found, using fallback teardown..."
  cd "${COMPOSE_DIR}"
  docker compose -f docker-compose.yml -f docker-compose.monitoring.yml down --remove-orphans --volumes 2>/dev/null || true
  docker compose -f docker-compose.yml down --remove-orphans --volumes 2>/dev/null || true
fi

echo
echo "[2/4] Removing any remaining testbed containers..."
CONTAINERS=(
  "llm-backend"
  "agent-a"
  "agent-b" "agent-b-2" "agent-b-3" "agent-b-4" "agent-b-5"
  "chat-ui"
  "jaeger"
  "prometheus" "grafana" "cadvisor" "docker-mapping-exporter"
)
for container in "${CONTAINERS[@]}"; do
  if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "    Removing container: ${container}"
    docker rm -f "${container}" 2>/dev/null || true
  fi
done

echo
echo "[3/4] Cleaning up logs and artifacts..."
if [[ "${KEEP_LOGS}" == "false" && -d "${LOG_DIR}" ]]; then
  echo "    Removing logs under ${LOG_DIR}..."
  find "${LOG_DIR}" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
else
  echo "    Keeping logs (pass --delete-logs to remove)"
fi

echo
echo "[4/4] Clearing GPU resources..."
clear_gpu_resources

if [[ "${PRUNE_IMAGES}" == "true" ]]; then
  echo
  echo "[*] Pruning unused Docker images..."
  docker image prune -af
fi

echo
echo "============================================================"
echo "[✓] Uninstall complete."
echo "============================================================"
