# Experiment runner

`run_agentverse.sh` sends repeated AgentVerse requests to Agent A and records the full
response — including all LLM call timestamps and token counts — to a JSONL file.
It is the primary data-collection script for the paper experiments.

---

## Quick start

```bash
# Reproduce the paper: all three topologies, 500 runs, 4 agents
scripts/experiment/run_agentverse.sh

# Quick smoke test
scripts/experiment/run_agentverse.sh --topology full_mesh --runs 5

# Single topology
scripts/experiment/run_agentverse.sh --topology horizontal --runs 50
```

---

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `-t, --topology` | `all` | `horizontal` \| `vertical` \| `full_mesh` \| `all` |
| `-n, --runs` | `500` | Repetitions per topology |
| `-a, --agents` | `4` | Recruited sub-agents (fixed for paper) |
| `-r, --rounds` | `3` | Full-mesh discussion rounds |
| `-H, --host` | `localhost` | Agent A host |
| `-p, --port` | `8101` | Agent A port |
| `-o, --output-dir` | `./data/agentverse` | Where to write JSONL results |

---

## Output format

Results are written to a single JSONL file:

```
data/agentverse/<output-dir>/experiment_<topology>_n<agents>_<timestamp>.jsonl
```

Each line is one complete run — a JSON object with:

| Field | Description |
|-------|-------------|
| `run` | Run number within this batch |
| `topology` | `horizontal` / `vertical` / `full_mesh` |
| `force_agent_count` | Number of recruited sub-agents |
| `task` | Task prompt sent to the agent |
| `http_status` | HTTP status from Agent A |
| `elapsed_ms` | Wall-clock duration of the request |
| `duration_seconds` | Duration reported by the orchestrator |
| `stages` | Per-stage outputs (recruitment, decision, execution, evaluation) |
| `llm_requests` | List of individual LLM calls, each with `start_time_utc`, `duration_seconds`, `label`, `llm_meta` (token counts, latency) |

The `llm_requests` field is the primary data source for IAT analysis.

---

## Task pool

The script cycles through 10 general-purpose reasoning tasks (CAP theorem, TCP vs UDP,
gradient descent, etc.) round-robin across runs. The pool is defined at lines 80–91 of
the script. Extend it to increase task variety.

---

## Running via the queue

For long batches, use the experiment queue instead of running the script directly.
This handles testbed lifecycle (deploy/stop), GPU gating, and plot generation automatically.
See [scripts/queue/README.md](../queue/README.md).

```bash
# Via MCP tool (Claude Code):
queue_add_job("agentverse", {
    "topology": "all",
    "runs": 500,
    "agents": 4,
    "generate_plots": True,   # run paper figures after the experiment
})
```
