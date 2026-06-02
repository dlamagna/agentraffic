# Experiment Queue

Schedules and runs AgentVerse topology experiments serially via a background daemon. Useful when running large batches of experiments (e.g. 500 runs × 3 topologies) without babysitting the terminal.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Interfaces                                          │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ Claude Code  │  │  add_job.sh  │                  │
│  │  (MCP tools) │  │  (CLI)       │                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         └────────────────┘                           │
│                   │                                  │
│       ┌───────────▼──────────────┐                   │
│       │     queue_manager.py     │                   │
│       │  queue/state/queue.json  │                   │
│       │  queue/state/history.jsonl│                  │
│       └───────────┬──────────────┘                   │
│                   │  poll every 5 s                  │
│       ┌───────────▼──────────────┐                   │
│       │     job_runner.py        │                   │
│       │   (background daemon)    │                   │
│       └───────────┬──────────────┘                   │
└───────────────────┼──────────────────────────────────┘
                    │ subprocess
          scripts/experiment/run_agentverse.sh
                    │
              data/agentverse/
```

### Key files

| Path | Purpose |
|------|---------|
| `scripts/queue/server.py` | FastMCP server — exposes queue tools to Claude Code |
| `scripts/queue/job_runner.py` | Background daemon — dequeues and executes jobs |
| `scripts/queue/queue_manager.py` | Queue state I/O (thread-safe, file-locked) |
| `scripts/queue/duration_estimator.py` | Duration heuristics + CLI |
| `scripts/queue/job_types.py` | Job type definition and command builder |
| `scripts/queue/add_job.sh` | Shell CLI for adding jobs |
| `scripts/queue/install_mcp.sh` | One-shot MCP registration script |
| `queue/state/queue.json` | Live queue state (auto-created) |
| `queue/state/history.jsonl` | Completed job history |
| `queue/state/daemon.pid` | Daemon PID (auto-created while running) |
| `queue/logs/daemon.log` | Daemon log |
| `queue/logs/job_<id>.log` | Per-job stdout/stderr |

---

## Setup

### 1. Install fastmcp

```bash
pip install fastmcp
# or: pip install -r requirements.txt
```

### 2. Register the MCP server (for Claude Code)

```bash
./scripts/queue/install_mcp.sh
```

This writes a `testbed-queue` entry to `.mcp.json`. Reload the Claude Code window to pick it up.

### 3. Verify

```bash
# Confirm the server starts
python -m scripts.queue.server
# Should print: FastMCP server running on stdio — Ctrl-C to exit

# Confirm the CLI works
./scripts/queue/add_job.sh --help
```

---

## Usage: Shell CLI

```bash
# Paper reproduction — all three topologies, 500 runs, 4 agents
./scripts/queue/add_job.sh --notes "paper reproduction"

# Single topology
./scripts/queue/add_job.sh --topology full_mesh --runs 100

# Insert at front of queue
./scripts/queue/add_job.sh --topology horizontal --runs 50 --front

# Dry-run: estimate duration without adding
./scripts/queue/add_job.sh --topology all --runs 500 --dry-run

# Wait for GPU to be free before starting
./scripts/queue/add_job.sh --topology full_mesh --runs 200 --wait-for-gpu-free
```

### Options

| Option | Description |
|--------|-------------|
| `--topology` | `horizontal` \| `vertical` \| `full_mesh` \| `all` (default: `all`) |
| `--runs` | Repetitions per topology (default: 500) |
| `--agents` | Recruited sub-agents (default: 4) |
| `--rounds` | Full-mesh discussion rounds (default: 3) |
| `--host` | Agent A host (default: localhost) |
| `--port` | Agent A port (default: 8101) |
| `--notes` | Free-text annotation stored with the job |
| `--position` | Insert at position N (0 = front) |
| `--front` | Shorthand for `--position 0` |
| `--wait-for-gpu-free` | Wait until `nvidia-smi` reports no active compute processes |
| `--gpu-wait-poll N` | Seconds between GPU checks (default: 60) |
| `--gpu-wait-timeout N` | Max seconds to wait (0 = indefinitely) |
| `--no-reset` | Skip `deploy.sh` before the job (default: reset is **on**) |
| `--no-shutdown` | Skip `stop.sh` after the job (default: shutdown is **on**) |
| `--generate-plots` | Run `scripts/analysis/plot_paper_figures.py` on the output after the experiment |
| `--dry-run` | Estimate duration only, do not add |

---

## Usage: MCP Tools (Claude Code)

With the MCP server registered, Claude Code can call these tools directly.

### `queue_add_job`

```python
queue_add_job(
    job_type = "agentverse",
    params   = {"topology": "all", "runs": 500, "agents": 4},
    notes    = "paper reproduction run",
)
# Returns: job_id, estimated_duration, queue_position
```

Full example with all lifecycle options:

```python
queue_add_job(
    job_type = "agentverse",
    params   = {
        "topology":                    "all",
        "runs":                        500,
        "agents":                      4,
        # Testbed lifecycle — both default to True
        "reset_testbed_at_start":      True,   # run stop.sh then deploy.sh before the experiment
        "shutdown_testbed_when_done":  True,   # run stop.sh when the experiment finishes
        # GPU gating — wait for external processes to clear before deploying
        "wait_for_gpu_free":           True,
        "gpu_wait_poll_interval_s":    60,
        # Analysis — generate paper figures from the JSONL output
        "generate_plots":              True,
    },
    notes = "paper reproduction — full lifecycle",
)
```

**Lifecycle order** when both reset and GPU-wait are enabled:

1. `stop.sh` — tear down our own stack so our vLLM doesn't block the GPU check
2. GPU wait — poll `nvidia-smi` until only external processes remain
3. `deploy.sh` — start a fresh stack
4. Experiment runs
5. `stop.sh` — shut down when done
6. `plot_paper_figures.py` — generate paper figures (if `generate_plots=True`)

### Other tools

| Tool | Description |
|------|-------------|
| `queue_status` | Counts by status, estimated remaining time, daemon alive flag |
| `queue_list_jobs` | List all jobs; filter by status; optionally include history |
| `queue_get_job` | Full detail for one job by ID or 8-char prefix |
| `queue_get_history` | Recent completed/failed jobs |
| `queue_estimate_duration` | Estimate a job's duration without adding it |
| `queue_estimate_total` | Total estimated time for pending + running jobs |
| `queue_start_daemon` | Start the background daemon |
| `queue_stop_daemon` | Stop the daemon (graceful or force) |
| `queue_cancel_running` | Kill the current job subprocess |
| `queue_pause` | Stop daemon after current job completes |
| `queue_remove_job` | Remove a pending job |
| `queue_cancel_job` | Cancel a pending job (stays in history) |
| `queue_move_job` | Reorder a job (position=0 → front) |
| `queue_tail_log` | View daemon log or per-job log |
| `queue_annotate_job` | Add or replace notes on any job |
| `queue_adopt_running` | Import a manually-started experiment into the queue |
| `queue_import_history` | Import pre-queue result directories into history |

---

## Starting the daemon

```bash
# 1. Add jobs
./scripts/queue/add_job.sh --topology all --runs 500 --notes "run A"
./scripts/queue/add_job.sh --topology full_mesh --runs 200 --notes "run B"

