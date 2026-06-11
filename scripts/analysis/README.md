# Analysis scripts

Post-experiment analysis tools that produce the figures used in the paper.

---

## `plot_paper_figures.py`

Reads an experiment output directory and generates the three paper figures.

```bash
python scripts/analysis/plot_paper_figures.py <experiment_dir> [--out <output_dir>]
```

**Output** (written to `<experiment_dir>/figures/` by default):

| File | Paper figure | Description |
|------|-------------|-------------|
| `iat_topologies_3x2_same_scale.pdf` | Fig 3 | IAT histogram per topology — linear (top) and log (bottom) rows |
| `iat_topologies_lognormal_fit_2row.pdf` | Fig 4 | Log-normal fit on reasoning-phase IATs (IAT > 50 ms) |
| `cross_layer_spearman_heatmap.pdf` | Fig 2 | Spearman rank correlations across per-run application-layer metrics |

Each figure is saved as both `.pdf` and `.png`.

**Dependencies:**

```bash
pip install matplotlib numpy scipy
# or: pip install -e ".[analysis]"
```

---

## Running via the queue

Pass `"generate_plots": true` when adding a job — the daemon runs this script automatically after the experiment completes:

```python
queue_add_job("agentverse", {
    "topology": "all",
    "runs": 500,
    "agents": 4,
    "generate_plots": True,
})
```

Figures land in `<output_path>/figures/` alongside the experiment JSONL.

---

## Generating the data

The paper figures are produced from experiment output created by `scripts/experiment/run_agentverse.sh`. To reproduce:

```bash
# 1. Start the stack
scripts/deploy/deploy.sh

# 2. Collect data (all three topologies, 500 runs each — matches the paper)
scripts/experiment/run_agentverse.sh

# 3. Plot figures
python scripts/analysis/plot_paper_figures.py data/agentverse/<experiment_dir>
```

A quick smoke-test (10 runs, full_mesh only) takes ~7 minutes and produces valid figures:

```bash
scripts/experiment/run_agentverse.sh --topology full_mesh --runs 10
python scripts/analysis/plot_paper_figures.py data/agentverse/<experiment_dir>
```

---

## Notes

- **Reasoning-phase IATs**: Figs 3 and 4 filter out the fan-out mode (IAT ≤ 50 ms) before fitting. The 50 ms threshold is the visible trough between the two modes in the bimodal distributions.
- **Upper-tail fence**: a 3 × IQR fence is applied to remove rare extreme gaps consistent with model-serving timeouts (not part of the arrival process).
- **Cross-layer heatmap**: Fig 2 is computed from application-layer metrics only (LLM call counts, token counts, latency). The TCP byte-rate columns present in the paper require the passive TCP collector to have been running during the experiment — see [infra/README.md](../../infra/README.md).
