"""Traffic page analyses: writes ``traffic.json``.

Usage::

    python -m scripts.demo.analysis_traffic --source data/att-paper [--out ui/data/private]

Run on its own it calls ``export_results.build_all`` and writes only ``<out>/traffic.json``;
``export_results.py`` also calls ``build(ctx)`` through its per-page hook. Stdlib only and
deterministic (fixed seeds). The output is aggregates only: counts, quantiles, rates.

Definitions (from the paper's scripts in ``scripts/experiment/agentverse/``)
-------------------------------------------------------------------------
* **Discussion IATs**: as Table 2 (``_compute_table2.collect_iats``), i.e. ``Run.disc_iats``.
* **Burst**: a maximal run of consecutive discussion calls whose gaps are all below 50 ms, the
  paper's burst threshold (Table 2 "burst fraction"). A call with no such neighbour is a burst
  of size 1. **ON period**: first to last call start of a burst of 2+ calls. **OFF period**:
  the gap from the last call of a burst to the first call of the next (an IAT >= 50 ms).
* **Gaps with bursts removed**: each burst merged into one arrival at its first call; the gaps
  between consecutive merged arrivals. ``analyse_burst_removed_agents._burst_remove`` instead
  drops every IAT below a threshold (0.1 s by default); at the same threshold that leaves the OFF
  periods, which differ from the merged gaps only by the preceding ON period (a few ms). The
  0.1 s variant is reported for comparison (``dropped_0p1``).
* **Subsampling robustness** (paper Table ``tab:ks-subsample``, NAIC slide "Robustness check"):
  the KS rejection rate per family (exponential, Weibull, log-normal) at n = 50 / 100 / 200 gaps
  per sample, for all three topologies. The protocol of the paper's ``ks_subsample_analysis.py``
  is 500 random samples per cell, every family refitted to each sample, one-sample KS test at
  alpha = 0.05. The exported rates are **the paper's published values** (``PAPER_KS_SUBSAMPLE``,
  every cell ``"source": "paper"``); they are not recomputed from the published runs, and the
  page says so. ``pool_n`` and ``n_runs`` still describe the published runs.
* **Playground inputs**: burst sizes (above) and the paper's log-normal gap fit
  (``summary.iat.fits``) drive the browser simulation. Call durations are the discussion calls'
  ``duration_seconds`` with the same upper cut as the fit sample (<= its largest value, which
  removes timeouts), as quantiles. ``measured_mean_inflight``: time-weighted mean of discussion
  calls in flight per run, averaged over runs; ``model_mean_inflight``: the model's mean by
  Little's law (calls per second x mean duration) for one workflow.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.demo import export_results as er
from scripts.demo.generate_fixtures import (
    BURST_THRESHOLD_S,
    TOPOLOGIES,
    LeakError,
    assert_no_leaks,
    percentile,
)

GENERATOR = "scripts/demo/analysis_traffic.py"
SCHEMA_VERSION = 1

SUBSAMPLE_NS = (50, 100, 200)
N_SUBSAMPLES = 500
ALPHA = 0.05
FAMILIES = ("exponential", "weibull", "lognormal")
# Paper tab:ks-subsample (body.tex) = the NAIC slide "Robustness check: subsampling stability":
# rejection rate in % per n -> family -> (Sequential, Star, Full Mesh).
# The page shows these published values for every topology (provenance "source": "paper").
PAPER_KS_SUBSAMPLE = {
    50: {"exponential": (100, 100, 51), "weibull": (7, 10, 7), "lognormal": (1, 2, 1)},
    100: {"exponential": (100, 100, 80), "weibull": (40, 55, 32), "lognormal": (1, 11, 5)},
    200: {"exponential": (100, 100, 98), "weibull": (93, 98, 76), "lognormal": (1, 50, 33)},
}
DROP_THRESHOLD_S = 0.1  # analyse_burst_removed_agents.py --burst-threshold default
QUANTILES = (5, 25, 50, 75, 95)
N_DURATION_QUANTILES = 100  # 101 points: 0th ... 100th percentile
_DISC_STAGES = (1, 2)  # export_results.STAGE_CODES: discussion, discussion_synthesis


# ---------------------------------------------------------------------------
# Bursts
# ---------------------------------------------------------------------------


def burst_groups(iats: list[float], threshold: float = BURST_THRESHOLD_S) -> list[list[int]]:
    """Call indices (0 .. len(iats)) grouped into bursts: a gap below ``threshold`` joins calls."""
    if not iats:
        return []
    groups = [[0]]
    for i, gap in enumerate(iats):
        if gap < threshold:
            groups[-1].append(i + 1)
        else:
            groups.append([i + 1])
    return groups


def run_bursts(iats: list[float], threshold: float = BURST_THRESHOLD_S) -> dict:
    """Burst sizes, ON spans, OFF gaps and merged gaps of one run's discussion IATs."""
    starts = [0.0]
    for gap in iats:
        starts.append(starts[-1] + gap)
    groups = burst_groups(iats, threshold)
    first = [starts[g[0]] for g in groups]
    return {
        "sizes": [len(g) for g in groups],
        "on": [starts[g[-1]] - starts[g[0]] for g in groups if len(g) > 1],
        "off": [gap for gap in iats if gap >= threshold],
        "merged": [b - a for a, b in zip(first, first[1:])],
    }


