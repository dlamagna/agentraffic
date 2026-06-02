# agentraffic

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![CI](https://github.com/dlamagna/agentraffic/actions/workflows/ci.yml/badge.svg)](https://github.com/dlamagna/agentraffic/actions/workflows/ci.yml)

A multi-layer measurement framework for studying how coordination topology shapes LLM-call arrival processes in multi-agent systems.

This is the open-source release accompanying the paper:

> **Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology**
> Davide Lamagna, Berta Serracanta, Alberto Rodriguez Natal, Gábor Rétvári, Albert Cabellos
> *3rd ACM SIGCOMM Workshop on Networks for AI Computing (NAIC 2026)*

---

## Overview

The framework runs a multi-agent workflow ([AgentVerse](https://arxiv.org/pdf/2308.10848)) under three coordination topologies and simultaneously measures traffic across four layers:

| Layer | Metrics collected |
|---|---|
| Application | LLM-call inter-arrival time (IAT), call latency, time-to-first-token, token counts |
| LLM backend | Token throughput, request rate, in-flight requests, concurrency peaks |
| Container | Per-container CPU, memory, and interface byte counters |
| Network | Byte/packet counts per directed service pair, connection events, burstiness, inter-arrival jitter |

**Main findings of the paper:**
- Coordination topology determines the *shape* of the LLM-call arrival process, independently of task rate.
- Fan-out topologies (star, full mesh) produce bimodal IAT distributions: a near-zero *fan-out mode* (concurrent dispatch) and a multi-second *reasoning-phase mode* (between coordination rounds). Sequential coordination produces a near-unimodal distribution.
- The reasoning-phase component is best described by a log-normal distribution across all three topologies; the exponential (Poisson null model) is decisively rejected.
- These topology-induced differences propagate beyond the application layer, affecting inference-layer concurrency and network-layer TCP byte rates.

---

## Architecture

```
┌──────────────┐   POST /agentverse   ┌────────────────────────┐
│   Experiment │ ──────────────────▶  │   Agent A (port 8101)  │
│   runner /   │                      │   AgentVerseOrchestrator│
│   HTTP client│                      │   sequential / star /   │
└──────────────┘                      │   full_mesh             │
                                      └────────┬───────────────┘
                                               │ parallel calls (full_mesh / star)
                        ┌──────────────────────┼──────────────────────┐
                        ▼                      ▼                      ▼
               ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
               │  Agent B :8102 │  │  Agent B :8103 │  │  Agent B :8104 │
               │  (worker)      │  │  (worker)      │  │  (worker)      │
               └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
                       └──────────────────┬┘──────────────────┘
                                          ▼
                              ┌───────────────────────┐
                              │  LLM backend :8000    │
                              │  AsyncVLLM (vLLM)     │
                              │  Llama-3.2-3B-Instruct│
                              └───────────────────────┘

Monitoring: Prometheus + Grafana + Jaeger + cAdvisor + passive TCP collector
```

The framework is organised as containerised services on Docker bridge networks. A passive packet-capture collector reconstructs TCP flows and exports metrics to Prometheus; application traces go to Jaeger; container resource metrics are collected via cAdvisor. All layers share agent identifiers and timestamps so per-run metrics can be joined across layers directly.

### Coordination topologies

| Topology | `force_structure` | Protocol |
|---|---|---|
| Sequential | `horizontal` | Agents called one at a time in a fixed turn order |
| Star | `vertical` | A designated solver proposes first; all remaining agents are dispatched simultaneously as parallel reviewers |
| Full Mesh | `full_mesh` | All N×(N−1) directed peer-message pairs submitted concurrently each round |

The paper fixes agent count at **four recruited sub-agents** — large enough to exhibit fan-out and peer-coordination effects while keeping token volumes within the model's context window.

### LLM backend

The inference backend runs vLLM's `AsyncLLMEngine` with any HuggingFace-hosted model that vLLM supports, configured via `LLM_MODEL` in `infra/.env`. The paper uses **Llama-3.2-3B-Instruct** with the following settings:
- Effective concurrency limit: 8 requests
- Maximum model length: 11,200 tokens
- Default completion cap: 6,144 tokens

The asynchronous engine accepts concurrent requests from multiple agents and schedules them for batching on the GPU, making queueing, in-flight request count, and token throughput observable parts of the framework.

---

## Quick start

### Prerequisites

- Docker with the [NVIDIA container runtime](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (GPU required for vLLM)
- A Hugging Face token (only required for gated models such as Llama — not needed for open models like Qwen)
- `jq` and `curl` (for the experiment runner)

### 1. Configure

```bash
cp infra/.env.example infra/.env
# Edit infra/.env — at minimum set LLM_MODEL and HF_TOKEN (if using a gated model)
```

The default model is `meta-llama/Llama-3.2-3B-Instruct` (used in the paper). To use a different model, set `LLM_MODEL` in `infra/.env` to any vLLM-compatible HuggingFace model ID:

```bash
# Non-gated alternative (no HF token required)
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct

# Larger Llama variant
LLM_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

If you change the model, recalculate the KV-cache token limits for your GPU:

```bash
python scripts/deploy/kv_cache_calc.py --free-gb <FREE_GiB>
```

### 2. Start the stack

```bash
# Core agents + LLM + Jaeger
scripts/deploy/deploy.sh

# Core + monitoring dashboards (Prometheus, Grafana, cAdvisor)
scripts/deploy/deploy.sh --monitoring
```

The LLM backend takes a few minutes to download and load the model on first run.

### 3. Run an experiment

```bash
# Reproduce the paper: all three topologies, 500 runs each, 4 sub-agents
scripts/experiment/run_agentverse.sh

# Quick sanity check (10 runs, full_mesh only)
scripts/experiment/run_agentverse.sh --topology full_mesh --runs 10

# Single topology
scripts/experiment/run_agentverse.sh --topology horizontal --agents 4 --runs 50
```

Results are written to `data/agentverse/experiment_<topology>_n<agents>_<timestamp>.jsonl`.
Each line is one run: topology label, elapsed time, and the full `llm_requests` trace (prompt, response, token counts, IAT timestamps).

### 4. View traces and dashboards

| Service | URL | Notes |
|---|---|---|
| Jaeger | http://localhost:16686 | Per-call spans across agent-a → agent-b → llm-backend |
| Grafana | http://localhost:3001 | IAT histograms, concurrency, TCP byte rates (admin/admin) |
| Prometheus | http://localhost:9090 | Raw metrics |
| AgentVerse viewer | http://localhost:3000/agentverse | Per-run LLM call graph |

### 5. Stop

```bash
scripts/deploy/stop.sh           # keeps images and model cache
scripts/deploy/stop.sh --volumes # also removes model cache
```

---

## Sending a single request (curl)

```bash
# Full-mesh, 4 agents, 3 rounds
curl -X POST http://localhost:8101/agentverse \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Compare TCP and UDP and explain when to use each.",
    "force_structure": "full_mesh",
    "force_agent_count": 4,
    "full_mesh_max_rounds": 3,
    "max_iterations": 1
  }'

# Sequential
curl -X POST http://localhost:8101/agentverse \
  -H "Content-Type: application/json" \
  -d '{"task": "Explain gradient descent.", "force_structure": "horizontal", "force_agent_count": 4}'

# Star
curl -X POST http://localhost:8101/agentverse \
  -H "Content-Type: application/json" \
  -d '{"task": "Explain gradient descent.", "force_structure": "vertical", "force_agent_count": 4}'
```

`POST /agentverse` parameters:

| Field | Type | Default | Description |
|---|---|---|---|
| `task` | string | required | Task prompt |
| `force_structure` | string | LLM decides | `horizontal` \| `vertical` \| `full_mesh` |
| `force_agent_count` | int | LLM decides | Number of recruited sub-agents (0 = solo) |
| `full_mesh_max_rounds` | int | `FULL_MESH_MAX_ROUNDS` env | Discussion rounds for full_mesh |
| `max_iterations` | int | 3 | AgentVerse evaluation iterations |
| `success_threshold` | int | 70 | Score (0–100) to accept and stop |
| `stream` | bool | false | Stream progress as Server-Sent Events |

---

## Adapting to a different framework

The framework communicates with the LLM backend purely over HTTP. Swapping the workflow implementation only requires changing the orchestrator.

### Option A — Replace the orchestrator class

`agents/agent_a/orchestrator.py` implements `AgentVerseOrchestrator`. Create a new class that exposes the same `run_workflow(...)` interface and wire it into `agents/agent_a/server.py`:

```python
# agents/agent_a/server.py  (simplified)
from agents.agent_a.my_framework_orchestrator import MyOrchestrator

orchestrator = MyOrchestrator(logger=logger, tracer=self.tracer)
result = orchestrator.run_workflow(task=task, task_id=task_id, ...)
```

The LLM backend (`LLM_SERVER_URL`) and worker agent slots (`AGENT_B_URLS`) are injected via environment variables — your orchestrator can reuse the same containers and monitoring stack unchanged.

### Option B — Point an external framework at the LLM backend

If your framework manages its own agents, point it at the vLLM backend on `http://localhost:8000`:

```
POST http://localhost:8000/chat                  {"prompt": "..."}
POST http://localhost:8000/v1/chat/completions   (OpenAI-compatible)
GET  http://localhost:8000/metrics               (Prometheus)
```

The monitoring stack collects metrics regardless of which framework generates the calls.

### Option C — Replace Agent B with framework-native workers

Agent B is a thin HTTP wrapper that forwards a prompt to the LLM backend and returns the response. Replace it with any service that accepts:

```
POST /subtask   {"subtask": "<prompt>"}
→ {"output": "<response>", "llm_meta": {...}}
```

---

## TCP metrics collection

Network-layer measurements use a passive packet-capture collector that runs on the host and exports Prometheus metrics.

```bash
# Requires access to the Docker bridge interface
sudo python scripts/monitoring/tcp_metrics_collector.py \
  --interface br-$(docker network inspect infra_agent-net -f '{{.Id}}' | head -c 12)
```

Prometheus scrapes it at `http://host.docker.internal:9102/metrics` (configured in `infra/monitoring/prometheus.yml`).

---

## Repository structure

```
├── agents/
│   ├── agent_a/              # Orchestrator (AgentVerse workflow)
│   │   ├── orchestrator.py   # Workflow: recruit → discuss → execute → evaluate
│   │   ├── prompts.py        # All prompt templates
│   │   └── server.py         # HTTP server: POST /agentverse, POST /task
│   ├── agent_b/              # Worker agent (forwards subtasks to LLM backend)
│   └── common/               # Shared telemetry, tracing, metrics logger
├── llm/
│   └── serve_llm.py          # AsyncVLLM backend with Prometheus metrics
├── infra/
│   ├── docker-compose.yml
│   ├── docker-compose.monitoring.yml
│   └── monitoring/           # Prometheus config + Grafana dashboards
├── scripts/
│   ├── deploy/               # deploy.sh / stop.sh
│   ├── experiment/           # run_agentverse.sh — data collection script
│   ├── analysis/             # plot_paper_figures.py — reproduces paper figures
│   ├── queue/                # Experiment queue daemon + MCP server
│   ├── monitoring/           # TCP metrics collector + Docker mapping exporter
│   └── ci/                   # smoketest.sh
├── tests/                    # Pure-Python unit tests (no GPU required)
└── ui/agentverse/            # Browser-based run viewer
```

---

## Citation

```bibtex
@inproceedings{lamagna2026agentraffic,
  title     = {Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology},
  author    = {Lamagna, Davide and Serracanta, Berta and Rodriguez Natal, Alberto and R{\'e}tv{\'a}ri, G{\'a}bor and Cabellos, Albert},
  booktitle = {3rd ACM SIGCOMM Workshop on Networks for AI Computing (NAIC)},
  year      = {2026},
}
```

---

---

## Troubleshooting

**GPU not detected**
Ensure the NVIDIA container runtime is installed and `docker info | grep -i runtime` shows `nvidia`. Run `nvidia-smi` on the host to confirm the driver is loaded.

**HuggingFace token invalid / model download fails**
Check `HF_TOKEN` in `infra/.env`. For gated models (e.g. Llama), the token must have read access — request it on the model's HuggingFace page. For open models (e.g. Qwen), `HF_TOKEN` can be left empty.

**Port conflicts**
Default ports: 8000 (LLM), 8101–8105 (agents), 3000 (UI), 16686 (Jaeger), 3001 (Grafana), 9090 (Prometheus). Change them in `infra/docker-compose.yml` if needed.

**Model download timeout**
The first `deploy.sh` run downloads ~6 GB. If it times out, restart — vLLM resumes from the Hugging Face hub cache (`~/.cache/huggingface` on the host, mounted into the container).

**`docker compose config` fails**
The compose files use `infra/.env` for substitution. Copy and fill `infra/.env.example` first:
```bash
cp infra/.env.example infra/.env
```

**Experiment runner exits immediately**
Confirm the stack is up (`docker compose ps`) and Agent A is healthy (`curl http://localhost:8101/health`).

---

## Documentation

| Topic | File |
|-------|------|
| Running experiments | [scripts/experiment/README.md](scripts/experiment/README.md) |
| Experiment queue (batch runs, lifecycle, plots) | [scripts/queue/README.md](scripts/queue/README.md) |
| Docker Compose stack and environment config | [infra/README.md](infra/README.md) |
| AgentVerse browser UI | [ui/agentverse/README.md](ui/agentverse/README.md) |
| Contributing guide | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Changelog | [CHANGELOG.md](CHANGELOG.md) |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup, code style, and PR guidelines.
Bugs and feature requests go in [GitHub Issues](../../issues).

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for the full text.