# 2. Check estimated total time
python -m scripts.queue.duration_estimator --queue queue/state/queue.json

# 3. Start daemon
python -m scripts.queue.job_runner

# Or via MCP:
#   queue_start_daemon()
```

The daemon logs to `queue/logs/daemon.log`. Each job also gets its own log at `queue/logs/job_<id>.log`.

**Important:** The daemon does not hot-reload. Any edit to `job_runner.py`, `job_types.py`, or `plot_paper_figures.py` requires a restart to take effect. Use force=True if the daemon is stuck in a GPU wait:

```bash
queue_stop_daemon(force=True)
# clear stale PID if needed: rm queue/state/daemon.pid
queue_start_daemon()
```

---

## Duration estimation

Estimates are based on per-run medians from the paper (Table 2):

| Topology | Median run duration |
|----------|---------------------|
| Sequential (`horizontal`) | ~82 s/run |
| Star (`vertical`) | ~105 s/run |
| Full Mesh (`full_mesh`) | ~32 s/run |

```bash
# Estimate a single job
python -m scripts.queue.duration_estimator --type agentverse --topology all --runs 500

# Estimate the full queue
python -m scripts.queue.duration_estimator --queue queue/state/queue.json
```

---

## Results traceability

Every completed job writes a `queue_manifest.json` to its results directory:

```json
{
  "queue_schema_version": "1",
  "queue_job_id":         "3f8a1b2c-...",
  "job_type":             "agentverse",
  "notes":                "paper reproduction run",
  "params":               {"topology": "all", "runs": 500},
  "expected_duration":    "11h 23m 30s",
  "enqueued_at":          "2026-05-27T09:00:00Z",
  "started_at":           "2026-05-27T09:00:30Z",
  "completed_at":         "2026-05-27T20:24:00Z",
  "exit_code":            0,
  "output_path":          "data/agentverse/experiment_2026-05-27_...",
  "stdout_file":          "queue/logs/job_3f8a1b2c.log"
}
```

The same record is appended to `queue/state/history.jsonl` so runs are searchable long after completion:

```bash
# Find all completed runs
grep '"agentverse"' queue/state/history.jsonl | jq '{id, notes, completed_at, exit_code}'

# Find failed runs
jq 'select(.status=="failed") | {id, notes, exit_code}' queue/state/history.jsonl
```

---

## Queue state files

| File | Format | Description |
|------|--------|-------------|
| `queue/state/queue.json` | JSON | All jobs (pending/running/completed/failed) |
| `queue/state/history.jsonl` | JSONL | Completed job archive |
| `queue/state/daemon.pid` | Text | Daemon PID (removed on clean exit) |
| `queue/logs/daemon.log` | Text | Daemon stdout/stderr |
| `queue/logs/job_<id>.log` | Text | Per-job stdout/stderr |

### Job status values

| Status | Meaning |
|--------|---------|
| `pending` | Waiting to run |
| `waiting_for_gpu` | Waiting for `nvidia-smi` to report no active compute processes |
| `running` | Currently executing |
| `completed` | Exited with code 0 |
| `failed` | Exited with non-zero code |
| `cancelled` | Manually cancelled before running |
