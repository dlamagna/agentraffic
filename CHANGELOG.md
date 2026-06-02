# Changelog

All notable changes to this project will be documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.1.0] — 2026-05-28

Initial open-source release accompanying the NAIC 2026 paper:
> *Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology*
> Lamagna et al., 3rd ACM SIGCOMM Workshop on Networks for AI Computing (NAIC 2026)

### Added

- **AgentVerse orchestrator** (`agents/agent_a/`) implementing the four-stage workflow: expert recruitment → discussion → execution → evaluation, across three coordination topologies (sequential, star, full mesh).
- **Worker agent** (`agents/agent_b/`) — thin HTTP wrapper forwarding subtasks to the LLM backend.
- **vLLM backend** (`llm/`) — `AsyncLLMEngine` serving Llama-3.2-3B-Instruct with Prometheus metrics.
- **Monitoring stack** — Prometheus, Grafana, Jaeger, cAdvisor, and passive TCP packet-capture collector.
- **Experiment runner** (`scripts/experiment/run_agentverse.sh`) — reproduces the paper results across all three topologies.
- **Browser UI** (`ui/agentverse/`) — per-run LLM call graph viewer with topology selector and SVG diagram.
- **Docker Compose** setup for all services on bridged Docker networks.
- MIT License.
