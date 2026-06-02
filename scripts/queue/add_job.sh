#!/usr/bin/env bash
# =============================================================================
# add_job.sh — Add an AgentVerse experiment job to the queue
# =============================================================================
#
# Usage:
#   ./scripts/queue/add_job.sh [options]
#
# Options:
#   --topology  TOPOLOGY    horizontal | vertical | full_mesh | all (default: all)
#   --runs      N           Repetitions per topology (default: 500)
#   --agents    N           Recruited sub-agents (default: 4)
#   --rounds    N           Full-mesh discussion rounds (default: 3)
#   --host      HOST        Agent A host (default: localhost)
#   --port      PORT        Agent A port (default: 8101)
#   --notes     TEXT        Free-text annotation for this job
#   --position  N           Queue insert position (0=front; default: end)
#   --front                 Shorthand for --position 0
#   --wait-for-gpu-free     Wait until nvidia-smi reports no active compute processes
#   --gpu-wait-poll N       Seconds between GPU checks (default: 60)
#   --gpu-wait-timeout N    Max seconds to wait for GPU (0 = indefinitely)
#   --dry-run               Estimate duration only, do not add to queue
#
# Examples:
#   # Reproduce the paper (all topologies, 500 runs, 4 agents)
#   ./scripts/queue/add_job.sh --notes "paper reproduction"
#
#   # Single topology, 100 runs
#   ./scripts/queue/add_job.sh --topology full_mesh --runs 100 --notes "quick validation"
#
#   # Insert at front of queue
#   ./scripts/queue/add_job.sh --topology horizontal --runs 50 --front
#
#   # Estimate duration without adding
#   ./scripts/queue/add_job.sh --topology all --runs 500 --dry-run
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
    source "$REPO_ROOT/.venv/bin/activate"
fi

PYTHON="${REPO_ROOT}/.venv/bin/python3"
[[ -x "$PYTHON" ]] || PYTHON="python3"

JOB_TYPE="agentverse"
NOTES=""
POSITION="null"
DRY_RUN=0

declare -A PARAMS

while [[ $# -gt 0 ]]; do
    case "$1" in
        --topology)          PARAMS[topology]="\"$2\"";              shift 2 ;;
        --runs)              PARAMS[runs]="$2";                      shift 2 ;;
        --agents)            PARAMS[agents]="$2";                    shift 2 ;;
        --rounds)            PARAMS[rounds]="$2";                    shift 2 ;;
        --host)              PARAMS[host]="\"$2\"";                  shift 2 ;;
        --port)              PARAMS[port]="$2";                      shift 2 ;;
        --notes)             NOTES="$2";                             shift 2 ;;
        --position)          POSITION="$2";                          shift 2 ;;
        --front)             POSITION="0";                           shift   ;;
        --dry-run)           DRY_RUN=1;                              shift   ;;
        --wait-for-gpu-free) PARAMS[wait_for_gpu_free]="true";       shift   ;;
        --gpu-wait-poll)     PARAMS[gpu_wait_poll_interval_s]="$2";  shift 2 ;;
        --gpu-wait-timeout)  PARAMS[gpu_wait_timeout_s]="$2";        shift 2 ;;
        -h|--help)
            sed -n '3,50p' "$0" | sed 's/^# //' | sed 's/^#//'
            exit 0
            ;;
        *)
            echo "WARNING: Unknown option '$1' (ignored)"
            shift
            ;;
    esac
done

# Build params JSON
PARAMS_JSON="{"
FIRST=1
for key in "${!PARAMS[@]}"; do
    val="${PARAMS[$key]}"
    [[ $FIRST -eq 0 ]] && PARAMS_JSON+=","
    PARAMS_JSON+="\"${key}\": ${val}"
    FIRST=0
done
PARAMS_JSON+="}"

# ---------------------------------------------------------------------------
# Dry-run: estimate duration only
# ---------------------------------------------------------------------------
if [[ $DRY_RUN -eq 1 ]]; then
    echo "DRY RUN — estimating duration (job will not be added)"
    echo ""
    "$PYTHON" -c "
import sys, json
sys.path.insert(0, '$REPO_ROOT')
from scripts.queue.duration_estimator import estimate_job_duration, format_duration
params = json.loads('$PARAMS_JSON')
secs = estimate_job_duration('$JOB_TYPE', params)
print(f'  Topology  : {params.get(\"topology\", \"all\")}')
print(f'  Runs      : {params.get(\"runs\", 500)} per topology')
print(f'  Estimated : ~{format_duration(secs)}')
"
    exit 0
fi

# ---------------------------------------------------------------------------
# Add job
# ---------------------------------------------------------------------------
RESULT=$("$PYTHON" -c "
import sys, json
sys.path.insert(0, '$REPO_ROOT')
from scripts.queue.queue_manager import add_job
from scripts.queue.duration_estimator import format_duration

params   = json.loads('$PARAMS_JSON')
position = ($POSITION) if '$POSITION' != 'null' else None
job      = add_job('$JOB_TYPE', params, notes='$NOTES', position=position)

dur = job.get('expected_duration') or 'unknown'
print(json.dumps({
    'job_id':    job['id'],
    'type':      job['type'],
    'status':    job['status'],
    'topology':  params.get('topology', 'all'),
    'runs':      params.get('runs', 500),
    'estimated': dur,
    'notes':     job['notes'],
}, indent=2))
")

echo "Job added to queue:"
echo "$RESULT"
echo ""

PENDING=$("$PYTHON" -c "
import sys
sys.path.insert(0, '$REPO_ROOT')
from scripts.queue.queue_manager import pending_count
print(pending_count())
" 2>/dev/null || echo "?")

echo "Queue now has $PENDING pending job(s)."
echo "  Total estimate : $("$PYTHON" -m scripts.queue.duration_estimator --queue "$REPO_ROOT/queue/state/queue.json" 2>/dev/null | grep 'Total' || echo '(run: python -m scripts.queue.duration_estimator --queue queue/state/queue.json)')"
echo ""
echo "To start the daemon: $PYTHON -m scripts.queue.job_runner"
