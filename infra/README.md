# Infrastructure

Docker Compose stack and environment configuration for agentraffic.

---

## Configuration files

| File | Purpose | Gitignored |
|---|---|---|
| `.env.example` | Template — copy to `.env` and fill in | No |
| `.env` | Your local config (secrets, model, tuning) | **Yes** |
| `network.env.example` | Template for distributed network topology | No |
| `network.env` | Subnet ranges and static IPs (distributed mode only) | **Yes** |

### Quick setup

```bash
cp infra/.env.example infra/.env
# Edit infra/.env — at minimum set HF_TOKEN
```

For distributed mode (the default), `deploy.sh` will auto-create `network.env` from the example on first run using the default subnet assignments. Edit `infra/network.env` if you need to change the address ranges.

---

## Deployment modes

Set `DEPLOYMENT_MODE` in `infra/.env`:

| Mode | Description |
|---|---|
| `distributed` | Separate Docker bridge networks per logical node (agent-a, agent-b, llm), connected via a shared inter-service bridge. Better for observing cross-service traffic. Requires `network.env`. **Default.** |
| `single` | All containers share one Docker bridge. Simpler setup; good for quick experiments. `network.env` is ignored. |

---

## Compose files

| File | Services |
|---|---|
| `docker-compose.yml` | Core stack: llm-backend, agent-a, agent-b (×4), jaeger, chat-ui |
| `docker-compose.monitoring.yml` | Monitoring sidecar: Prometheus, Grafana, cAdvisor |

The monitoring stack is opt-in — pass `--monitoring` to `scripts/deploy/deploy.sh`.

---

## Network emulation

When `DEPLOYMENT_MODE=distributed`, artificial latency/jitter/loss can be injected on the Docker bridge links via Linux `tc netem`. This is controlled in `infra/.env`:

```bash
ENABLE_NETWORK_EMULATION=1   # 0 = off (default)
NETWORK_DELAY_MS=10          # base delay per link
NETWORK_JITTER_MS=2          # ± jitter around base delay
NETWORK_LOSS_PERCENT=0       # packet loss (0–100)
```

Requires `NET_ADMIN` capability on the affected containers.

---

## Network topology (`network.env`)

Only used when `DEPLOYMENT_MODE=distributed`. Defines the subnet range for each logical node and the static IP assigned to each container:

```
172.20.0.0/24  — agent-a network
172.21.0.0/24  — agent-b network
172.22.0.0/24  — llm network
172.23.0.0/24  — inter-agent bridge (all services connect here)
```

The defaults in `network.env.example` match the paper's setup. Override them only if the ranges conflict with your host network.

---

## Monitoring dashboards

Grafana dashboards are provisioned automatically from `monitoring/grafana/provisioning/`. The `agentic-traffic.json` dashboard covers:

- LLM-call IAT histograms per topology
- Request concurrency and token throughput
- TCP byte rates (requires the host-side TCP metrics collector)

See [scripts/monitoring/](../scripts/monitoring/) for the TCP metrics collector setup.

---

## Cost tracking

Optional per-token cost annotation (set in `infra/.env`):

```bash
COST_PER_INPUT_TOKEN_USD=0.000003    # $3.00/1M input tokens
COST_PER_OUTPUT_TOKEN_USD=0.000015   # $15.00/1M output tokens
```

Set both to `0` (default) to disable. Useful when comparing local vLLM cost against cloud API cost for the same workload.
