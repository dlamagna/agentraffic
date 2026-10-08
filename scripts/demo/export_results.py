"""Export the paper's results (Table 2, IATs, fits, cross-layer metrics) for the static results page.

Usage::

    python -m scripts.demo.export_results --source data/att-paper [--out ui/data/private] \
        [--no-check]

``--source`` is a (sparse) checkout of ``paper-branch`` of ``dlamagna/agentraffic``.
Inputs, relative to it::

    data/agentverse/balanced_agents4_*/tasks/*/response.json.gz        1,481 runs (main data)
    data/agentverse/full_mesh_agents{3,5}_*/tasks/*/response.json.gz   scaling runs (optional)
    data/agentverse/combined_agents4_analysis/plots/paper/table2.md
    data/agentverse/combined_agents4_analysis/plots/structure_correlation/per_run_metrics.csv
    data/agentverse/combined_agents4_analysis/plots/structure_correlation/
        cross_layer_selected_correlations.csv
    figures/n_agents/full_mesh_runs.jsonl                              scaling run list (optional)

Outputs (stdlib only, deterministic: re-running on the same source gives byte-identical files)::

    <out>/summary.json   small, loaded on page open: source, Table 2, pooled IAT histograms and
                         fits, metric catalogue, Spearman matrices, per-group aggregates, scaling,
                         the 12 demo fixtures, per-topology quantile tables of every per-run metric
    <out>/runs.json      lazy-loaded drill-down: per run its metrics row, roles and every LLM call
    <out>/manifest.json  ``{"mode": "private", "generated": <UTC date>}``: tells the site
                         (ui/common/js/data.js) that this is the real data set

The default ``--out`` is ``ui/data/private/`` (gitignored; never committed or published). The
public aggregates are derived from it by ``scripts/demo/export_public.py``.

Nothing is written unless every cross-check passes (``--no-check`` writes anyway).

Definitions (all taken from the paper's scripts in ``scripts/experiment/agentverse/``)
------------------------------------------------------------------------------------
* **Topology** of a run: from its request labels (``label_topology``; ``full_mesh_message`` ->
  Full Mesh, ``vertical_solver``/``vertical_reviewer`` -> Star, ``horizontal_discussion`` ->
  Sequential), as in every paper script. It agrees with ``structure_used`` on all 1,481 runs.
* **Discussion IATs** (Table 2): ``discussion_iats`` from ``generate_fixtures``, i.e.
  ``collect_iats()`` in ``_compute_table2.py``. Per run, sort the ``start_time_utc`` of the
  requests whose label has one of the topology's discussion prefixes and take consecutive
  differences; pool over runs. Burst = IAT < 50 ms.
* **Fits** (paper Table 3, ``tab:gof``): the pipeline of ``make_session_proxy_figures.py``
  (``raw_iat_statistical_tests.py`` calls it "the original Table 3 pipeline"). Pooled discussion
  IATs > 0; a 3x IQR upper fence (Q3 + 3 IQR) for Sequential and Star only; keep IAT > 50 ms (the
  reasoning-phase mode); drop values above that sample's 99th percentile. Then maximum likelihood
  with location 0: log-normal (mu, sigma = mean / population std of ln x), exponential
  (lambda = 1 / mean) and Weibull (shape k from the MLE equation, scale). KS = one-sample
  Kolmogorov-Smirnov statistic against the fitted CDF; its p-value is the exact two-sided
  distribution as in ``scipy.stats.kstest`` (``kstwo.sf``: Simard & L'Ecuyer's method selection,
  re-implemented in ``ks_pvalue``). AIC = 2k - 2 log L. The p-values ignore that the parameters
  were estimated from the same data (the paper reports the statistic, not the p-value).
* **Per-run metrics**: the columns of ``per_run_metrics.csv`` (written by
  ``correlate_structure_metrics.py``). 20 of its 29 columns come from ``response.json``
  (``response_metrics`` re-implements ``extract_run``); the 9 ``tcp_*`` columns come from the
  run's Prometheus ``metrics.csv`` (not in the sparse checkout), windowed to the discussion stage.
* **Spearman rho**: Pearson correlation of average ranks over pairwise-complete rows, as
  ``pandas.DataFrame.corr(method="spearman")``.

Joining per_run_metrics.csv to responses
----------------------------------------
The CSV has no run id. ``correlate_structure_metrics.py`` appends one row per run, walking the
experiment directories in the order given and each one's ``tasks/`` in sorted order; the combined
CSV was built from the two ``balanced_agents4`` experiments in chronological order. So row *i*
should be the *i*-th response in that order. A row is accepted only if its ``structure`` and
``task_slug`` match and all 20 response-derived columns equal the values recomputed from the
response (relative tolerance 1e-9). Rows that fail are searched for among the unused rows by the
same full fingerprint; a unique hit is accepted, anything else stays unmatched (metrics ``null``).
The match counts are printed and stored in ``summary.source.join``.

Cross-checks (exit 1 unless ``--no-check``)
-------------------------------------------
* Every Table 2 cell is recomputed (``_compute_table2._build_results`` + its formatting) from the
  joined CSV rows and the pooled IATs, and must equal the published string; this covers the IAT
  counts 6513 / 7355 / 14493, medians, p95, burst fractions 0.0 / 53.3 / 38.2 %.
* Fits must reproduce the paper's ``tab:gof`` (n, parameters, AIC, KS at its printed precision)
  for Sequential and Full Mesh. Star is recomputed from the 481 published runs (3,198 fit IATs
  instead of the paper's 3,303 from a 500-run pool that was never released), so that comparison
  is informational only; the Star entry of ``summary.iat.fits`` is the paper's published row
  (``PAPER_GOF``) and carries ``"source": "paper"``. Run data, per-run metrics, histograms and run
  counts are never altered; the recomputed Star sample statistics stay under ``sample``.
* The all-runs Spearman rho must reproduce ``cross_layer_selected_correlations.csv`` (|diff| <
  1e-9), and the join must match every response.

Exit codes: 0 ok, 1 cross-check failed, 2 bad input, 3 sensitive data in the output.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import importlib
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from scripts.demo.generate_fixtures import (
    _TASK_DIR_RE,
    BURST_THRESHOLD_S,
    CATEGORY_TO_TASK,
    EXPERIMENT_GLOB,
    REPO_ROOT,
    SOURCE_BRANCH,
    SOURCE_REPO,
    TABLE2_RELPATH,
    TASKS,
    TOPOLOGIES,
    TOPOLOGY_LABELS,
    LeakError,
    assert_no_leaks,
    discussion_iats,
    find_response_files,
    label_topology,
    load_response,
    parse_ts,
    percentile,
    print_table,
)

DEFAULT_OUT = REPO_ROOT / "ui" / "data" / "private"
FIXTURE_INDEX = REPO_ROOT / "ui" / "data" / "private" / "fixtures" / "index.json"
SCHEMA_VERSION = 1
GENERATOR = "scripts/demo/export_results.py"

ANALYSIS_DIR = Path("data/agentverse/combined_agents4_analysis/plots/structure_correlation")
PER_RUN_CSV_RELPATH = ANALYSIS_DIR / "per_run_metrics.csv"
SELECTED_CSV_RELPATH = ANALYSIS_DIR / "cross_layer_selected_correlations.csv"
SCALING_JSONL_RELPATH = Path("figures/n_agents/full_mesh_runs.jsonl")

TASK_LABELS = {
    "math": "Math problem",
    "research": "Research task",
    "consulting": "Consulting",
    "coding": "Software development",
}

# Shared log-spaced IAT bins: 8 per decade, anchored so that the 50 ms burst threshold is an edge.
BIN_ANCHOR_S = BURST_THRESHOLD_S
BINS_PER_DECADE = 8
LINEAR_BIN_S = 0.25  # linear-scale IAT histogram: 0.25 s bins over [0, 30) s
LINEAR_MAX_S = 30.0
LINEAR_EDGES = [round(i * LINEAR_BIN_S, 2) for i in range(int(LINEAR_MAX_S / LINEAR_BIN_S) + 1)]
BIN_J_RANGE = (-24, 32)  # edges 0.05 * 10**(j/8): 50 us ... 500 s (data: 0.1 ms ... 211 s)

# Fit scope (make_session_proxy_figures.py): fence for these topologies only.
FENCED_TOPOLOGIES = ("horizontal", "vertical")
FENCE_IQR = 3.0
FIT_CLIP_PERCENTILE = 99.0

# correlate_structure_metrics.DISCUSSION_LABEL_PREFIXES (one list for every topology).
CORR_DISC_PREFIXES = (
    "horizontal_discussion",
    "synthesize_discussion",
    "vertical_solver",
    "vertical_reviewer",
    "full_mesh_message",
)

# The paper's tab:gof (body.tex; also PAPER_GOF in raw_iat_statistical_tests.py).
PAPER_GOF = {
    "horizontal": {
        "n": 6168,
        "exponential": {"mean_s": 4.77, "aic": 31604, "ks": 0.396},
        "weibull": {"k": 3.09, "scale_s": 5.32, "aic": 23165, "ks": 0.091},
        "lognormal": {"sigma": 0.31, "median_s": 4.54, "aic": 21782, "ks": 0.027},
    },
    "vertical": {
        "n": 3303,
        "exponential": {"mean_s": 10.55, "aic": 22173, "ks": 0.359},
        "weibull": {"k": 2.38, "scale_s": 11.92, "aic": 19131, "ks": 0.104},
        "lognormal": {"sigma": 0.40, "median_s": 9.70, "aic": 18377, "ks": 0.077},
    },
    "full_mesh": {
        "n": 8870,
        "exponential": {"mean_s": 1.28, "aic": 22078, "ks": 0.116},
        "weibull": {"k": 0.88, "scale_s": 1.18, "aic": 21760, "ks": 0.068},
        "lognormal": {"sigma": 1.16, "median_s": 0.67, "aic": 20590, "ks": 0.089},
    },
}
# Topologies whose fit entry in summary.iat.fits is the paper's published row (provenance
# "source": "paper"): Star, whose 500-run pool was never released (only 481 runs are).
PAPER_FIT_TOPOLOGIES = ("vertical",)
# Informational only (console report): the recomputed fit of those topologies differs from the paper.
KNOWN_FIT_DEVIATIONS = {
    "vertical": "recomputed from the 481 published Star runs; the paper used a 500-run pool"
}


def paper_fit(topology: str, recomputed: dict) -> dict:
    """The paper's tab:gof row as a fit entry (same shape as ``fit_all``), source = paper.

    Parameters are derived from the printed ones (mu = ln median, lambda = 1 / mean); KS and AIC
    as printed; the p-value is the exact KS p-value of the printed statistic at the paper's n.
    The recomputed sample statistics (published runs only) are kept under ``sample``.
    """
    g = PAPER_GOF[topology]
    n = g["n"]
    ln, ex, wb = g["lognormal"], g["exponential"], g["weibull"]

    def p(ks: float) -> float:
        return sig(ks_pvalue(ks, n), 6)

    entry = {
        "source": "paper",
        "n": n,
        "fraction_of_iats": None,
        "range_s": recomputed["range_s"],
        "fence_s": recomputed["fence_s"],
        "clip_s": recomputed["clip_s"],
        "lognormal": {
            "mu": sig(math.log(ln["median_s"]), 8),
            "sigma": ln["sigma"],
            "median_s": ln["median_s"],
            "ks": ln["ks"],
            "p_value": p(ln["ks"]),
            "aic": ln["aic"],
        },
        "exponential": {
            "lambda": sig(1.0 / ex["mean_s"], 8),
            "mean_s": ex["mean_s"],
            "ks": ex["ks"],
            "p_value": p(ex["ks"]),
            "aic": ex["aic"],
        },
        "weibull": {
            "shape": wb["k"],
            "scale_s": wb["scale_s"],
            "ks": wb["ks"],
            "p_value": p(wb["ks"]),
            "aic": wb["aic"],
        },
    }
    fams = ("lognormal", "exponential", "weibull")
    entry["best_aic"] = min(fams, key=lambda k: entry[k]["aic"])
    entry["best_ks"] = min(fams, key=lambda k: entry[k]["ks"])
    entry["sample"] = {
        "source": "published_runs",
        "n": recomputed["n"],
        "fraction_of_iats": recomputed["fraction_of_iats"],
        "n_positive": recomputed["n_positive"],
        "n_after_fence": recomputed["n_after_fence"],
        "n_reasoning": recomputed["n_reasoning"],
    }
    return entry

# make_full_mesh_scaling_figures.LOGNORMAL_FIT_PARAMS (hard-coded mu, sigma in the figure).
PAPER_SCALING_LOGNORMAL = {3: (0.98, 0.59), 4: (-0.36, 1.22), 5: (-0.72, 1.11)}

# --- Metric catalogue -------------------------------------------------------------------------
# (key, label, paper label, unit, layer, description). Display order = this order, grouped by
# layer. Meanings from correlate_structure_metrics.extract_run / METRIC_DEFS; "discussion calls"
# are the requests labelled horizontal_discussion / vertical_solver / vertical_reviewer /
# full_mesh_message / synthesize_discussion, all iterations of the run pooled.
# fmt: off
_PROM = (
    "measured passively on the network, samples inside the "
    "discussion window [first discussion-call start, last discussion-call end]"
)
METRICS: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("disc_n_requests", "Discussion calls", "Discussion Requests (count)", "calls",
     "application", "Number of discussion calls in the run."),
    ("disc_duration_s", "Discussion duration", "Discussion Duration (s)", "s", "application",
     "Last minus first discussion-call start time."),
    ("disc_total_tokens", "Discussion tokens", "Discussion Tokens (total)", "tokens",
     "application", "Prompt + completion tokens of all discussion calls (llm_meta)."),
    ("disc_mean_latency_s", "Mean call latency", "Discussion LLM Latency Mean (s)", "s",
     "application", "Mean end-to-end duration of a discussion call (duration_seconds, timed by "
     "the calling agent)."),
    ("disc_mean_iat_s", "Mean discussion IAT", "Discussion IAT Mean (s)", "s", "application",
     "Mean gap between consecutive discussion-call starts = duration / (calls - 1)."),
    ("llm_latency_p50_mean_s", "Call latency p50", "LLM Latency p50 (s)", "s", "llm",
     "Median discussion-call duration within the run."),
    ("llm_latency_p95_mean_s", "Call latency p95", "LLM Latency p95 (s)", "s", "llm",
     "95th percentile of discussion-call durations within the run."),
    ("llm_ttft_p50_mean_s", "TTFT p50", "TTFT p50 (s)", "s", "llm",
     "Median time to first token of the run's discussion calls: llm_meta.queue_wait_s, timed by "
     "the vLLM server from submission to the first output (queueing + prefill). Same values as "
     "llm_queue_wait_p50_mean_s."),
    ("llm_ttft_p95_mean_s", "TTFT p95", "TTFT p95 (s)", "s", "llm",
     "95th percentile of llm_meta.queue_wait_s (time to first token) of the run's discussion "
     "calls. Same values as llm_queue_wait_p95_mean_s."),
    ("llm_inflight_mean", "Mean in-flight calls", "In-flight LLM Req (mean)", "calls", "llm",
     "Time-weighted mean number of concurrent discussion calls over the discussion window "
     "([start, start + duration] intervals)."),
    ("llm_inflight_peak", "Peak in-flight calls", "In-flight LLM Req (peak)", "calls", "llm",
     "Maximum number of concurrent discussion calls."),
    ("llm_queue_wait_p50_mean_s", "Queue wait p50", "Queue Wait p50 (s)", "s", "llm",
     "Median llm_meta.queue_wait_s of the run's discussion calls (duplicate of TTFT p50)."),
    ("llm_queue_wait_p95_mean_s", "Queue wait p95", "Queue Wait p95 (s)", "s", "llm",
     "95th percentile of llm_meta.queue_wait_s (duplicate of TTFT p95)."),
    ("prompt_tokens_per_s_mean", "Prompt tokens/s", "Prompt Tokens/s", "tok/s", "llm",
     "Prompt tokens of all discussion calls / discussion duration."),
    ("completion_tokens_per_s_mean", "Completion tokens/s", "Completion Tokens/s", "tok/s", "llm",
     "Completion tokens of all discussion calls / discussion duration."),
    ("iat_mean_s", "Mean IAT", "IAT Mean (s)", "s", "traffic",
     "Mean discussion-call IAT (identical to disc_mean_iat_s)."),
    ("burstiness_mean", "Burstiness (max/mean IAT)", "Burstiness (mean)", "ratio", "traffic",
     "Largest discussion IAT of the run divided by its mean IAT (runs with >= 3 calls)."),
    ("burstiness_max", "Max IAT", "Burstiness (max)", "s", "traffic",
     "Largest discussion IAT of the run, in seconds (named burstiness_max in the paper's code)."),
    ("iat_jitter_p50_mean_s", "IAT p50", "IAT Jitter p50 (s)", "s", "traffic",
     "Median discussion IAT within the run (Table 2 'IAT jitter p50' is its mean over runs)."),
    ("iat_jitter_p95_mean_s", "IAT p95", "IAT Jitter p95 (s)", "s", "traffic",
     "95th percentile of the run's discussion IATs."),
    ("tcp_rtt_p50_mean_s", "TCP RTT p50", "TCP RTT p50 (s)", "s", "network",
     f"RTT of the TCP handshake from Agent A to the model server, histogram p50; {_PROM}. "
     "Constant (0.25 ms) in every run, so it carries no information."),
    ("tcp_rtt_p95_mean_s", "TCP RTT p95", "TCP RTT p95 (s)", "s", "network",
     f"RTT of the TCP handshake from Agent A to the model server, histogram p95; {_PROM}. Constant (0.475 ms) in every run."),
    ("tcp_flow_dur_p50_mean_s", "TCP flow duration p50", "TCP Flow Dur p50 (s)", "s", "network",
     f"TCP flow duration Agent A -> LLM, histogram p50; {_PROM}. Not discussion-only: flows "
     "span the whole task."),
    ("tcp_flow_dur_p95_mean_s", "TCP flow duration p95", "TCP Flow Dur p95 (s)", "s", "network",
     f"TCP flow duration Agent A -> LLM, histogram p95; {_PROM}. Not discussion-only."),
    ("tcp_bytes_llm_mean_Bps", "LLM TCP byte rate", "TCP Bytes/s from LLM (mean)", "B/s",
     "network", f"Bytes/s sent by the LLM backend, mean; {_PROM}."),
    ("tcp_bytes_llm_peak_Bps", "Peak LLM TCP byte rate", "TCP Bytes/s from LLM (peak)", "B/s",
     "network", f"Bytes/s sent by the LLM backend, max; {_PROM}."),
    ("tcp_bytes_a_to_llm_mean_Bps", "TCP bytes/s A->LLM", "TCP Bytes/s A→LLM", "B/s", "network",
     f"Bytes/s Agent A -> LLM backend, mean; {_PROM}."),
    ("tcp_bytes_b_to_llm_mean_Bps", "TCP bytes/s B->LLM", "TCP Bytes/s B→LLM (sum)", "B/s",
     "network", f"Bytes/s of all Agent B instances -> LLM backend (summed per sample), mean; "
     f"{_PROM}."),
    ("tcp_bytes_a_to_b_mean_Bps", "TCP bytes/s A->B", "TCP Bytes/s A→B (sum)", "B/s", "network",
     f"Bytes/s Agent A -> all Agent B instances (summed per sample), mean; {_PROM}."),
)
# fmt: on
METRIC_KEYS = tuple(m[0] for m in METRICS)
LAYERS = ("application", "llm", "traffic", "network")
DUPLICATE_OF = {
    "llm_queue_wait_p50_mean_s": "llm_ttft_p50_mean_s",
    "llm_queue_wait_p95_mean_s": "llm_ttft_p95_mean_s",
    "iat_mean_s": "disc_mean_iat_s",
}
# Columns that correlate_structure_metrics.extract_run computes from response.json.
RESPONSE_DERIVED = tuple(k for k in METRIC_KEYS if not k.startswith("tcp_"))
# correlate_structure_metrics.PAPER_HEATMAP_METRICS (the paper's Figure uses it without TTFT).
PAPER_HEATMAP = (
    ("Mean IAT", "disc_mean_iat_s"),
    ("Calls", "disc_n_requests"),
    ("Tokens", "disc_total_tokens"),
    ("Call latency", "disc_mean_latency_s"),
    ("In-flight", "llm_inflight_mean"),
    ("Token rate", "prompt_tokens_per_s_mean"),
    ("TCP bytes", "tcp_bytes_llm_mean_Bps"),
    ("TTFT p95", "llm_ttft_p95_mean_s"),
)

# --- runs.json call encoding --------------------------------------------------------------------
STAGE_CODES = (
    "recruitment",  # expert_recruitment (orchestrator); one per iteration, starts it
    "discussion",  # horizontal_discussion / vertical_solver / vertical_reviewer / full_mesh_message
    "discussion_synthesis",  # synthesize_discussion (orchestrator, still in the discussion window)
    "execution",  # execute_<role>
    "evaluation",  # evaluate_results (orchestrator)
    "final_output",  # final_output (orchestrator, after the last iteration)
)
CALL_FIELDS = (
    "start_ms",
    "dur_ms",
    "stage",
    "agent",
    "peer",
    "round",
    "prompt_tokens",
    "completion_tokens",
    "queue_wait_ms",
)
_DISCUSSION_CALL_PREFIXES = (
    "horizontal_discussion",
    "vertical_solver",
    "vertical_reviewer",
    "full_mesh_message",
)
_AGENT_SOURCE_RE = re.compile(r"^agent-b-(\d+)$")
_MESH_LABEL_RE = re.compile(r"_agent(\d+)_to_agent(\d+)$")

JOIN_REL_TOL = 1e-9
RHO_TOL = 1e-9


# ---------------------------------------------------------------------------
# Small numeric helpers (stdlib only)
# ---------------------------------------------------------------------------


def is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def sig(x: float | None, digits: int = 6) -> float | int | None:
    """Round to ``digits`` significant digits; integral values become ints (shorter JSON)."""
    if x is None or not math.isfinite(x):
        return None
    if x == 0:
        return 0
    y = float(f"{x:.{digits}g}")
    return int(y) if y.is_integer() and abs(y) < 1e15 else y


def fmean(values: list[float]) -> float:
    return math.fsum(values) / len(values)


def nan_mean(values: Iterable[float | None]) -> float:
    vals = [v for v in values if is_num(v)]
    return fmean(vals) if vals else math.nan


def describe(values: Iterable[float | None]) -> dict:
    vals = [v for v in values if is_num(v)]
    if not vals:
        return {"median": None, "p25": None, "p75": None, "mean": None, "n": 0}
    return {
        "median": sig(statistics.median(vals)),
        "p25": sig(percentile(vals, 25)),
        "p75": sig(percentile(vals, 75)),
        "mean": sig(fmean(vals)),
        "n": len(vals),
    }


# ---------------------------------------------------------------------------
# Spearman
# ---------------------------------------------------------------------------


def rankdata(values: list[float]) -> list[float]:
    """1-based ranks, ties get the average rank (scipy.stats.rankdata 'average')."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 2:
        return None
    mx, my = fmean(x), fmean(y)
    dx = [a - mx for a in x]
    dy = [b - my for b in y]
    sxx = math.fsum(a * a for a in dx)
    syy = math.fsum(b * b for b in dy)
    if sxx == 0 or syy == 0:
        return None
    r = math.fsum(a * b for a, b in zip(dx, dy)) / math.sqrt(sxx * syy)
    return max(-1.0, min(1.0, r))


