#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$PATH"
# =============================================================================
# scripts/experiment/run_agentverse.sh
# =============================================================================
# Run repeated AgentVerse tasks and collect IAT / metrics data.
#
# This script reproduces the topology experiments in the paper:
#   Sequential (horizontal), Star (vertical), Full Mesh — each N repetitions.
#
# Usage:
#   scripts/experiment/run_agentverse.sh [OPTIONS]
#
# Options:
#   -t, --topology   TOPOLOGY  horizontal | vertical | full_mesh  (default: all)
#   -n, --runs       N         Repetitions per topology            (default: 500)
#   -a, --agents     N         Recruited sub-agents                (default: 4)
#   -r, --rounds     N         Full-mesh discussion rounds         (default: 3)
#   -H, --host       HOST      Agent A host                        (default: localhost)
#   -p, --port       PORT      Agent A port                        (default: 8101)
#   -o, --output-dir DIR       Where to store JSONL results        (default: ./data/agentverse)
#   -h, --help                 Show this help
#
# Examples:
#   # Reproduce all three topologies (500 runs each, 4 agents — paper default)
#   scripts/experiment/run_agentverse.sh
#
#   # Quick 10-run sanity check with full_mesh only
#   scripts/experiment/run_agentverse.sh -t full_mesh -n 10
#
#   # Custom run with 3 agents
#   scripts/experiment/run_agentverse.sh -a 3 -n 50
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --------------- defaults ---------------
TOPOLOGY="all"
N_RUNS=500
N_AGENTS=4
MESH_ROUNDS=3
AGENT_A_HOST="localhost"
AGENT_A_PORT=8101
OUTPUT_DIR="${REPO_ROOT}/data/agentverse"

# --------------- argument parsing ---------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--topology)  TOPOLOGY="$2";    shift 2 ;;
    -n|--runs)      N_RUNS="$2";      shift 2 ;;
    -a|--agents)    N_AGENTS="$2";    shift 2 ;;
    -r|--rounds)    MESH_ROUNDS="$2"; shift 2 ;;
    -H|--host)      AGENT_A_HOST="$2"; shift 2 ;;
    -p|--port)      AGENT_A_PORT="$2"; shift 2 ;;
    -o|--output-dir) OUTPUT_DIR="$2"; shift 2 ;;
    -h|--help)
      grep -E "^#" "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "[!] Unknown option: $1"; exit 1 ;;
  esac
done

AGENT_A_URL="http://${AGENT_A_HOST}:${AGENT_A_PORT}/agentverse"

# Validate topology argument
if [[ "$TOPOLOGY" != "all" && "$TOPOLOGY" != "horizontal" && "$TOPOLOGY" != "vertical" && "$TOPOLOGY" != "full_mesh" ]]; then
  echo "[!] Invalid topology: $TOPOLOGY (choose from: horizontal, vertical, full_mesh, all)"
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
LOG_FILE="${OUTPUT_DIR}/experiment_${TOPOLOGY}_n${N_AGENTS}_${TIMESTAMP}.jsonl"

# --------------- task pool ---------------
# General-purpose reasoning tasks.  Extend this list for more variety.
TASKS=(
  "What are the main trade-offs between microservices and monolithic architectures?"
  "Explain the CAP theorem and give a real-world example of each combination."
  "How does gradient descent work, and what are common failure modes?"
  "Compare TCP and UDP: when would you choose each?"
  "What is the difference between a mutex and a semaphore?"
  "Explain eventual consistency and give an example of a system that uses it."
  "What are the key differences between SQL and NoSQL databases?"
  "How does public-key cryptography work in HTTPS?"
  "What is a distributed hash table and how does it handle node failures?"
  "Explain backpressure in reactive systems and why it matters."
)
N_TASKS="${#TASKS[@]}"