def describe(values: list[float]) -> dict:
    """n, mean, CV (population std / mean) and the QUANTILES of a sample."""
    if not values:
        return {"n": 0}
    mean = er.fmean(values)
    out: dict[str, Any] = {"n": len(values), "mean_s": er.sig(mean)}
    out["cv"] = er.sig(statistics.pstdev(values) / mean) if mean > 0 else None
    for q in QUANTILES:
        out[f"p{q}_s"] = er.sig(percentile(values, q))
    return out


def build_bursts(runs: list[er.Run]) -> dict:
    out = {}
    for t in TOPOLOGIES:
        sizes: Counter[int] = Counter()
        on: list[float] = []
        off: list[float] = []
        n_runs = 0
        for r in runs:
            if r.topology != t or not r.disc_iats:
                continue
            n_runs += 1
            b = run_bursts(r.disc_iats)
            sizes.update(b["sizes"])
            on += b["on"]
            off += b["off"]
        n_bursts = sum(sizes.values())
        n_calls = sum(k * v for k, v in sizes.items())
        out[t] = {
            "n_runs": n_runs,
            "n_calls": n_calls,
            "n_bursts": n_bursts,
            "sizes": [[k, sizes[k]] for k in sorted(sizes)],
            "mean_size": er.sig(n_calls / n_bursts) if n_bursts else None,
            "calls_in_bursts": er.sig(
                sum(k * v for k, v in sizes.items() if k > 1) / n_calls if n_calls else 0
            ),
            "bursts_per_run": er.sig(sum(v for k, v in sizes.items() if k > 1) / n_runs),
            "on": describe(on),
            "off": describe(off),
        }
    return out


def build_gaps(runs: list[er.Run], edges: list[float]) -> dict:
    out = {}
    for t in TOPOLOGIES:
        raw: list[float] = []
        merged: list[float] = []
        for r in runs:
            if r.topology != t or not r.disc_iats:
                continue
            raw += r.disc_iats
            merged += run_bursts(r.disc_iats)["merged"]
        dropped = [x for x in raw if x >= DROP_THRESHOLD_S]
        hist = er.histogram(merged, edges)
        out[t] = {
            "raw": describe(raw),
            "merged": describe(merged),
            "dropped_0p1": describe(dropped),
            "counts": hist["counts"],
            "underflow": hist["underflow"],
            "overflow": hist["overflow"],
        }
    return out


# ---------------------------------------------------------------------------
# Subsampling robustness (ks_subsample_analysis.py)
# ---------------------------------------------------------------------------


def slow_mode_pool(iats: list[float], topology: str) -> list[float]:
    """ks_subsample_analysis.load_slow_iats: IATs > 0, 3x IQR fence (Sequential, Star), > 50 ms."""
    pos = [x for x in iats if x > 0]
    if topology in er.FENCED_TOPOLOGIES and pos:
        q1, q3 = percentile(pos, 25), percentile(pos, 75)
        fence = q3 + er.FENCE_IQR * (q3 - q1)
        pos = [x for x in pos if x <= fence]
    return [x for x in pos if x > BURST_THRESHOLD_S]


def paper_cells(topology: str, n: int) -> dict[str, dict]:
    """The paper's rejection rates (tab:ks-subsample) for one topology and n, as fraction."""
    idx = TOPOLOGIES.index(topology)
    return {
        f: {"reject_rate": PAPER_KS_SUBSAMPLE[n][f][idx] / 100, "source": "paper"}
        for f in FAMILIES
    }


def build_robustness(
    runs: list[er.Run],
    ns: tuple[int, ...] = SUBSAMPLE_NS,
    draws: int = N_SUBSAMPLES,
) -> dict:
    """The paper's published KS rejection rates (all topologies); ``draws`` is the paper's 500."""
    per_topology = {}
    for t in TOPOLOGIES:
        pool = slow_mode_pool([x for r in runs if r.topology == t for x in r.disc_iats], t)
        per_topology[t] = {
            "pool_n": len(pool),
            "n_runs": sum(1 for r in runs if r.topology == t),
            "cells": {str(n): paper_cells(t, n) for n in ns},
        }
    return {
        "ns": list(ns),
        "draws": draws,
        "alpha": ALPHA,
        "families": list(FAMILIES),
        "ks_critical": {str(n): er.sig(1.36 / math.sqrt(n), 4) for n in ns},
        "per_topology": per_topology,
        "source_note": (
            "Paper tab:ks-subsample: rejection rates as published (500 random samples per cell, "
            "KS test at alpha = 0.05). Not recomputed from the published runs."
        ),
    }