def spearman(x: list[float | None], y: list[float | None]) -> tuple[float | None, int]:
    """Spearman rho over pairwise-complete observations, and that number of pairs."""
    pairs = [(a, b) for a, b in zip(x, y) if is_num(a) and is_num(b)]
    if len(pairs) < 2:
        return None, len(pairs)
    xs, ys = zip(*pairs)
    return pearson(rankdata(list(xs)), rankdata(list(ys))), len(pairs)


def spearman_matrix(columns: list[list[float | None]]) -> tuple[list[list], list[list[int]]]:
    k = len(columns)
    rho: list[list] = [[None] * k for _ in range(k)]
    npair = [[0] * k for _ in range(k)]
    for i in range(k):
        for j in range(i, k):
            r, n = spearman(columns[i], columns[j])
            if i == j and r is not None:
                r = 1.0
            rho[i][j] = rho[j][i] = r
            npair[i][j] = npair[j][i] = n
    return rho, npair


# ---------------------------------------------------------------------------
# Distribution fits and the Kolmogorov-Smirnov distribution
# ---------------------------------------------------------------------------

_LOG_2PI = math.log(2 * math.pi)
_STIRLING = (
    -2.955065359477124183e-2,
    6.4102564102564102564e-3,
    -1.9175269175269175269e-3,
    8.4175084175084175084e-4,
    -5.952380952380952381e-4,
    7.9365079365079365079e-4,
    -2.7777777777777777778e-3,
    8.3333333333333333333e-2,
)