run_topology() {
  local topo="$1"
  echo ""
  echo "============================================================"
  echo "  Topology : $topo"
  echo "  Runs     : $N_RUNS"
  echo "  Agents   : $N_AGENTS"
  echo "  Output   : $LOG_FILE"
  echo "============================================================"

  local ok=0 fail=0

  for i in $(seq 1 "$N_RUNS"); do
    local task="${TASKS[$((  (i - 1) % N_TASKS  ))]}"

    local payload
    payload=$(jq -n \
      --arg task "$task" \
      --arg topo "$topo" \
      --argjson agents "$N_AGENTS" \
      --argjson rounds "$MESH_ROUNDS" \
      '{
        task: $task,
        force_structure: $topo,
        force_agent_count: $agents,
        full_mesh_max_rounds: $rounds,
        max_iterations: 1,
        success_threshold: 0
      }')

    local t0
    t0=$(date +%s%3N)

    local response http_status
    if response=$(curl -s -w "\n__HTTP_STATUS__%{http_code}" \
                       -X POST "$AGENT_A_URL" \
                       -H "Content-Type: application/json" \
                       -d "$payload" \
                       --max-time 300 2>/dev/null); then
      http_status=$(echo "$response" | grep '__HTTP_STATUS__' | sed 's/__HTTP_STATUS__//')
      response=$(echo "$response" | grep -v '__HTTP_STATUS__')
    else
      http_status="000"
      response="{}"
    fi

    local t1
    t1=$(date +%s%3N)
    local elapsed_ms=$(( t1 - t0 ))

    local record
    record=$(jq -n \
      --arg run "$i" \
      --arg topo "$topo" \
      --arg task "$task" \
      --argjson agents "$N_AGENTS" \
      --argjson status "$http_status" \
      --argjson elapsed_ms "$elapsed_ms" \
      --argjson ts "$(date +%s)" \
      '{
        run: ($run | tonumber),
        topology: $topo,
        force_agent_count: $agents,
        task: $task,
        http_status: $status,
        elapsed_ms: $elapsed_ms,
        timestamp: $ts
      }')

    # Merge the agent response (llm_requests, etc.) into the record if valid JSON
    if echo "$response" | jq . > /dev/null 2>&1; then
      record=$(echo "$record $response" | jq -s 'add')
    fi

    echo "$record" >> "$LOG_FILE"

    if [[ "$http_status" == "200" ]]; then
      ok=$(( ok + 1 ))
      printf "  [%4d/%d] %-10s  %4dms  OK\n" "$i" "$N_RUNS" "$topo" "$elapsed_ms"
    else
      fail=$(( fail + 1 ))
      printf "  [%4d/%d] %-10s  %4dms  FAIL (HTTP %s)\n" "$i" "$N_RUNS" "$topo" "$elapsed_ms" "$http_status"
    fi
  done

  echo ""
  echo "  Done: $ok OK, $fail failed"
}

# --------------- main ---------------
echo "AgenTraffic — AgentVerse Experiment"
echo "  Timestamp : $TIMESTAMP"
echo "  Endpoint  : $AGENT_A_URL"
echo ""

# Verify Agent A is reachable
if ! curl -sf "http://${AGENT_A_HOST}:${AGENT_A_PORT}/agentverse" \
          --max-time 5 -o /dev/null 2>/dev/null; then
  # A GET with no task_id returns 400 — that's fine, the server is up
  code=$(curl -so /dev/null -w "%{http_code}" \
              "http://${AGENT_A_HOST}:${AGENT_A_PORT}/agentverse" \
              --max-time 5 2>/dev/null || echo "000")
  if [[ "$code" == "000" ]]; then
    echo "[!] Agent A not reachable at $AGENT_A_URL"
    echo "    Start the stack with: docker compose -f infra/docker-compose.yml up -d"
    exit 1
  fi
fi
echo "[✓] Agent A reachable"

if [[ "$TOPOLOGY" == "all" ]]; then
  for topo in horizontal vertical full_mesh; do
    run_topology "$topo"
  done
else
  run_topology "$TOPOLOGY"
fi

echo ""
echo "[✓] Results written to: $LOG_FILE"
