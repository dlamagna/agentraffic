# Changelog

All notable changes to this project will be documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

- **Static demo fixtures** (`ui/agentverse/fixtures/`): 12 real recorded runs from the paper experiments (3 topologies × 4 tasks), sanitised, each with a reconstructed SSE replay (`events.json`) and an `index.json` provenance manifest.
- **`scripts/demo/generate_fixtures.py`**: picks representative runs from the paper data, removes internal endpoints and trace IDs, and checks that the discussion-stage IATs reproduce the paper's Table 2.
- **`scripts/demo/sse_events.py`**: rebuilds the orchestrator's SSE progress stream from a recorded `response.json`.
- **Demo mode** (`ui/agentverse/js/mock-backend.js`): when Agent A is unreachable (or with `?demo=1`), the runner and viewer replay the recorded fixtures through a fake `fetch`, with speed control, cancel support and a provenance banner.
- **Live topology diagram**: the AgentVerse diagram bolds the edge between the agents of each LLM call as it lands (ported from the MARBLE UI), so Full Mesh and Star fan-out show as bursts.
- **`scripts/demo/smoke_test.py`**: Playwright end-to-end test of demo mode (all 12 replays, cancel, speed, demo flag, viewer, 375 px layout).

### Fixed

- Cancelling a run showed "Error" and marked every stage as failed; it now shows "Cancelled".
- Full-mesh discussion rounds now appear live (`full_mesh_round` events were ignored) and render their messages instead of "No reviews".
- The AgentVerse pages no longer scroll sideways on narrow (375 px) screens.

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