def _log_nfactorial_div_n_pow_n(n: int) -> float:
    rn = 1.0 / n
    poly = 0.0
    for c in _STIRLING:
        poly = poly * (rn / n) + c
    return math.log(n) / 2 - n + _LOG_2PI / 2 + rn * poly


def smirnov_sf(n: int, d: float) -> float:
    """Exact one-sided P(D_n^+ >= d) (Birnbaum-Tingey sum, in log space)."""
    if d <= 0:
        return 1.0
    if d >= 1:
        return 0.0
    log_terms = []
    lg_n1 = math.lgamma(n + 1)
    for j in range(int(math.floor(n * (1 - d))) + 1):
        a = 1.0 - d - j / n
        b = d + j / n
        if a <= 0:
            continue
        log_terms.append(
            lg_n1
            - math.lgamma(j + 1)
            - math.lgamma(n - j + 1)
            + (n - j) * math.log(a)
            + (j - 1) * math.log(b)
        )
    if not log_terms:
        return 0.0
    m = max(log_terms)
    return min(1.0, d * math.exp(m) * math.fsum(math.exp(t - m) for t in log_terms))


def _matmul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    bt = list(zip(*b))
    return [[math.fsum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def kolmogorov_cdf_dmtw(n: int, d: float) -> float:
    """Exact P(D_n <= d): Durbin matrix, Marsaglia-Tsang-Wang (port of scipy's _kolmogn_DMTW)."""
    if d >= 1.0:
        return 1.0
    nd = n * d
    if nd <= 0.5:
        return 0.0
    k = int(math.ceil(nd))
    h = k - nd
    m = 2 * k - 1
    v = [1.0 - h ** (j + 1) for j in range(m)]
    w = [0.0] * m
    fac = 1.0
    for j in range(1, m + 1):
        w[j - 1] = fac
        fac /= j
        v[j - 1] *= fac
    tt = max(2 * h - 1.0, 0) ** m - 2 * h**m
    v[-1] = (1.0 + tt) * fac
    mat = [[0.0] * m for _ in range(m)]
    for i in range(1, m):
        for r in range(i - 1, m):
            mat[r][i] = w[r - (i - 1)]
    for r in range(m):
        mat[r][0] = v[r]
    mat[-1] = v[::-1]
    power = [[1.0 if r == c else 0.0 for c in range(m)] for r in range(m)]
    e128 = 2.0**128
    nn, expnt, mexpnt = n, 0, 0
    while nn > 0:
        if nn % 2:
            power = _matmul(power, mat)
            expnt += mexpnt
        mat = _matmul(mat, mat)
        mexpnt *= 2
        if abs(mat[k - 1][k - 1]) > e128:
            mat = [[x / e128 for x in row] for row in mat]
            mexpnt += 128
        nn //= 2
    p = power[k - 1][k - 1]
    for i in range(1, n + 1):
        p = i * p / n
        if abs(p) < 1.0 / e128:
            p *= e128
            expnt -= 128
    return math.ldexp(p, expnt)


def kolmogorov_cdf_pelz_good(n: int, x: float) -> float:
    """Pelz-Good asymptotic P(D_n <= x) (port of scipy's _kolmogn_PelzGood)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    pi2, pi4, pi6 = math.pi**2, math.pi**4, math.pi**6
    z = math.sqrt(n) * x
    z2, z3, z4, z6 = z**2, z**3, z**4, z**6
    qlog = -pi2 / 8 / z2
    if qlog < -708:
        return 0.0
    q = math.exp(qlog)
    k1a, k1b = -z2, pi2 / 4
    k2a = 6 * z6 + 2 * z4
    k2b = (2 * z4 - 5 * z2) * pi2 / 4
    k2c = pi4 * (1 - 2 * z2) / 16
    k3d = pi6 * (5 - 30 * z2) / 64
    k3c = pi4 * (-60 * z2 + 212 * z4) / 16
    k3b = pi2 * (135 * z4 - 96 * z6) / 4
    k3a = -30 * z6 - 90 * z**8
    kk = [0.0, 0.0, 0.0, 0.0]
    maxk = int(math.ceil(16 * z / math.pi))
    for k in range(maxk, 0, -1):
        m = 2 * k - 1
        m2, m4, m6 = m**2, m**4, m**6
        qpower = q ** (8 * k)
        coeffs = (
            1.0,
            k1a + k1b * m2,
            k2a + k2b * m2 + k2c * m4,
            k3a + k3b * m2 + k3c * m4 + k3d * m6,
        )
        kk = [a * qpower + c for a, c in zip(kk, coeffs)]
    sqrt2pi = math.sqrt(2 * math.pi)
    kk = [a * q * sqrt2pi for a in kk]
    kk = [a / dv for a, dv in zip(kk, (z, 6 * z4, 72 * z**7, 6480 * z**10))]
    q = math.exp(-pi2 / 2 / z2)
    ks = range(maxk, 0, -1)
    qp = [q ** (k * k) for k in ks]
    k2extra = math.fsum(k * k * p for k, p in zip(ks, qp)) * pi2 * sqrt2pi / (-36 * z3)
    sqrt3z = math.sqrt(3) * z
    k3extra = math.fsum(
        (sqrt3z + math.pi * k) * (sqrt3z - math.pi * k) * k * k * p for k, p in zip(ks, qp)
    )
    kk[2] += k2extra
    kk[3] += k3extra * pi2 * sqrt2pi / (216 * z6)
    kk = [a / (n ** (i / 2.0)) for i, a in enumerate(kk)]
    return sum(kk)


def ks_pvalue(d: float, n: int) -> float:
    """Two-sided one-sample KS p-value P(D_n >= d), as scipy.stats.kstwo.sf(d, n)."""
    if n <= 0 or math.isnan(d):
        return math.nan
    if d >= 1.0:
        return 0.0
    if d <= 0.0:
        return 1.0

    def clip(p: float) -> float:
        return min(1.0, max(0.0, p))

    t = n * d
    if t <= 1.0:
        if t <= 0.5:
            return 1.0
        if n <= 140:
            prob = 1.0
            for i in range(1, n + 1):
                prob *= i * (1.0 / n) * (2 * t - 1)
        else:
            prob = math.exp(_log_nfactorial_div_n_pow_n(n) + n * math.log(2 * t - 1))
        return clip(1.0 - prob)
    if t >= n - 1:
        return clip(2 * (1.0 - d) ** n)
    if d >= 0.5:
        return clip(2 * smirnov_sf(n, d))
    nx2 = t * d
    if n <= 140:
        if nx2 <= 4:  # scipy: DMTW below 0.754693, Pomeranz up to 4; both exact
            return clip(1.0 - kolmogorov_cdf_dmtw(n, d))
        return clip(2 * smirnov_sf(n, d))
    if nx2 >= 370.0:
        return 0.0
    if nx2 >= 2.2:
        return clip(2 * smirnov_sf(n, d))
    if n <= 100000 and n * d**1.5 <= 1.4:
        return clip(1.0 - kolmogorov_cdf_dmtw(n, d))
    return clip(1.0 - kolmogorov_cdf_pelz_good(n, d))


def ks_statistic(sorted_x: list[float], cdf: Callable[[float], float]) -> float:
    """One-sample KS statistic D = max(D+, D-) of sorted data against ``cdf``."""
    n = len(sorted_x)
    d = 0.0
    for i, x in enumerate(sorted_x):
        c = cdf(x)
        d = max(d, (i + 1) / n - c, c - i / n)
    return d


def fit_lognormal(xs: list[float]) -> dict:
    logs = [math.log(x) for x in xs]
    mu = fmean(logs)
    sigma = math.sqrt(math.fsum((v - mu) ** 2 for v in logs) / len(logs))
    loglik = math.fsum(
        -v - math.log(sigma) - 0.5 * _LOG_2PI - (v - mu) ** 2 / (2 * sigma**2) for v in logs
    )
    s2 = sigma * math.sqrt(2)
    return {
        "mu": mu,
        "sigma": sigma,
        "median_s": math.exp(mu),
        "loglik": loglik,
        "k": 2,
        "cdf": lambda x: 0.5 * math.erfc(-(math.log(x) - mu) / s2),
    }


def fit_exponential(xs: list[float]) -> dict:
    mean = fmean(xs)
    loglik = -len(xs) * math.log(mean) - math.fsum(xs) / mean
    return {
        "lambda": 1.0 / mean,
        "mean_s": mean,
        "loglik": loglik,
        "k": 1,
        "cdf": lambda x: -math.expm1(-x / mean),
    }


def fit_weibull(xs: list[float]) -> dict:
    """Weibull MLE with location 0: solve the shape equation by bisection."""
    logs = [math.log(x) for x in xs]
    mean_log = fmean(logs)

    def g(k: float) -> float:  # increasing in k; root = MLE shape
        w = [k * v for v in logs]
        top = max(w)
        e = [math.exp(t - top) for t in w]
        return math.fsum(a * b for a, b in zip(e, logs)) / math.fsum(e) - 1.0 / k - mean_log

    lo, hi = 1e-3, 1.0
    while g(hi) < 0:
        lo, hi = hi, hi * 2
        if hi > 1e4:
            raise ValueError("Weibull shape did not bracket")
    for _ in range(200):
        mid = (lo + hi) / 2
        if g(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * hi:
            break
    k = (lo + hi) / 2
    w = [k * v for v in logs]
    top = max(w)
    # scale = (mean x^k)^(1/k), computed in log space
    scale = math.exp((top + math.log(math.fsum(math.exp(t - top) for t in w) / len(w))) / k)
    loglik = math.fsum(
        math.log(k / scale) + (k - 1) * (v - math.log(scale)) - (math.exp(v) / scale) ** k
        for v in logs
    )
    return {
        "k": 2,
        "shape": k,
        "scale_s": scale,
        "loglik": loglik,
        "cdf": lambda x: -math.expm1(-((x / scale) ** k)),
    }


def reasoning_phase_sample(iats: list[float], topology: str) -> tuple[list[float], dict]:
    """The paper's fit sample (make_session_proxy_figures.plot_iat_distribution_fits)."""
    pos = [x for x in iats if x > 0]
    scope: dict[str, Any] = {"n_iats": len(iats), "n_positive": len(pos), "fence_s": None}
    if topology in FENCED_TOPOLOGIES and pos:
        q1, q3 = percentile(pos, 25), percentile(pos, 75)
        fence = q3 + FENCE_IQR * (q3 - q1)
        pos = [x for x in pos if x <= fence]
        scope["fence_s"] = fence
    scope["n_after_fence"] = len(pos)
    slow = [x for x in pos if x > BURST_THRESHOLD_S]
    scope["n_reasoning"] = len(slow)
    if not slow:
        return [], {**scope, "clip_s": None, "n": 0}
    clip = percentile(slow, FIT_CLIP_PERCENTILE)
    sample = sorted(x for x in slow if x <= clip)
    return sample, {**scope, "clip_s": clip, "n": len(sample)}


def fit_all(sample: list[float]) -> dict[str, dict]:
    """Fit the three families; returns rounded, JSON-ready dicts with KS, p-value and AIC."""
    out: dict[str, dict] = {}
    n = len(sample)
    for name, fitter in (
        ("lognormal", fit_lognormal),
        ("exponential", fit_exponential),
        ("weibull", fit_weibull),
    ):
        f = fitter(sample)
        d = ks_statistic(sample, f["cdf"])
        params = {k: v for k, v in f.items() if k not in ("cdf", "loglik", "k")}
        out[name] = {
            **{k: sig(v, 8) for k, v in params.items()},
            "ks": sig(d, 6),
            "p_value": sig(ks_pvalue(d, n), 6),
            "aic": sig(2 * f["k"] - 2 * f["loglik"], 8),
        }
    return out


# ---------------------------------------------------------------------------
# Log bins
# ---------------------------------------------------------------------------


def log_bin_edges(
    anchor: float = BIN_ANCHOR_S,
    per_decade: int = BINS_PER_DECADE,
    j_range: tuple[int, int] = BIN_J_RANGE,
) -> list[float]:
    """Edges ``anchor * 10**(j/per_decade)`` for j in [lo, hi], rounded to 6 significant digits."""
    lo, hi = j_range
    return [sig(anchor * 10 ** (j / per_decade)) for j in range(lo, hi + 1)]


def histogram(values: Iterable[float], edges: list[float]) -> dict:
    """Counts per [edges[i], edges[i+1]) plus values below / at-or-above the range."""
    counts = [0] * (len(edges) - 1)
    under = over = 0
    for v in values:
        if v < edges[0]:
            under += 1
        elif v >= edges[-1]:
            over += 1
        else:
            counts[bisect.bisect_right(edges, v) - 1] += 1
    return {"counts": counts, "underflow": under, "overflow": over}


# ---------------------------------------------------------------------------
# Per-run extraction
# ---------------------------------------------------------------------------


def _time_weighted_concurrency(intervals: list[tuple[float, float]]) -> tuple[float, float]:
    """Mean and peak concurrency (correlate_structure_metrics._time_weighted_concurrency)."""
    clean = [(s, e) for s, e in intervals if e > s]
    if not clean:
        return math.nan, math.nan
    window_start = min(s for s, _ in clean)
    window_end = max(e for _, e in clean)
    if window_end <= window_start:
        return math.nan, math.nan
    events = sorted(
        [(s, 1) for s, _ in clean] + [(e, -1) for _, e in clean], key=lambda t: (t[0], -t[1])
    )
    active, last_t, area, peak = 0, window_start, 0.0, 0
    for t, delta in events:
        if t > last_t:
            area += active * (t - last_t)
            last_t = t
        active += delta
        peak = max(peak, active)
    return area / (window_end - window_start), float(peak)


def _pct_or_nan(values: list[float], q: float) -> float:
    clean = [v for v in values if math.isfinite(v)]
    return percentile(clean, q) if clean else math.nan


def response_metrics(requests: list[dict]) -> dict[str, float]:
    """The response.json-derived columns of per_run_metrics.csv (extract_run, first half)."""
    disc_ts: list[float] = []
    durations: list[float] = []
    queue_waits: list[float] = []
    tokens = prompt_tokens = completion_tokens = 0
    intervals: list[tuple[float, float]] = []
    for req in requests:
        if not str(req.get("label", "")).startswith(CORR_DISC_PREFIXES):
            continue
        start = parse_ts(req.get("start_time_utc"))
        if start is not None:
            disc_ts.append(start)
        dur = req.get("duration_seconds")
        if dur is not None:
            durations.append(float(dur))
            if start is not None:
                intervals.append((start, start + max(float(dur), 0.0)))
        meta = req.get("llm_meta") or {}
        queue_wait = meta.get("queue_wait_s", req.get("queue_wait_s"))
        if queue_wait is not None:
            queue_waits.append(float(queue_wait))
        p = int(meta.get("prompt_tokens", 0) or 0)
        c = int(meta.get("completion_tokens", 0) or 0)
        prompt_tokens += p
        completion_tokens += c
        tokens += p + c

    row: dict[str, float] = {"disc_n_requests": float(len(disc_ts))}
    ts = sorted(disc_ts)
    iats = [b - a for a, b in zip(ts, ts[1:])]
    if len(ts) >= 2:
        row["disc_duration_s"] = ts[-1] - ts[0]
        row["disc_mean_iat_s"] = fmean(iats)
    else:
        row["disc_duration_s"] = row["disc_mean_iat_s"] = math.nan
    row["disc_total_tokens"] = float(tokens)
    row["disc_mean_latency_s"] = fmean(durations) if durations else math.nan
    row["llm_latency_p50_mean_s"] = _pct_or_nan(durations, 50)
    row["llm_latency_p95_mean_s"] = _pct_or_nan(durations, 95)
    row["llm_ttft_p50_mean_s"] = row["llm_queue_wait_p50_mean_s"] = _pct_or_nan(queue_waits, 50)
    row["llm_ttft_p95_mean_s"] = row["llm_queue_wait_p95_mean_s"] = _pct_or_nan(queue_waits, 95)
    row["llm_inflight_mean"], row["llm_inflight_peak"] = _time_weighted_concurrency(intervals)
    dur_s = row["disc_duration_s"]
    if math.isfinite(dur_s) and dur_s > 0:
        row["prompt_tokens_per_s_mean"] = prompt_tokens / dur_s
        row["completion_tokens_per_s_mean"] = completion_tokens / dur_s
    else:
        row["prompt_tokens_per_s_mean"] = row["completion_tokens_per_s_mean"] = math.nan
    if len(ts) >= 3:
        avg = fmean(iats)
        row["iat_mean_s"] = avg
        row["iat_jitter_p50_mean_s"] = percentile(iats, 50)
        row["iat_jitter_p95_mean_s"] = percentile(iats, 95)
        row["burstiness_mean"] = max(iats) / avg if avg > 0 else math.nan
        row["burstiness_max"] = max(iats)
    else:
        row["iat_mean_s"] = row["disc_mean_iat_s"]
        for k in ("iat_jitter_p50_mean_s", "iat_jitter_p95_mean_s"):
            row[k] = math.nan
        row["burstiness_mean"] = row["burstiness_max"] = math.nan
    return row


def _stage_code(req: dict) -> int:
    label = str(req.get("label", ""))
    stage = req.get("stage")
    if label.startswith(_DISCUSSION_CALL_PREFIXES):
        return 1
    if label.startswith("synthesize_discussion"):
        return 2
    for code, name in ((0, "recruitment"), (3, "execution"), (4, "evaluation")):
        if stage == name:
            return code
    if stage == "synthesis" or label == "final_output":
        return 5
    raise ValueError(f"unknown LLM call stage/label: {stage!r} / {label!r}")


def _roster(doc: dict) -> tuple[list[str], dict[int, list[str]]]:
    experts = (doc.get("stages", {}).get("recruitment", {}) or {}).get("experts") or []
    final = [e.get("role") if isinstance(e, dict) else str(e) for e in experts]
    by_iter = {}
    for h in doc.get("iteration_history") or []:
        roles = (h.get("recruitment") or {}).get("experts")
        if isinstance(h.get("iteration"), int) and isinstance(roles, list):
            by_iter[h["iteration"]] = [r.get("role") if isinstance(r, dict) else r for r in roles]
    return final, by_iter


def _ms(seconds: float | None, ndigits: int = 0) -> int | float | None:
    if seconds is None:
        return None
    v = round(float(seconds) * 1000.0, ndigits)
    return int(v) if float(v).is_integer() else v


def encode_calls(
    requests: list[dict],
    topology: str,
    roster_for: Callable[[Any], list[str]] | None = None,
) -> tuple[list[list], list[str]]:
    """Compact call rows (CALL_FIELDS order) and problems found while resolving agents.

    agent: recruitment position of the calling expert from ``source`` = ``agent-b-<i+1>`` (set by
    the orchestrator from ``expert.index``; this also disambiguates duplicate roles), -1 for the
    orchestrator ("Agent A"). peer: full mesh -> receiver (``..._agent<s>_to_agent<r>`` label,
    i.e. sender_role / receiver_role); star reviewer -> the solver of the same iteration (hub);
    sequential discussion -> the chain predecessor (agent - 1, none for the first agent), as
    ``_topoTarget`` in ui/playground/js/renderers.js; otherwise -1. With ``roster_for``
    (iteration -> roles), every agent index is checked against the call's ``agent_role``.
    """
    problems: list[str] = []
    starts = [parse_ts(r.get("start_time_utc")) for r in requests]
    known = [s for s in starts if s is not None]
    t0 = min(known) if known else 0.0

    def agent_of(req: dict) -> int:
        m = _AGENT_SOURCE_RE.match(str(req.get("source", "")))
        return int(m.group(1)) - 1 if m else -1

    solver_by_iter: dict[Any, int] = {}
    for req in requests:
        if str(req.get("label", "")).startswith("vertical_solver"):
            solver_by_iter.setdefault(req.get("iteration"), agent_of(req))

    rows = []
    order = sorted(
        range(len(requests)),
        key=lambda i: (starts[i] if starts[i] is not None else math.inf, i),
    )
    for i in order:
        req = requests[i]
        label = str(req.get("label", ""))
        agent = agent_of(req)
        if roster_for is not None and agent >= 0:
            roster = roster_for(req.get("iteration"))
            if agent >= len(roster) or roster[agent] != req.get("agent_role"):
                problems.append(f"agent {agent} is not {req.get('agent_role')!r} in {roster}")
        peer = -1
        if label.startswith("full_mesh_message"):
            m = _MESH_LABEL_RE.search(label)
            if m:
                if int(m.group(1)) - 1 != agent:
                    problems.append(f"sender in label {label!r} != source {req.get('source')!r}")
                peer = int(m.group(2)) - 1
        elif label.startswith("vertical_reviewer"):
            peer = solver_by_iter.get(req.get("iteration"), -1)
        elif label.startswith("horizontal_discussion") and topology == "horizontal" and agent > 0:
            peer = agent - 1
        meta = req.get("llm_meta") or {}
        start = starts[i]
        rnd = req.get("round")
        rows.append(
            [
                _ms(start - t0) if start is not None else None,
                _ms(req.get("duration_seconds")),
                _stage_code(req),
                agent,
                peer,
                rnd if isinstance(rnd, int) else None,
                meta.get("prompt_tokens"),
                meta.get("completion_tokens"),
                _ms(meta.get("queue_wait_s"), 1),
            ]
        )
    return rows, problems


@dataclass
class Run:
    experiment: str
    task_dir: str
    category: str
    task_id: str
    topology: str | None
    structure_used: str | None
    disc_iats: list[float]
    response_metrics: dict[str, float]
    n_disc_errors: int
    calls: list[list] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    roles_by_iteration: list[list[str]] | None = None
    iterations: int = 1
    score: Any = None
    goal_achieved: Any = None
    consensus_reached: Any = None
    discussion_rounds: int | None = None
    n_roles: int = 0
    problems: list[str] = field(default_factory=list)
    run_id: str = ""
    csv_row: dict[str, float | None] | None = None
    join_method: str | None = None

    @property
    def task(self) -> str:
        return CATEGORY_TO_TASK[self.category]


def extract_run(doc: dict, experiment: str, task_dir: str) -> Run:
    m = _TASK_DIR_RE.match(task_dir)
    if not m or m.group("category") not in CATEGORY_TO_TASK:
        raise ValueError(f"unexpected task dir name {task_dir!r}")
    requests = doc.get("llm_requests") or []
    topology = label_topology(requests)
    stages = doc.get("stages", {}) or {}
    decision = stages.get("decision", {}) or {}
    evaluation = stages.get("evaluation", {}) or {}
    final, by_iter = _roster(doc)
    calls, problems = encode_calls(requests, topology or "", lambda it: by_iter.get(it, final))
    rounds = decision.get("discussion_rounds")
    rosters = [by_iter[k] for k in sorted(by_iter)]
    return Run(
        experiment=experiment,
        task_dir=task_dir,
        category=m.group("category"),
        task_id=str(doc.get("task_id", "")),
        topology=topology,
        structure_used=decision.get("structure_used"),
        disc_iats=discussion_iats(requests, topology) if topology else [],
        response_metrics=response_metrics(requests),
        n_disc_errors=sum(
            1
            for r in requests
            if r.get("error") and str(r.get("label", "")).startswith(CORR_DISC_PREFIXES)
        ),
        calls=calls,
        roles=final,
        roles_by_iteration=rosters if any(r != final for r in rosters) else None,
        iterations=int(doc.get("iterations") or 1),
        score=evaluation.get("score"),
        goal_achieved=evaluation.get("goal_achieved"),
        consensus_reached=decision.get("consensus_reached"),
        discussion_rounds=len(rounds) if isinstance(rounds, list) else rounds,
        n_roles=len(final),
        problems=problems,
    )


def scan_runs(source: Path) -> tuple[list[Run], list[str]]:
    runs, warnings = [], []
    for experiment, task_dir, path in find_response_files(source):
        try:
            run = extract_run(load_response(path), experiment, task_dir)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"skipped {experiment}/{task_dir}: {exc}")
            continue
        if run.topology != run.structure_used:
            warnings.append(
                f"{experiment}/{task_dir}: labels say {run.topology}, structure_used="
                f"{run.structure_used}; the labels are used (as in the paper)"
            )
        runs.append(run)
    assign_run_ids(runs)
    return runs, warnings


def assign_run_ids(runs: list[Run]) -> None:
    """Short ids: the first 8 hex digits of the task UUID, longer only on a collision."""
    uuids = [_TASK_DIR_RE.match(r.task_dir).group("uuid").replace("-", "") for r in runs]
    width = 8
    while len({u[:width] for u in uuids}) < len(uuids):
        width += 2
    for run, u in zip(runs, uuids):
        run.run_id = u[:width]


# ---------------------------------------------------------------------------
# per_run_metrics.csv
# ---------------------------------------------------------------------------


def read_per_run_csv(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            row: dict[str, Any] = {
                "structure": raw.get("structure"),
                "task_slug": raw.get("task_slug"),
            }
            for key in METRIC_KEYS:
                val = raw.get(key, "")
                try:
                    num = float(val)
                except (TypeError, ValueError):
                    num = math.nan
                row[key] = num if math.isfinite(num) else None
            rows.append(row)
    return rows


def _same(a: float | None, b: float | None) -> bool:
    a_ok, b_ok = is_num(a), is_num(b)
    if not a_ok or not b_ok:
        return not a_ok and not b_ok
    return math.isclose(a, b, rel_tol=JOIN_REL_TOL, abs_tol=1e-12)


def row_matches(run: Run, row: dict[str, Any]) -> bool:
    if row.get("structure") != run.topology or row.get("task_slug") != run.category:
        return False
    return all(_same(run.response_metrics.get(k), row.get(k)) for k in RESPONSE_DERIVED)


def join_csv(runs: list[Run], rows: list[dict[str, Any]]) -> dict:
    """Attach CSV rows to runs: by position, else by a unique full fingerprint (never guesses)."""
    used: set[int] = set()
    pending = []
    for i, run in enumerate(runs):
        run.csv_row, run.join_method = None, None
        if i < len(rows) and row_matches(run, rows[i]):
            run.csv_row, run.join_method = rows[i], "order"
            used.add(i)
        else:
            pending.append(run)
    ambiguous = 0
    for run in pending:
        hits = [j for j, row in enumerate(rows) if j not in used and row_matches(run, row)]
        if len(hits) == 1:
            run.csv_row, run.join_method = rows[hits[0]], "fingerprint"
            used.add(hits[0])
        elif len(hits) > 1:
            ambiguous += 1
    by_order = sum(1 for r in runs if r.join_method == "order")
    by_fp = sum(1 for r in runs if r.join_method == "fingerprint")
    return {
        "runs": len(runs),
        "csv_rows": len(rows),
        "matched_by_order": by_order,
        "matched_by_fingerprint": by_fp,
        "unmatched_runs": len(runs) - by_order - by_fp,
        "ambiguous_runs": ambiguous,
        "unused_csv_rows": len(rows) - len(used),
        "match_rate": round((by_order + by_fp) / len(runs), 6) if runs else 0.0,
        "method": (
            "row i <-> i-th response (experiments in chronological order, task dirs sorted, as "
            "correlate_structure_metrics.load_all_runs); accepted only if structure, task_slug "
            f"and all {len(RESPONSE_DERIVED)} response-derived columns match (rel. tol. "
            f"{JOIN_REL_TOL:g}); otherwise a unique full-fingerprint match among unused rows"
        ),
    }


# ---------------------------------------------------------------------------
# Table 2: parse and recompute
# ---------------------------------------------------------------------------

TABLE2_SECTION_TITLES = ("Application", "Inter-arrival times", "LLM backend", "Network")
_T2_NAMES = {"Sequential": "horizontal", "Star": "vertical", "Full Mesh": "full_mesh"}
_FOOTNOTE_MARKS = "¹²³⁴⁵⁶⁷⁸⁹"


def _plain(text: str) -> str:
    return re.sub(r"[*`]", "", text).strip()


def parse_table2(text: str) -> dict:
    lines = text.splitlines()
    out: dict[str, Any] = {"title": "", "source": "", "runs": {}, "pooled_iats": {}, "notes": []}
    sections: list[list[dict]] = [[]]
    footnotes: list[dict] = []
    in_footnotes = False
    header_seen = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("# "):
            out["title"] = s[2:].strip()
        elif s.startswith("Source:"):
            out["source"] = _plain(s[len("Source:") :])
        elif s.startswith("Runs:") or s.startswith("Pooled IATs"):
            key = "runs" if s.startswith("Runs:") else "pooled_iats"
            for label, n in re.findall(r"(Sequential|Star|Full Mesh) n=(\d+)", s):
                out[key][_T2_NAMES[label]] = int(n)
        elif s.startswith(">"):
            out["notes"].append(_plain(s.lstrip("> ")))
        elif s == "**Footnotes**":
            in_footnotes = True
        elif in_footnotes and s and s[0] in _FOOTNOTE_MARKS:
            footnotes.append({"mark": s[0], "text": _plain(s[1:])})
        elif s.startswith("|"):
            note = None
            m = re.search(r"<!--\s*(.*?)\s*-->", s)
            if m:
                note = m.group(1)
                s = s[: m.start()].strip()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if not header_seen:
                header_seen = cells[0] == "Metric"
                continue
            if set("".join(cells)) <= set("-: "):
                if any(cells):
                    continue  # the |---| separator
                if sections[-1]:
                    sections.append([])  # blank row separates sections
                continue
            if len(cells) < 4:
                continue
            metric = _plain(cells[0])
            mark = None
            if metric and metric[-1] in _FOOTNOTE_MARKS:
                metric, mark = metric[:-1].strip(), metric[-1]
            row: dict[str, Any] = {"metric": metric, "values": dict(zip(TOPOLOGIES, cells[1:4]))}
            if mark:
                row["footnote"] = mark
            if note:
                row["note"] = note
            sections[-1].append(row)
    sections = [s for s in sections if s]
    if not sections:
        raise ValueError("no table rows found in table2.md")
    titles = TABLE2_SECTION_TITLES if len(sections) == len(TABLE2_SECTION_TITLES) else ()
    out["sections"] = [
        {**({"title": titles[i]} if titles else {}), "rows": rows}
        for i, rows in enumerate(sections)
    ]
    # The note on the TCP flow-duration rows is not shown: drop it and the marks that pointed to it.
    dropped = {f["mark"] for f in footnotes if f["text"].startswith("TCP flow duration p50/p95")}
    out["footnotes"] = [f for f in footnotes if f["mark"] not in dropped]
    for sec in out["sections"]:
        for row in sec["rows"]:
            if row.get("footnote") in dropped:
                del row["footnote"]
    return out


def _t2_pct(new: float, base: float) -> str:
    if base == 0:
        return "—"
    val = (new - base) / abs(base) * 100
    return f"{'+' if val >= 0 else ''}{val:.0f}%"


def _t2_fmt_s(x: float) -> str:
    if abs(x) < 0.001:
        return f"{x * 1000:.2f} ms"
    if abs(x) < 1.0:
        return f"{x * 1000:.0f} ms"
    return f"{x:.2f} s"


def _t2_fmt_k(x: float) -> str:
    return f"{x / 1000:.1f}k" if x >= 1000 else f"{x:.0f}"


def _t2_rate(x: float) -> str:
    return f"{x:.0f} B/s" if x < 1000 else f"{x / 1000:.2f} kB/s"


def recompute_table2(rows_by_topo: dict[str, list[dict]], pooled: dict[str, list[float]]) -> dict:
    """Table 2 cell strings, as _compute_table2._build_results + build_markdown produce them."""
    res: dict[str, dict[str, float]] = {}
    for t in TOPOLOGIES:
        sub, iats = rows_by_topo[t], pooled[t]

        def col(key: str, sub: list[dict] = sub) -> float:
            return nan_mean(r[key] for r in sub)

        def ratio(a: str, b: str, sub: list[dict] = sub) -> float:
            return nan_mean(
                r[a] / r[b] if is_num(r[a]) and is_num(r[b]) and r[b] else None for r in sub
            )

        res[t] = {
            "mean_req": col("disc_n_requests"),
            "total_req": int(math.fsum(r["disc_n_requests"] or 0 for r in sub)),
            "call_rate": ratio("disc_n_requests", "disc_duration_s"),
            "duration": col("disc_duration_s"),
            "tok_per_run": col("disc_total_tokens"),
            "tok_per_call": ratio("disc_total_tokens", "disc_n_requests"),
            "mean_lat": col("disc_mean_latency_s"),
            "mean_iat": fmean(iats),
            "med_iat": statistics.median(iats),
            "p95_iat": percentile(iats, 95),
            "burst_frac": sum(1 for x in iats if x < BURST_THRESHOLD_S) / len(iats) * 100,
            "jitter_p50": col("iat_jitter_p50_mean_s"),
            "jitter_p95": col("iat_jitter_p95_mean_s"),
            "lat_p50": col("llm_latency_p50_mean_s"),
            "lat_p95": col("llm_latency_p95_mean_s"),
            "ttft_p50": col("llm_ttft_p50_mean_s"),
            "ttft_p95": col("llm_ttft_p95_mean_s"),
            "mean_conc": col("llm_inflight_mean"),
            "peak_conc": col("llm_inflight_peak"),
            "prompt_tps": col("prompt_tokens_per_s_mean"),
            "comp_tps": col("completion_tokens_per_s_mean"),
            "tcp_bytes_disc": nan_mean(
                (
                    r["tcp_bytes_llm_mean_Bps"] * r["disc_duration_s"]
                    if is_num(r["tcp_bytes_llm_mean_Bps"]) and is_num(r["disc_duration_s"])
                    else None
                )
                for r in sub
            ),
            "tcp_mean_rate": col("tcp_bytes_llm_mean_Bps"),
            "tcp_peak_rate": col("tcp_bytes_llm_peak_Bps"),
            "flow_p50": col("tcp_flow_dur_p50_mean_s"),
            "flow_p95": col("tcp_flow_dur_p95_mean_s"),
        }
    h, v, m = (res[t] for t in TOPOLOGIES)

    def trio(key: str, fmt: Callable[[float], str], pct: bool = True) -> list[str]:
        if not pct:
            return [fmt(h[key]), fmt(v[key]), fmt(m[key])]
        return [
            fmt(h[key]),
            f"{fmt(v[key])} ({_t2_pct(v[key], h[key])})",
            f"{fmt(m[key])} ({_t2_pct(m[key], h[key])})",
        ]

    return {
        "Mean LLM req / rep": trio("mean_req", lambda x: f"{x:.2f}"),
        "Total LLM requests": trio("total_req", lambda x: f"{x:,}"),
        "Discussion call rate": trio("call_rate", lambda x: f"{x:.3f} calls/s"),
        "Duration": trio("duration", _t2_fmt_s),
        "Tokens / run": trio("tok_per_run", _t2_fmt_k),
        "Tokens / call": trio("tok_per_call", _t2_fmt_k),
        "Mean call latency": trio("mean_lat", _t2_fmt_s),
        "Mean IAT": trio("mean_iat", _t2_fmt_s),
        "Median IAT": trio("med_iat", _t2_fmt_s),
        "IAT p95": trio("p95_iat", _t2_fmt_s),
        "Burst fraction (IAT < 50 ms)": trio("burst_frac", lambda x: f"{x:.1f}%", pct=False),
        "IAT jitter p50": trio("jitter_p50", _t2_fmt_s),
        "IAT jitter p95": trio("jitter_p95", _t2_fmt_s),
        "LLM latency p50": trio("lat_p50", _t2_fmt_s),
        "LLM latency p95": trio("lat_p95", _t2_fmt_s),
        "TTFT p50": trio("ttft_p50", _t2_fmt_s),
        "TTFT p95": trio("ttft_p95", _t2_fmt_s),
        "Mean LLM concurrency": trio("mean_conc", lambda x: f"{x:.2f}"),
        "Peak LLM concurrency": trio("peak_conc", lambda x: f"{x:.2f}"),
        "Prompt tok/s": trio("prompt_tps", lambda x: f"{x:.1f} tok/s"),
        "Completion tok/s": trio("comp_tps", lambda x: f"{x:.1f} tok/s"),
        "LLM TCP bytes / run": trio("tcp_bytes_disc", _t2_fmt_k),
        "Mean LLM TCP byte rate": trio("tcp_mean_rate", _t2_rate),
        "Peak LLM TCP byte rate": trio("tcp_peak_rate", _t2_rate),
        "TCP flow dur p50": trio("flow_p50", _t2_fmt_s),
        "TCP flow dur p95": trio("flow_p95", _t2_fmt_s),
    }


def compare_table2(parsed: dict, recomputed: dict, n_failed: dict[str, int]) -> list[dict]:
    rows = []
    for section in parsed["sections"]:
        for row in section["rows"]:
            published = [row["values"][t] for t in TOPOLOGIES]
            if row["metric"] == "Failed discussion calls":
                ours = [str(n_failed[t]) for t in TOPOLOGIES]
            elif row["metric"] in recomputed:
                ours = recomputed[row["metric"]]
            else:
                ours = None
            rows.append(
                {
                    "metric": row["metric"],
                    "published": published,
                    "ours": ours,
                    "ok": ours == published,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Summary sections
# ---------------------------------------------------------------------------


def build_iat(runs: list[Run], edges: list[float]) -> tuple[dict, dict[str, list[float]], list]:
    pooled = {t: [x for r in runs if r.topology == t for x in r.disc_iats] for t in TOPOLOGIES}
    per_topo: dict[str, dict] = {}
    fits: dict[str, dict] = {}
    fit_checks: list[dict] = []
    for t in TOPOLOGIES:
        iats = pooled[t]
        if not iats:
            raise ValueError(f"no discussion IATs for {t}")
        hist = histogram(iats, edges)
        sample, scope = reasoning_phase_sample(iats, t)
        per_topo[t] = {
            "n_runs": sum(1 for r in runs if r.topology == t and len(r.disc_iats) >= 1),
            "n": len(iats),
            "mean_s": sig(fmean(iats)),
            "median_s": sig(statistics.median(iats)),
            "p95_s": sig(percentile(iats, 95)),
            "burst_fraction": sig(sum(1 for x in iats if x < BURST_THRESHOLD_S) / len(iats)),
            **hist,
            "fit_counts": histogram(sample, edges)["counts"],
            "linear_counts": (lin := histogram(iats, LINEAR_EDGES))["counts"],
            "linear_overflow": lin["overflow"],
            "linear_fit_counts": histogram(sample, LINEAR_EDGES)["counts"],
        }
        fit = fit_all(sample)
        best = min(fit, key=lambda k: fit[k]["aic"])
        fits[t] = {
            "n": scope["n"],
            "fraction_of_iats": sig(scope["n"] / len(iats)),
            "range_s": [sig(sample[0]), sig(sample[-1])],
            "fence_s": sig(scope["fence_s"]),
            "clip_s": sig(scope["clip_s"]),
            "n_positive": scope["n_positive"],
            "n_after_fence": scope["n_after_fence"],
            "n_reasoning": scope["n_reasoning"],
            **fit,
            "best_aic": best,
            "best_ks": min(fit, key=lambda k: fit[k]["ks"]),
        }
        fit_checks.extend(check_fit(t, fits[t]))
        if t in PAPER_FIT_TOPOLOGIES:
            fits[t] = paper_fit(t, fits[t])
    return {"per_topology": per_topo, "fits": fits}, pooled, fit_checks


def check_fit(topology: str, fit: dict) -> list[dict]:
    """Compare a fit with the paper's tab:gof at the precision it prints."""
    paper = PAPER_GOF[topology]
    known = KNOWN_FIT_DEVIATIONS.get(topology)
    ln, ex, wb = fit["lognormal"], fit["exponential"], fit["weibull"]
    pairs = [
        ("n", fit["n"], paper["n"], 0),
        ("lognormal sigma", ln["sigma"], paper["lognormal"]["sigma"], 2),
        ("lognormal median (s)", ln["median_s"], paper["lognormal"]["median_s"], 2),
        ("lognormal AIC", ln["aic"], paper["lognormal"]["aic"], 0),
        ("lognormal KS", ln["ks"], paper["lognormal"]["ks"], 3),
        ("exponential mean (s)", ex["mean_s"], paper["exponential"]["mean_s"], 2),
        ("exponential AIC", ex["aic"], paper["exponential"]["aic"], 0),
        ("exponential KS", ex["ks"], paper["exponential"]["ks"], 3),
        ("weibull k", wb["shape"], paper["weibull"]["k"], 2),
        ("weibull scale (s)", wb["scale_s"], paper["weibull"]["scale_s"], 2),
        ("weibull AIC", wb["aic"], paper["weibull"]["aic"], 0),
        ("weibull KS", wb["ks"], paper["weibull"]["ks"], 3),
    ]
    out = []
    for name, ours, theirs, nd in pairs:
        ok = round(ours, nd) == round(theirs, nd)
        out.append(
            {
                "topology": topology,
                "quantity": name,
                "ours": round(ours, nd) if nd else int(round(ours)),
                "paper": theirs,
                "ok": ok,
                "known_deviation": known if not ok else None,
            }
        )
    return out


def build_metrics_catalogue() -> list[dict]:
    out = []
    for key, label, paper_label, unit, layer, desc in METRICS:
        entry = {
            "key": key,
            "label": label,
            "paper_label": paper_label,
            "unit": unit,
            "layer": layer,
            "description": desc,
            "source": "prometheus" if key.startswith("tcp_") else "response",
        }
        if key in DUPLICATE_OF:
            entry["duplicate_of"] = DUPLICATE_OF[key]
        out.append(entry)
    return out


def _columns(runs: list[Run]) -> list[list[float | None]]:
    return [[r.csv_row[k] if r.csv_row else None for r in runs] for k in METRIC_KEYS]


def build_correlations(runs: list[Run], selected_rows: list[dict]) -> tuple[dict, list[dict]]:
    groups: dict[str, dict] = {}
    selection = {"all": runs, **{t: [r for r in runs if r.topology == t] for t in TOPOLOGIES}}
    for name, group in selection.items():
        rho, npair = spearman_matrix(_columns(group))
        flat_n = {n for row in npair for n in row}
        groups[name] = {
            "n": npair[0][0] if len(flat_n) == 1 else npair,
            "rho": [[None if v is None else round(v, 4) for v in row] for row in rho],
        }
    cols = dict(zip(METRIC_KEYS, _columns(runs)))
    selected, checks = [], []
    for row in selected_rows:
        x, y = row["x_metric"], row["y_metric"]
        ours, n = spearman(cols[x], cols[y])
        paper = float(row["spearman_rho"])
        ok = ours is not None and abs(ours - paper) < RHO_TOL and n == int(row["n"])
        checks.append({"x": x, "y": y, "ours": ours, "paper": paper, "n": n, "ok": ok})
        selected.append(
            {
                "relationship": row["relationship"],
                "x": x,
                "y": y,
                "rho": round(paper, 6),
                "n": int(row["n"]),
            }
        )
    return {
        "method": "Spearman rank correlation, pairwise-complete rows, average ranks for ties "
        "(pandas DataFrame.corr(method='spearman')); null where a column is constant",
        "metric_keys": list(METRIC_KEYS),
        "groups": groups,
        "selected": selected,
        "paper_heatmap": [{"label": lb, "key": k} for lb, k in PAPER_HEATMAP],
    }, checks


def build_aggregates(runs: list[Run]) -> dict:
    def stats(group: list[Run]) -> dict:
        return {
            k: describe(r.csv_row[k] if r.csv_row else None for r in group) for k in METRIC_KEYS
        }

    return {
        "stats": ["median", "p25", "p75", "mean", "n"],
        "by_topology": {t: stats([r for r in runs if r.topology == t]) for t in TOPOLOGIES},
        "by_topology_task": {
            t: {
                task: stats([r for r in runs if r.topology == t and r.task == task])
                for task in TASKS
            }
            for t in TOPOLOGIES
        },
    }


QUANTILE_GRID = (0, 1, *range(5, 96, 5), 99, 100)  # percent: p0, p1, p5, p10 ... p95, p99, p100


def build_quantiles(runs: list[Run]) -> dict[str, dict[str, list[float | None]]]:
    """Per-topology quantile tables for every per-run metric: ``out[topology][metric][i]`` is the
    ``QUANTILE_GRID[i]``-th percentile (linear interpolation, as numpy) of that metric over the
    topology's runs, ``None`` throughout when the metric has no values. Aggregate only: this is
    what the synthetic runs (4.2) are sampled from."""
    out: dict[str, dict[str, list[float | None]]] = {}
    for t in TOPOLOGIES:
        group = [r for r in runs if r.topology == t]
        out[t] = {}
        for k in METRIC_KEYS:
            vals = [v for v in (r.csv_row[k] if r.csv_row else None for r in group) if is_num(v)]
            out[t][k] = [sig(percentile(vals, q)) if vals else None for q in QUANTILE_GRID]
    return out


# ---------------------------------------------------------------------------
# Full-mesh scaling (3 / 4 / 5 agents)
# ---------------------------------------------------------------------------


def build_scaling(source: Path, edges: list[float]) -> tuple[dict | None, list[str]]:
    """Discussion IATs per agent count over the run list of make_full_mesh_scaling_figures.py."""
    jsonl = source / SCALING_JSONL_RELPATH
    notes: list[str] = []
    if not jsonl.is_file():
        return None, [f"{SCALING_JSONL_RELPATH} not found; scaling skipped"]
    entries = [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln]
    by_n: dict[int, list[tuple[str, str]]] = {}
    for e in entries:
        parts = Path(e["run_dir"]).parts  # absolute path on the recording machine: never output
        by_n.setdefault(int(e["n_agents"]), []).append((parts[-3], parts[-1]))
    agents = []
    for n_agents in sorted(by_n):
        iats: list[float] = []
        app: dict[str, list[float]] = {k: [] for k in SCALING_APP_METRICS}
        experiments: set[str] = set()
        missing = wrong = 0
        n_runs = 0
        for experiment, task_dir in sorted(by_n[n_agents]):
            tdir = source / "data" / "agentverse" / experiment / "tasks" / task_dir
            path = next(
                (tdir / f for f in ("response.json.gz", "response.json") if (tdir / f).is_file()),
                None,
            )
            if path is None:
                missing += 1
                continue
            doc = load_response(path)
            requests = doc.get("llm_requests") or []
            final, _ = _roster(doc)
            if label_topology(requests) != "full_mesh" or len(final) != n_agents:
                wrong += 1
                continue
            n_runs += 1
            experiments.add(experiment)
            iats.extend(discussion_iats(requests, "full_mesh"))
            rm = response_metrics(requests)
            for k in SCALING_APP_METRICS:
                app[k].append(rm[k])
        if missing or wrong:
            notes.append(
                f"{n_agents} agents: {missing} listed runs missing from the checkout, {wrong} not "
                "full mesh with that agent count"
            )
        if not iats:
            continue
        slow = [x for x in iats if x > BURST_THRESHOLD_S]
        ln = fit_lognormal(slow)
        agents.append(
            {
                "n_agents": n_agents,
                "experiments": sorted(experiments),
                "n_runs": n_runs,
                "n_listed": len(by_n[n_agents]),
                "n": len(iats),
                "mean_s": sig(fmean(iats)),
                "median_s": sig(statistics.median(iats)),
                "p95_s": sig(percentile(iats, 95)),
                "burst_fraction": sig(sum(1 for x in iats if x < BURST_THRESHOLD_S) / len(iats)),
                **histogram(iats, edges),
                "lognormal_reasoning": {
                    "n": len(slow),
                    "mu": sig(ln["mu"]),
                    "sigma": sig(ln["sigma"]),
                },
                "means": {k: sig(nan_mean(v)) for k, v in app.items()},
            }
        )
    return {
        "definition": (
            "Full mesh discussion IATs (full_mesh_message + synthesize_discussion) per recruited "
            "agent count over the run list in figures/n_agents/full_mesh_runs.jsonl, i.e. "
            "make_full_mesh_scaling_figures.py: 3 and 5 agents = both full_mesh_agents{3,5} "
            "experiments, 4 agents = the 200 full-mesh runs of "
            "balanced_agents4_experiment_2026-05-01_08-39-59 (the main IAT section pools all 500). "
            "lognormal_reasoning: ML fit to IATs > 50 ms (the scaling figure's scope, no fence or "
            "clip). means: per-run means of per_run_metrics.csv columns recomputed from the "
            "responses (no TCP metrics: their Prometheus data is not in the checkout)."
        ),
        "bins": "iat.bins_s",
        "agents": agents,
    }, notes


SCALING_APP_METRICS = (
    "disc_n_requests",
    "disc_total_tokens",
    "llm_inflight_mean",
    "prompt_tokens_per_s_mean",
)


# ---------------------------------------------------------------------------
# Fixtures, runs.json
# ---------------------------------------------------------------------------


def build_fixture_map(runs: list[Run], index_path: Path) -> list[dict]:
    if not index_path.is_file():
        return []
    index = json.loads(index_path.read_text(encoding="utf-8"))
    by_dir = {(r.experiment, r.task_dir): r for r in runs}
    out = []
    for f in index.get("fixtures", []):
        run = by_dir.get((f.get("experiment"), f.get("task_dir")))
        if run is None or run.task_id != f.get("task_id"):
            raise ValueError(f"fixture {f.get('topology')}/{f.get('task')} not found in the runs")
        if (run.topology, run.task) != (f.get("topology"), f.get("task")):
            raise ValueError(f"fixture {f.get('task_id')} topology/task disagree with its run")
        out.append(
            {
                "topology": run.topology,
                "task": run.task,
                "task_id": run.task_id,
                "run_id": run.run_id,
                "experiment": run.experiment,
            }
        )
    return out


def build_runs_doc(runs: list[Run], fixtures: list[dict]) -> dict:
    experiments = sorted({r.experiment for r in runs})
    fixture_ids = {f["run_id"] for f in fixtures}
    out_runs = []
    for r in runs:
        entry: dict[str, Any] = {
            "id": r.run_id,
            "topology": r.topology,
            "task": r.task,
            "task_id": r.task_id,
            "experiment": experiments.index(r.experiment),
            "fixture": r.run_id in fixture_ids,
            "iterations": r.iterations,
            "score": r.score,
            "goal_achieved": r.goal_achieved,
            "consensus_reached": r.consensus_reached,
            "discussion_rounds": r.discussion_rounds,
            "metrics": [sig(r.csv_row[k], 5) if r.csv_row else None for k in METRIC_KEYS],
            "roles": r.roles,
        }
        if r.roles_by_iteration:
            entry["roles_by_iteration"] = r.roles_by_iteration
        entry["calls"] = r.calls
        out_runs.append(entry)
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "notes": [
            "experiment: index into experiments. metrics: per_run_metrics.csv values in "
            "metric_keys order (5 significant digits), null if the run has no CSV row.",
            "roles: expert roles of the final iteration in recruitment order; "
            "roles_by_iteration (only when the roster changed between iterations) lists every "
            "iteration's roster. Each iteration starts with its recruitment call.",
            "calls: every LLM call, sorted by start, columns in call_fields order. start_ms: since "
            "the run's first LLM call; dur_ms: duration_seconds (recorded rounded to 10 ms, so back-to-back calls can appear to overlap by up to 5 ms); stage: index into stage_codes; "
            "agent: recruitment position of the calling expert (-1 = orchestrator); peer: "
            "receiver (full mesh), solver/hub (star reviewers), chain predecessor (sequential "
            "discussion), -1 = none; round: discussion round (star: solver iteration), null "
            "outside the discussion; tokens and queue_wait_ms (= TTFT) from llm_meta.",
        ],
        "experiments": experiments,
        "metric_keys": list(METRIC_KEYS),
        "stage_codes": list(STAGE_CODES),
        "call_fields": list(CALL_FIELDS),
        "runs": out_runs,
    }


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def dumps_summary(obj: Any, indent: str = "") -> str:
    """Indented JSON with lists of scalars kept on one line (correlation rows, histograms)."""
    step = indent + " "
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f"{step}{_compact(k)}: {dumps_summary(v, step)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + indent + "}"
    if isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            return _compact(obj)
        return "[\n" + ",\n".join(step + dumps_summary(v, step) for v in obj) + "\n" + indent + "]"
    return _compact(obj)


def dumps_runs(doc: dict) -> str:
    """Compact JSON, one run per line."""
    head = ",".join(f"{_compact(k)}:{_compact(v)}" for k, v in doc.items() if k != "runs")
    body = ",\n".join(_compact(r) for r in doc["runs"])
    return "{" + head + ',"runs":[\n' + body + "\n]}\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _fmt_check_value(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def build_all(source: Path) -> tuple[dict, dict, dict]:
    """Return (summary, runs_doc, report) for a source checkout. Raises ValueError on bad input."""
    runs, warnings = scan_runs(source)
    if not runs:
        raise ValueError(f"no runs under {source}/data/agentverse/{EXPERIMENT_GLOB}/tasks")
    for p in (source / TABLE2_RELPATH, source / PER_RUN_CSV_RELPATH, source / SELECTED_CSV_RELPATH):
        if not p.is_file():
            raise ValueError(f"missing input {p}")
    unknown = [r for r in runs if r.topology not in TOPOLOGIES]
    if unknown:
        raise ValueError(f"{len(unknown)} runs without a recognisable topology")
    problems = [f"{r.experiment}/{r.task_dir}: {p}" for r in runs for p in r.problems]

    csv_rows = read_per_run_csv(source / PER_RUN_CSV_RELPATH)
    join = join_csv(runs, csv_rows)
    with (source / SELECTED_CSV_RELPATH).open(newline="", encoding="utf-8") as fh:
        selected_rows = list(csv.DictReader(fh))

    edges = log_bin_edges()
    iat, pooled, fit_checks = build_iat(runs, edges)
    table2 = parse_table2((source / TABLE2_RELPATH).read_text(encoding="utf-8"))
    rows_by_topo = {
        t: [r.csv_row for r in runs if r.topology == t and r.csv_row] for t in TOPOLOGIES
    }
    n_failed = {t: sum(r.n_disc_errors for r in runs if r.topology == t) for t in TOPOLOGIES}
    t2_checks = compare_table2(table2, recompute_table2(rows_by_topo, pooled), n_failed)
    n_runs = {t: sum(1 for r in runs if r.topology == t) for t in TOPOLOGIES}
    for key, ours in (("runs", n_runs), ("pooled_iats", {t: len(pooled[t]) for t in TOPOLOGIES})):
        t2_checks.append(
            {
                "metric": f"header: {key}",
                "published": [table2[key].get(t) for t in TOPOLOGIES],
                "ours": [ours[t] for t in TOPOLOGIES],
                "ok": all(table2[key].get(t) == ours[t] for t in TOPOLOGIES),
            }
        )
    correlations, rho_checks = build_correlations(runs, selected_rows)
    scaling, scaling_notes = build_scaling(source, edges)
    fixtures = build_fixture_map(runs, FIXTURE_INDEX)

    experiments = sorted({r.experiment for r in runs})
    summary: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "source": {
            "repository": SOURCE_REPO,
            "branch": SOURCE_BRANCH,
            "experiments": experiments,
            "n_runs": n_runs,
            "n_runs_total": len(runs),
            "files": {
                "table2": str(TABLE2_RELPATH),
                "per_run_metrics": str(PER_RUN_CSV_RELPATH),
                "selected_correlations": str(SELECTED_CSV_RELPATH),
                "scaling_runs": str(SCALING_JSONL_RELPATH) if scaling else None,
            },
            "join": join,
        },
        "topologies": [{"key": t, "label": TOPOLOGY_LABELS[t]} for t in TOPOLOGIES],
        "tasks": [
            {"key": CATEGORY_TO_TASK[c], "category": c, "label": TASK_LABELS[CATEGORY_TO_TASK[c]]}
            for c in CATEGORY_TO_TASK
        ],
        "table2": table2,
        "iat": {
            "definition": (
                "Discussion-stage inter-arrival times: per run, sorted start_time_utc of the LLM "
                "calls labelled horizontal_discussion / synthesize_discussion (Sequential), plus "
                "vertical_solver / vertical_reviewer (Star), full_mesh_message / "
                "synthesize_discussion (Full Mesh); consecutive differences pooled over runs "
                "(_compute_table2.collect_iats). Burst = IAT < 50 ms."
            ),
            "burst_threshold_s": BURST_THRESHOLD_S,
            "bins_s": edges,
            "linear_bins_s": LINEAR_EDGES,
            "bins_note": (
                f"{BINS_PER_DECADE} log-spaced bins per decade, edges 0.05 s * 10^(j/"
                f"{BINS_PER_DECADE}); counts[i] covers [bins_s[i], bins_s[i+1]); underflow / "
                "overflow count values outside; fit_counts bins the fit sample. linear_bins_s / "
                f"linear_counts / linear_fit_counts: the same on {LINEAR_BIN_S} s linear bins over "
                f"[0, {LINEAR_MAX_S:g}) s for the linear-scale view (linear_overflow: IATs beyond)."
            ),
            "per_topology": iat["per_topology"],
            "fit_scope": (
                "Paper Table 3 (tab:gof) pipeline, make_session_proxy_figures.py: pooled IATs > 0; "
                "3x IQR upper fence (Q3 + 3 IQR) for Sequential and Star; IAT > 50 ms "
                "(reasoning-phase mode); values above the 99th percentile of that sample dropped. "
                "Maximum likelihood with location 0. lognormal: mu, sigma of ln(IAT); "
                "exponential: lambda = 1/mean; weibull: shape, scale. ks: one-sample KS "
                "statistic; p_value: exact two-sided KS distribution (scipy.stats.kstest), not "
                "corrected for estimated parameters; aic = 2k - 2 log L."
            ),
            "fits": iat["fits"],
        },
        "metrics": build_metrics_catalogue(),
        "layers": list(LAYERS),
        "correlations": correlations,
        "aggregates": build_aggregates(runs),
        "quantile_grid": list(QUANTILE_GRID),
        "quantiles": build_quantiles(runs),
        "scaling": scaling,
        "fixtures": fixtures,
    }
    runs_doc = build_runs_doc(runs, fixtures)
    report = {
        "warnings": warnings + scaling_notes,
        "problems": problems,
        "join": join,
        "table2": t2_checks,
        "fits": fit_checks,
        "rho": rho_checks,
        "iat": iat,
        "scaling": scaling,
        "n_calls": sum(len(r.calls) for r in runs),
        "runs": runs,  # for the per-page analysis modules (run_analyses); not printed
    }
    return summary, runs_doc, report


def print_report(report: dict) -> int:
    """Print the cross-checks; return the number of failures."""
    failures = 0
    j = report["join"]
    print(
        f"\nJoin per_run_metrics.csv <-> responses: {j['matched_by_order']} by row order, "
        f"{j['matched_by_fingerprint']} by fingerprint, {j['unmatched_runs']} unmatched "
        f"({j['ambiguous_runs']} ambiguous), {j['unused_csv_rows']} unused CSV rows; "
        f"match rate {j['match_rate'] * 100:.2f}%"
    )
    failures += j["unmatched_runs"] > 0 or j["unused_csv_rows"] > 0
    if report["problems"]:
        failures += 1
        print(f"\n{len(report['problems'])} call-encoding problems, e.g. {report['problems'][:3]}")

    bad = [c for c in report["table2"] if not c["ok"]]
    print(
        f"\nTable 2 recomputed from the joined CSV + pooled IATs: {len(report['table2']) - len(bad)}"
        f"/{len(report['table2'])} rows identical to table2.md"
    )
    for c in bad:
        print(f"  DIFFERS {c['metric']}: published {c['published']} ours {c['ours']}")
    failures += len(bad)

    print("\nIAT fits (paper tab:gof scope) vs the paper")
    rows = []
    for c in report["fits"]:
        status = "ok" if c["ok"] else ("known" if c["known_deviation"] else "DIFFERS")
        failures += not c["ok"] and not c["known_deviation"]
        rows.append([TOPOLOGY_LABELS[c["topology"]], c["quantity"], c["ours"], c["paper"], status])
    print_table(["topology", "quantity", "ours", "paper", "result"], rows)
    for t, why in KNOWN_FIT_DEVIATIONS.items():
        print(f"  informational ({TOPOLOGY_LABELS[t]}, published as the paper's row): {why}")
    rows = []
    for t, f in report["iat"]["fits"].items():
        for fam in ("lognormal", "exponential", "weibull"):
            params = {k: v for k, v in f[fam].items() if k not in ("ks", "p_value", "aic")}
            rows.append(
                [
                    TOPOLOGY_LABELS[t],
                    fam,
                    f["n"],
                    ", ".join(f"{k}={_fmt_check_value(v)}" for k, v in params.items()),
                    f[fam]["ks"],
                    f"{f[fam]['p_value']:.3g}",
                    f[fam]["aic"],
                ]
            )
    print_table(["topology", "family", "n", "parameters", "KS", "p", "AIC"], rows)

    bad = [c for c in report["rho"] if not c["ok"]]
    print(
        f"\nSelected Spearman rho reproduced: {len(report['rho']) - len(bad)}/{len(report['rho'])}"
    )
    for c in report["rho"]:
        diff = abs(c["ours"] - c["paper"]) if c["ours"] is not None else math.nan
        print(
            f"  {c['x']} vs {c['y']}: ours {c['ours']:.12f} paper {c['paper']:.12f} "
            f"|diff| {diff:.1e} n={c['n']} {'ok' if c['ok'] else 'DIFFERS'}"
        )
    failures += len(bad)

    if report["scaling"]:
        print("\nFull-mesh scaling (discussion IATs)")
        rows = []
        for a in report["scaling"]["agents"]:
            mu_p, sg_p = PAPER_SCALING_LOGNORMAL.get(a["n_agents"], (None, None))
            ln = a["lognormal_reasoning"]
            rows.append(
                [
                    a["n_agents"],
                    a["n_runs"],
                    a["n"],
                    f"{a['median_s'] * 1000:.1f} ms",
                    f"{a['p95_s']:.2f} s",
                    f"{a['burst_fraction'] * 100:.1f}%",
                    f"{ln['mu']:.2f}/{ln['sigma']:.2f}",
                    f"{mu_p}/{sg_p}",
                    f"{a['means']['disc_n_requests']:.2f}",
                ]
            )
        print_table(
            ["agents", "runs", "IATs", "median", "p95", "burst", "LN mu/sigma", "figure", "calls"],
            rows,
        )
    for w in report["warnings"]:
        print(f"warning: {w}", file=sys.stderr)
    return failures


# Per-page analysis modules. scripts/demo/analysis_<name>.py may define
#   build(ctx) -> dict           written to <out>/<name>.json (aggregates only: it is published)
#   annotate_runs(runs_doc, ctx)  adds fields to runs.json in place (e.g. outlier flags)
# ctx = {"runs": [Run], "summary": summary dict, "source": Path}. A missing module is skipped.
ANALYSES = ("traffic", "load", "workflow", "outliers")


def run_analyses(runs: list[Run], summary: dict, runs_doc: dict, source: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    ctx = {"runs": runs, "summary": summary, "source": source}
    for name in ANALYSES:
        modname = f"scripts.demo.analysis_{name}"
        try:
            mod = importlib.import_module(modname)
        except ModuleNotFoundError as exc:
            if exc.name == modname:
                continue
            raise
        if hasattr(mod, "annotate_runs"):
            mod.annotate_runs(runs_doc, ctx)
        if hasattr(mod, "build"):
            payload = mod.build(ctx)
            texts[f"{name}.json"] = (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    return texts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, required=True, help="paper-branch checkout")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--no-check", action="store_true", help="write even if a cross-check fails")
    args = ap.parse_args(argv)

    try:
        summary, runs_doc, report = build_all(args.source)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    print(f"scanned {summary['source']['n_runs_total']} runs, {report['n_calls']} LLM calls")
    failures = print_report(report)

    extra = run_analyses(report["runs"], summary, runs_doc, args.source)
    texts = {
        "summary.json": dumps_summary(summary) + "\n",
        "runs.json": dumps_runs(runs_doc),
        **extra,
    }
    try:
        for name, text in texts.items():
            assert_no_leaks(text, name)
    except LeakError as exc:
        print(f"error: {exc}")
        return 3
    if failures and not args.no_check:
        print(f"\nerror: {failures} cross-check(s) failed; nothing written (use --no-check)")
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (args.out / name).write_text(text, encoding="utf-8")
        print(f"wrote {args.out / name} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    # Marks the directory as the real (private) data set: ui/common/js/data.js looks for it.
    manifest = {"mode": "private", "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
    (args.out / "manifest.json").write_text(_compact(manifest) + "\n", encoding="utf-8")
    print(f"wrote {args.out / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
