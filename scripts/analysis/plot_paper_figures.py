#!/usr/bin/env python3
"""
Generate the paper figures from an agentraffic experiment output directory.

Usage:
    python scripts/analysis/plot_paper_figures.py <experiment_dir> [--out <output_dir>]

Produces (in <experiment_dir>/figures/ by default):
    iat_topologies_3x2_same_scale.pdf   — Fig 3: IAT histogram, linear + log rows
    iat_topologies_lognormal_fit_2row.pdf — Fig 4: log-normal fit on reasoning-phase IATs
    cross_layer_spearman_heatmap.pdf    — Fig 2: Spearman correlation across per-run metrics

Dependencies:  pip install matplotlib numpy scipy
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Style — matches the paper
# ---------------------------------------------------------------------------

COLORS = {"Sequential": "#1f77b4", "Star": "#ff7f0e", "Full Mesh": "#9467bd"}
FIT_COLOR = "#c94949"
TOPOLOGIES = ["Sequential", "Star", "Full Mesh"]
TOPOLOGY_KEY = {"horizontal": "Sequential", "vertical": "Star", "full_mesh": "Full Mesh"}

# Label prefixes that belong to the discussion stage for each topology
DISCUSSION_PREFIXES = {
    "Sequential": ("horizontal_discussion", "synthesize_discussion"),
    "Star":       ("horizontal_discussion", "synthesize_discussion",
                   "vertical_solver", "vertical_reviewer"),
    "Full Mesh":  ("full_mesh_message", "synthesize_discussion"),
}

plt.rcParams.update({
    "font.family":        "serif",
    "font.size":          14,
    "axes.labelsize":     14,
    "axes.titlesize":     18,
    "xtick.labelsize":    13,
    "ytick.labelsize":    13,
    "legend.fontsize":    13,
    "figure.dpi":         180,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.02,
    "axes.grid":          True,
    "grid.alpha":         0.25,
    "grid.linewidth":     0.5,
    "axes.spines.top":    False,
    "axes.spines.right":  False,
})


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_records(experiment_dir: Path) -> list[dict]:
    """Parse all *.jsonl files in experiment_dir (skipping experiment_log.jsonl)."""
    records = []
    decoder = json.JSONDecoder()
    for jsonl in sorted(experiment_dir.glob("*.jsonl")):
        if jsonl.name == "experiment_log.jsonl":
            continue
        text = jsonl.read_text(encoding="utf-8")
        i = 0
        while i < len(text):
            chunk = text[i:].lstrip()
            if not chunk:
                break
            i += len(text[i:]) - len(chunk)
            try:
                obj, end = decoder.raw_decode(chunk)
                records.append(obj)
                i += end
            except json.JSONDecodeError:
                i += 1
    return records


def collect_iats(records: list[dict], topology: str) -> np.ndarray:
    """
    Collect inter-arrival times (seconds) for one topology across all runs.
    Uses only the discussion-stage LLM calls (filtered by label prefix).
    """
    prefixes = DISCUSSION_PREFIXES[topology]
    iats: list[float] = []

    for rec in records:
        if TOPOLOGY_KEY.get(rec.get("topology", "")) != topology:
            continue
        timestamps = [
            datetime.fromisoformat(req["start_time_utc"]).timestamp()
            for req in rec.get("llm_requests", [])
            if req.get("start_time_utc")
            and any(req.get("label", "").startswith(p) for p in prefixes)
        ]
        if len(timestamps) >= 2:
            iats.extend(np.diff(sorted(timestamps)).tolist())

    return np.array(iats, dtype=float)


def remove_upper_tail(arr: np.ndarray, k: float = 3.0) -> np.ndarray:
    """Remove outliers above Q3 + k * IQR (upper-tail fence only)."""
    q1, q3 = np.percentile(arr, [25, 75])
    return arr[arr <= q3 + k * (q3 - q1)]


# ---------------------------------------------------------------------------
# Panel helpers (shared by both figures)
# ---------------------------------------------------------------------------

def _linear_panel(ax: plt.Axes, arr: np.ndarray, topology: str, x_max: float) -> None:
    """Histogram + KDE on a linear x-axis."""
    color = COLORS[topology]
    visible = arr[(arr >= 0) & (arr <= x_max)]
    ax.hist(visible, bins=44, density=True, color=color, alpha=0.42)
    if len(visible) > 5:
        xs = np.linspace(0, x_max, 500)
        ax.plot(xs, stats.gaussian_kde(visible)(xs), color=color, linewidth=2.0)
    ax.set_xlim(0, x_max)
    ax.set_title(topology)


def _log_panel(ax: plt.Axes, arr: np.ndarray, topology: str,
               x_lo: float, x_hi: float) -> None:
    """Histogram + KDE on a log10 x-axis."""
    color = COLORS[topology]
    pos = arr[arr > 0]
    log_lo, log_hi = np.log10(x_lo), np.log10(x_hi)
    log_pos = np.log10(pos)
    clipped = log_pos[(log_pos >= log_lo) & (log_pos <= log_hi)]
    xs = np.linspace(log_lo, log_hi, 500)
    ax.hist(clipped, bins=np.linspace(log_lo, log_hi, 44), density=True,
            color=color, alpha=0.42)
    if len(pos) > 5:
        ax.plot(xs, stats.gaussian_kde(log_pos)(xs), color=color, linewidth=2.0)
    ticks = [p for p in range(int(np.floor(log_lo)), int(np.ceil(log_hi)) + 1)
             if log_lo <= p <= log_hi]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{10**p:g}" for p in ticks])
    ax.set_xlim(log_lo, log_hi)
    ax.set_title(topology)


def _lognormal_linear_panel(ax: plt.Axes, arr: np.ndarray, topology: str) -> None:
    """
    Reasoning-phase IATs (> 50 ms) on a linear x-axis:
    histogram + KDE (dashed, topology colour) + log-normal fit (solid red).
    """
    color = COLORS[topology]
    pos = arr[arr > 0.050]
    if len(pos) == 0:
        return
    x_max = float(np.percentile(pos, 99))
    visible = pos[pos <= x_max]
    ax.hist(visible, bins=44, density=True, color=color, alpha=0.36)
    xs = np.linspace(max(1e-4, float(pos.min())), x_max, 500)
    if len(visible) > 5:
        ax.plot(xs, stats.gaussian_kde(visible)(xs),
                color=color, linewidth=1.8, linestyle="--")
    mu = float(np.log(pos).mean())
    sigma = float(np.log(pos).std())
    ax.plot(xs, stats.lognorm.pdf(xs, s=sigma, scale=np.exp(mu)),
            color=FIT_COLOR, linewidth=2.1)
    ax.text(0.96, 0.92, f"$\\mu$={mu:.2f}\n$\\sigma$={sigma:.2f}",
            transform=ax.transAxes, va="top", ha="right", fontsize=13,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#cccccc", alpha=0.9))
    ax.text(0.04, 0.92, "IAT > 50 ms",
            transform=ax.transAxes, va="top", ha="left", fontsize=13,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#cccccc", alpha=0.9))
    ax.set_xlim(0, x_max)
    ax.set_title(topology)


def _lognormal_log_panel(ax: plt.Axes, arr: np.ndarray, topology: str) -> None:
    """
    Reasoning-phase IATs (> 50 ms) on a log10 x-axis:
    histogram + KDE (dashed) + log-normal fit (solid red).
    """
    color = COLORS[topology]
    pos = arr[arr > 0.050]
    if len(pos) == 0:
        return
    log_pos = np.log10(pos)
    x_lo = float(np.percentile(log_pos, 1))
    x_hi = float(np.percentile(log_pos, 99))
    clipped = log_pos[(log_pos >= x_lo) & (log_pos <= x_hi)]
    xs = np.linspace(x_lo, x_hi, 500)
    ax.hist(clipped, bins=np.linspace(x_lo, x_hi, 44), density=True,
            color=color, alpha=0.36)
    if len(log_pos) > 5:
        ax.plot(xs, stats.gaussian_kde(log_pos)(xs),
                color=color, linewidth=1.8, linestyle="--")
    # In log10 space, LogNormal(mu, sigma) → Normal(mu/ln10, sigma/ln10)
    mu = float(np.log(pos).mean())
    sigma = float(np.log(pos).std())
    ax.plot(xs, stats.norm.pdf(xs, loc=mu / np.log(10), scale=sigma / np.log(10)),
            color=FIT_COLOR, linewidth=2.1)
    ticks = [p for p in range(int(np.floor(x_lo)), int(np.ceil(x_hi)) + 1)
             if x_lo <= p <= x_hi]
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{10**p:g}" for p in ticks])
    ax.set_xlim(x_lo, x_hi)
    ax.text(0.96, 0.92, f"$\\mu$={mu:.2f}\n$\\sigma$={sigma:.2f}",
            transform=ax.transAxes, va="top", ha="right", fontsize=13,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#cccccc", alpha=0.9))
    ax.text(0.04, 0.92, "IAT > 50 ms",
            transform=ax.transAxes, va="top", ha="left", fontsize=13,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="#cccccc", alpha=0.9))
    ax.set_title(topology)


# ---------------------------------------------------------------------------
# Figure 3 — IAT histograms, 3 topologies × 2 rows (linear + log)
# ---------------------------------------------------------------------------

def plot_iat_3x2(datasets: dict[str, np.ndarray], out_dir: Path) -> None:
    """Fig 3: three columns (topologies), two rows (linear scale, log scale)."""
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 5.8), sharey="row")

    all_arr = np.concatenate(list(datasets.values()))
    x_max = float(np.percentile(all_arr, 99))
    all_pos = all_arr[all_arr > 0]
    x_lo = max(float(np.percentile(all_pos, 0.3)), 1e-4)
    x_hi = float(np.percentile(all_pos, 99.7))

    for col, topo in enumerate(TOPOLOGIES):
        _linear_panel(axes[0, col], datasets[topo], topo, x_max)
        _log_panel(axes[1, col], datasets[topo], topo, x_lo, x_hi)
        axes[1, col].set_title("")

    for ax in axes.flat:
        ax.set_xlabel("")
        ax.set_ylabel("")
    fig.supxlabel("Inter-arrival time (s)", fontsize=17, y=0.012)
    fig.supylabel("Density", fontsize=17, x=0.012)
    fig.tight_layout(h_pad=0.8, w_pad=1.1, rect=(0.025, 0.022, 1, 1))

    _save(fig, out_dir, "iat_topologies_3x2_same_scale")


# ---------------------------------------------------------------------------
# Figure 4 — log-normal fit on reasoning-phase IATs, 2 rows
# ---------------------------------------------------------------------------

def plot_lognormal_fit_2row(datasets: dict[str, np.ndarray], out_dir: Path) -> None:
    """Fig 4: IAT > 50 ms, linear (top row) and log10 (bottom row), with log-normal fit."""
    fig, axes = plt.subplots(2, 3, figsize=(10.8, 5.8), sharey=False)

    for col, topo in enumerate(TOPOLOGIES):
        _lognormal_linear_panel(axes[0, col], datasets[topo], topo)
        _lognormal_log_panel(axes[1, col], datasets[topo], topo)
        axes[0, col].set_title(topo)
        axes[1, col].set_title("")

    for ax in axes.flat:
        ax.set_xlabel("")
        ax.set_ylabel("")
    fig.supxlabel("Inter-arrival time (s)", fontsize=17, y=0.012)
    fig.supylabel("Density", fontsize=17, x=0.012)
    fig.tight_layout(h_pad=0.8, w_pad=1.1, rect=(0.025, 0.022, 1, 1))

    _save(fig, out_dir, "iat_topologies_lognormal_fit_2row")


# ---------------------------------------------------------------------------
# Figure 2 — cross-layer Spearman heatmap (application-layer metrics only)
# ---------------------------------------------------------------------------

def plot_spearman_heatmap(records: list[dict], out_dir: Path) -> None:
    """
    Fig 2: Spearman rank correlations across per-run application-layer metrics,
    pooled across all topologies.
    """
    rows = []
    for rec in records:
        topo = TOPOLOGY_KEY.get(rec.get("topology", ""))
        if not topo:
            continue
        reqs = [r for r in rec.get("llm_requests", []) if r.get("start_time_utc")]
        if not reqs:
            continue
        starts = sorted(datetime.fromisoformat(r["start_time_utc"]).timestamp()
                        for r in reqs)
        iats_run = np.diff(starts) if len(starts) > 1 else np.array([])
        total_tokens = sum(
            (r.get("llm_meta") or {}).get("total_tokens", 0) for r in reqs
        )
        dur = float(rec.get("duration_seconds") or rec.get("elapsed_ms", 0) / 1000)
        rows.append({
            "n_calls":      len(reqs),
            "duration_s":   dur,
            "total_tokens": total_tokens,
            "prompt_tps":   total_tokens / dur if dur > 0 else 0,
            "mean_iat_s":   float(np.mean(iats_run)) if len(iats_run) else 0,
            "burst_frac":   float(np.mean(iats_run < 0.050)) if len(iats_run) else 0,
            "mean_latency_s": float(np.mean([
                (r.get("llm_meta") or {}).get("latency_ms", 0) for r in reqs
            ])) / 1000,
        })

    if len(rows) < 5:
        print("  [skip] not enough runs for Spearman heatmap")
        return

    metric_labels = {
        "n_calls":        "LLM calls / run",
        "duration_s":     "Run duration (s)",
        "total_tokens":   "Total tokens",
        "prompt_tps":     "Token throughput",
        "mean_iat_s":     "Mean IAT (s)",
        "burst_frac":     "Burst fraction",
        "mean_latency_s": "Mean call latency (s)",
    }
    keys = list(metric_labels.keys())
    mat = np.array([[row[k] for k in keys] for row in rows])
    n = len(keys)
    corr = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            corr[i, j], _ = stats.spearmanr(mat[:, i], mat[:, j])

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
    fig.colorbar(im, ax=ax, label="Spearman ρ")
    tick_labels = list(metric_labels.values())
    ax.set_xticks(range(n)); ax.set_xticklabels(tick_labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(n)); ax.set_yticklabels(tick_labels, fontsize=9)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{corr[i,j]:.2f}", ha="center", va="center",
                    fontsize=7, color="black" if abs(corr[i, j]) < 0.7 else "white")
    ax.set_title("Cross-layer Spearman correlations\n(pooled across topologies)")
    fig.tight_layout()

    _save(fig, out_dir, "cross_layer_spearman_heatmap")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save(fig: plt.Figure, out_dir: Path, name: str) -> None:
    for ext in ("pdf", "png"):
        path = out_dir / f"{name}.{ext}"
        fig.savefig(path)
        print(f"  [ok] {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment_dir", type=Path,
                        help="Experiment output directory (contains *.jsonl files)")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory for figures (default: <experiment_dir>/figures)")
    args = parser.parse_args()

    exp_dir = args.experiment_dir.resolve()
    out_dir = (args.out or exp_dir / "figures").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading records from {exp_dir} ...")
    records = load_records(exp_dir)
    if not records:
        raise SystemExit(f"No records found in {exp_dir}")

    datasets: dict[str, np.ndarray] = {}
    for topo in TOPOLOGIES:
        raw = collect_iats(records, topo)
        datasets[topo] = remove_upper_tail(raw)
        print(f"  {topo}: {len(raw)} IATs → {len(datasets[topo])} after fence  "
              f"(median={np.median(datasets[topo]):.3g}s, "
              f"p95={np.percentile(datasets[topo], 95):.3g}s)")

    print(f"\nWriting figures to {out_dir}")
    plot_iat_3x2(datasets, out_dir)
    plot_lognormal_fit_2row(datasets, out_dir)
    plot_spearman_heatmap(records, out_dir)
    print("Done.")


if __name__ == "__main__":
    main()