# ---------------------------------------------------------------------------
# Playground inputs
# ---------------------------------------------------------------------------


def disc_calls(run: er.Run) -> list[list]:
    return [c for c in run.calls if c[2] in _DISC_STAGES]


def build_playground(runs: list[er.Run], summary: dict, bursts: dict) -> dict:
    out = {}
    fits = summary["iat"]["fits"]
    for t in TOPOLOGIES:
        fit = fits[t]
        cut = fit["range_s"][1]
        durations: list[float] = []
        means: list[float] = []
        for r in runs:
            if r.topology != t:
                continue
            calls = disc_calls(r)
            durations += [c[1] / 1000 for c in calls if c[1] is not None]
            spans = [(c[0] / 1000, (c[0] + c[1]) / 1000) for c in calls if c[1]]
            mean, _ = er._time_weighted_concurrency(spans)
            if math.isfinite(mean):
                means.append(mean)
        kept = sorted(d for d in durations if d <= cut)
        quant = [
            er.sig(percentile(kept, 100 * i / N_DURATION_QUANTILES), 4)
            for i in range(N_DURATION_QUANTILES + 1)
        ]
        ln = fit["lognormal"]
        mean_gap = math.exp(ln["mu"] + ln["sigma"] ** 2 / 2)
        rate = bursts[t]["n_calls"] / bursts[t]["n_bursts"] / mean_gap
        out[t] = {
            "duration_quantiles_s": quant,
            "duration_cut_s": cut,
            "n_durations": len(durations),
            "n_kept": len(kept),
            "mean_duration_s": er.sig(er.fmean(kept)),
            "mean_gap_s": er.sig(mean_gap),
            "calls_per_s": er.sig(rate),
            "model_mean_inflight": er.sig(rate * er.fmean(kept), 4),
            "measured_mean_inflight": er.sig(er.fmean(means), 4),
        }
    return out


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build(ctx: dict) -> dict:
    """The traffic.json payload (export_results.run_analyses hook)."""
    runs: list[er.Run] = ctx["runs"]
    summary: dict = ctx["summary"]
    if not runs:  # nothing scanned (other modules' hook tests call with no runs)
        return {"schema_version": SCHEMA_VERSION, "generator": GENERATOR, "n_runs": {}}
    edges = summary["iat"]["bins_s"]
    bursts = build_bursts(runs)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "burst_threshold_s": BURST_THRESHOLD_S,
        "drop_threshold_s": DROP_THRESHOLD_S,
        "n_runs": {t: sum(1 for r in runs if r.topology == t) for t in TOPOLOGIES},
        "bursts": bursts,
        "gaps": {"bins_s": edges, "per_topology": build_gaps(runs, edges)},
        "robustness": build_robustness(runs),
        "playground": build_playground(runs, summary, bursts),
    }


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, required=True, help="paper-branch checkout")
    ap.add_argument("--out", type=Path, default=er.DEFAULT_OUT, help="output directory")
    args = ap.parse_args(argv)
    try:
        summary, _, report = er.build_all(args.source)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    payload = build({"runs": report["runs"], "summary": summary, "source": args.source})
    text = dumps(payload)
    try:
        assert_no_leaks(text, "traffic.json")
    except LeakError as exc:
        print(f"error: {exc}")
        return 3
    print_report(payload)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "traffic.json"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    return 0


def print_report(payload: dict) -> None:
    rows = []
    for t in TOPOLOGIES:
        b, g = payload["bursts"][t], payload["gaps"]["per_topology"][t]
        rows.append(
            [
                t,
                b["n_bursts"],
                b["mean_size"],
                b["calls_in_bursts"],
                g["raw"]["cv"],
                g["merged"]["cv"],
                g["merged"]["p50_s"],
            ]
        )
    er.print_table(["topology", "bursts", "size", "in bursts", "CV raw", "CV merged", "p50"], rows)
    rob = payload["robustness"]
    rows = []
    for n in rob["ns"]:
        for f in rob["families"]:
            cells = []
            for t in TOPOLOGIES:
                c = rob["per_topology"][t]["cells"].get(str(n))
                cells.append(f"{c[f]['reject_rate'] * 100:.0f}%" if c else "-")
            rows.append([n, f, *cells])
    print("\nKS rejection rate (paper, tab:ks-subsample)")
    er.print_table(["n", "family", *TOPOLOGIES], rows)
    for t, p in payload["playground"].items():
        print(
            f"{t}: model mean in flight {p['model_mean_inflight']}, "
            f"measured {p['measured_mean_inflight']}"
        )


if __name__ == "__main__":
    sys.exit(main())
