"""System page, "at the model server and on the network": aggregates for load.json.

Usage (writes only ``ui/data/private/load.json``)::

    python -m scripts.demo.analysis_load --source data/att-paper [--out ui/data/private]

Also called by ``export_results.run_analyses`` through ``build(ctx)``. Stdlib only and
deterministic. The output holds aggregates
only: no prompts, responses, task ids or per-call points.

Definitions
-----------
* **Call interval**: ``[start, start + duration_seconds - OVERLAP_EPS_MS]`` (never shorter than
  zero). ``duration_seconds`` was recorded rounded to 10 ms, so back-to-back calls appear to
  overlap by up to 5 ms; shortening each call by 10 ms removes those false overlaps (the same
  rule as ``concurrency()`` in ``ui/results/js/run-charts.js``). At equal times an end is processed
  before a start.
* **Concurrency** (discussion calls: labels in ``CORR_DISC_PREFIXES``, as Table 2): per run the
  time-weighted mean number of calls in flight over the discussion window (first start to last
  end), and the true peak. ``raw_peak_mean`` repeats the paper's peak without the 10 ms rule
  (Table 2's inflated 1.99 / 3.80 / 6.03). ``time_share[k]``: share of all discussion-window
  time with k calls in flight (last bin: 5 or more), pooled over runs.
* **Contention** (every LLM call of the run, all stages): for each call, the number of calls in
  flight when it started, itself included (calls already running plus any started at the same
  instant). Runs never overlapped in time on the backend (checked), so this is the whole load
  the server saw. Per bin: median and quartiles of server latency (``llm_meta.latency_ms``,
  falling back to ``duration_seconds``), queue wait (``llm_meta.queue_wait_s``, i.e. time to
  first token), completion tokens and latency per completion token.
* **Discussion latency** (Table 2 scope): pooled per-call quantiles per topology, and
  ``latency_p95_alone_s``: the p95 if every call had run at the median per-token time and queue
  wait of calls that ran alone (in-flight 1, all topologies). The gap to the real p95 is the
  part of the tail that contention can explain.
* **Topology comparisons** (per-run metrics of ``per_run_metrics.csv``): for each pair of
  topologies, the number of runs and the median of every metric (the page shows the medians and
  the change from Sequential). Duplicate and constant metrics are listed under ``excluded``.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable

from scripts.demo import export_results as er
from scripts.demo.generate_fixtures import (
    TOPOLOGIES,
    find_response_files,
    load_response,
    parse_ts,
)

OVERLAP_EPS_MS = 10
MAX_LEVEL = 5  # in-flight bins 1..5 (the worker pool size; nothing higher is observed)
MIN_BIN_CALLS = 30  # contention bins with fewer calls are left out (null)
PAIRS = (("vertical", "horizontal"), ("full_mesh", "horizontal"), ("full_mesh", "vertical"))
# Left out of the comparisons, with the reason shown on the page.
EXCLUDED_WHY = {
    "llm_inflight_peak": "not a reliable measure",
}

SCHEMA_VERSION = 1
GENERATOR = "scripts/demo/analysis_load.py"
DEFAULT_OUT = er.DEFAULT_OUT


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _r(x: float | None, digits: int = 4) -> float | int | None:
    """Rounded to `digits` significant digits; None for missing or non-finite."""
    if x is None or not math.isfinite(x):
        return None
    return er.sig(x, digits)


def quartiles(values: list[float]) -> dict:
    """p25 / median / p75 (linear interpolation, as numpy) of a non-empty list."""
    xs = sorted(values)
    return {
        "p25": _r(er.percentile(xs, 25)),
        "median": _r(er.percentile(xs, 50)),
        "p75": _r(er.percentile(xs, 75)),
    }


def is_discussion(label: Any) -> bool:
    return str(label or "").startswith(er.CORR_DISC_PREFIXES)


def call_intervals(requests: list[dict], discussion_only: bool = False) -> list[dict]:
    """Calls with a start and duration, as {start, end, latency_ms, queue_wait_s, completion
    tokens, discussion} in seconds; end = start + duration - OVERLAP_EPS_MS (>= start)."""
    eps = OVERLAP_EPS_MS / 1000.0
    out = []
    for req in requests:
        start = parse_ts(req.get("start_time_utc"))
        dur = req.get("duration_seconds")
        if start is None or dur is None:
            continue
        disc = is_discussion(req.get("label"))
        if discussion_only and not disc:
            continue
        meta = req.get("llm_meta") or {}
        latency_ms = meta.get("latency_ms")
        out.append(
            {
                "start": start,
                "end": max(start, start + float(dur) - eps),
                "raw_end": start + max(float(dur), 0.0),
                "latency_ms": float(latency_ms if latency_ms is not None else float(dur) * 1000),
                "queue_wait_s": meta.get("queue_wait_s"),
                "completion_tokens": meta.get("completion_tokens"),
                "discussion": disc,
            }
        )
    return out


def _events(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, int]]:
    ev = []
    for s, e in intervals:
        if e > s:
            ev += [(s, 1), (e, -1)]
    ev.sort()  # (t, -1) sorts before (t, +1): an end at t is processed before a start at t
    return ev


def true_peak(intervals: list[tuple[float, float]]) -> int:
    """Largest number of intervals in flight at once (zero-length intervals never count)."""
    cur = peak = 0
    for _, d in _events(intervals):
        cur += d
        peak = max(peak, cur)
    return peak


def raw_peak(intervals: list[tuple[float, float]]) -> int:
    """The paper's peak (correlate_structure_metrics): starts before ends at equal times."""
    clean = [(s, e) for s, e in intervals if e > s]
    ev = sorted(
        [(s, 1) for s, _ in clean] + [(e, -1) for _, e in clean], key=lambda t: (t[0], -t[1])
    )
    cur = peak = 0
    for _, d in ev:
        cur += d
        peak = max(peak, cur)
    return peak


def level_times(intervals: list[tuple[float, float]]) -> tuple[float, dict[int, float]]:
    """(window length, {k: time with k in flight}) over [first start, last end]."""
    clean = [(s, e) for s, e in intervals if e > s]
    if not clean:
        return 0.0, {}
    t0 = min(s for s, _ in clean)
    t1 = max(e for _, e in clean)
    times: dict[int, float] = {}
    cur, last = 0, t0
    for t, d in _events(clean):
        if t > last:
            times[cur] = times.get(cur, 0.0) + (t - last)
            last = t
        cur += d
    return t1 - t0, times


def inflight_at_start(intervals: list[tuple[float, float]]) -> list[int]:
    """For each interval: 1 + the other intervals in flight at its start (s_j <= s_i < e_j)."""
    starts = sorted(s for s, _ in intervals)
    ends = sorted(e for _, e in intervals)
    out = []
    for s, e in intervals:
        n = bisect.bisect_right(starts, s) - bisect.bisect_right(ends, s)
        out.append(n - (1 if e > s else 0) + 1)
    return out


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def run_concurrency(requests: list[dict]) -> dict | None:
    """Discussion-stage concurrency of one run: mean, true peak, raw peak, level times."""
    calls = call_intervals(requests, discussion_only=True)
    iv = [(c["start"], c["end"]) for c in calls]
    window, times = level_times(iv)
    if window <= 0:
        return None
    raw = [(c["start"], c["raw_end"]) for c in calls]  # without the 10 ms rule
    return {
        "mean": sum(k * t for k, t in times.items()) / window,
        "peak": true_peak(iv),
        "raw_peak": raw_peak(raw),
        "window": window,
        "times": times,
    }


def build_concurrency(per_run: dict[str, list[dict]]) -> dict:
    out = {}
    for topo in TOPOLOGIES:
        rows = per_run.get(topo, [])
        if not rows:
            continue
        total = sum(r["window"] for r in rows)
        pooled = [0.0] * (MAX_LEVEL + 1)  # last bin: MAX_LEVEL or more
        for r in rows:
            for k, t in r["times"].items():
                pooled[min(k, MAX_LEVEL)] += t
        share = [_r(t / total) for t in pooled]
        peaks: dict[str, int] = {}
        for r in rows:
            peaks[str(r["peak"])] = peaks.get(str(r["peak"]), 0) + 1
        means = [r["mean"] for r in rows]
        out[topo] = {
            "n_runs": len(rows),
            "mean": _r(statistics.fmean(means)),
            "mean_quartiles": quartiles(means),
            "true_peak": max(r["peak"] for r in rows),
            "true_peak_runs": dict(sorted(peaks.items(), key=lambda kv: int(kv[0]))),
            "raw_peak_mean": _r(statistics.fmean(r["raw_peak"] for r in rows)),
            "time_share": share,
        }
    return out


def _bin_stats(calls: list[dict]) -> dict:
    lat = [c["latency_ms"] / 1000 for c in calls]
    qw = [float(c["queue_wait_s"]) for c in calls if c["queue_wait_s"] is not None]
    tok = [float(c["completion_tokens"]) for c in calls if c["completion_tokens"] is not None]
    mspt = [c["latency_ms"] / c["completion_tokens"] for c in calls if c["completion_tokens"]]
    return {
        "calls": len(calls),
        "latency_s": quartiles(lat),
        "queue_wait_s": quartiles(qw) if qw else None,
        "completion_tokens": quartiles(tok) if tok else None,
        "ms_per_token": quartiles(mspt) if mspt else None,
    }


def contention_bins(calls: list[dict]) -> list[dict | None]:
    """Stats per in-flight level 1..MAX_LEVEL (last bin = MAX_LEVEL or more)."""
    by_level: dict[int, list[dict]] = {}
    for c in calls:
        by_level.setdefault(min(c["inflight"], MAX_LEVEL), []).append(c)
    out: list[dict | None] = []
    for k in range(1, MAX_LEVEL + 1):
        group = by_level.get(k, [])
        out.append({"inflight": k, **_bin_stats(group)} if len(group) >= MIN_BIN_CALLS else None)
    return out


def _p(values: list[float], q: float) -> float | None:
    return er.percentile(sorted(values), q) if values else None


def build_contention(calls_by_topo: dict[str, list[dict]]) -> dict:
    every = [c for t in TOPOLOGIES for c in calls_by_topo.get(t, [])]
    alone = [c for c in every if c["inflight"] == 1]
    alone_mspt = statistics.median(
        c["latency_ms"] / c["completion_tokens"] for c in alone if c["completion_tokens"]
    )
    alone_qw = statistics.median(
        float(c["queue_wait_s"]) for c in alone if c["queue_wait_s"] is not None
    )
    discussion = {}
    for topo in TOPOLOGIES:
        disc = [c for c in calls_by_topo.get(topo, []) if c["discussion"]]
        if not disc:
            continue
        lat = [c["latency_ms"] / 1000 for c in disc]
        tok = [float(c["completion_tokens"]) for c in disc if c["completion_tokens"] is not None]
        qw = [float(c["queue_wait_s"]) for c in disc if c["queue_wait_s"] is not None]
        mspt = [c["latency_ms"] / c["completion_tokens"] for c in disc if c["completion_tokens"]]
        what_if = [
            (alone_qw * 1000 + float(c["completion_tokens"]) * alone_mspt) / 1000
            for c in disc
            if c["completion_tokens"] is not None
        ]
        inflight = [c["inflight"] for c in disc]
        discussion[topo] = {
            "calls": len(disc),
            "latency_p50_s": _r(_p(lat, 50)),
            "latency_p95_s": _r(_p(lat, 95)),
            "completion_tokens_p50": _r(_p(tok, 50)),
            "completion_tokens_p95": _r(_p(tok, 95)),
            "ms_per_token_median": _r(_p(mspt, 50)),
            "queue_wait_p50_s": _r(_p(qw, 50)),
            "queue_wait_p95_s": _r(_p(qw, 95)),
            "inflight_mean": _r(statistics.fmean(inflight)),
            "latency_p95_alone_s": _r(_p(what_if, 95)),
        }
    return {
        "levels": list(range(1, MAX_LEVEL + 1)),
        "min_bin_calls": MIN_BIN_CALLS,
        "n_calls": {t: len(calls_by_topo.get(t, [])) for t in TOPOLOGIES},
        "per_topology": {t: contention_bins(calls_by_topo.get(t, [])) for t in TOPOLOGIES},
        "all": contention_bins(every),
        "alone": {
            "calls": len(alone),
            "ms_per_token": _r(alone_mspt),
            "queue_wait_s": _r(alone_qw),
        },
        "discussion": discussion,
    }


def _values(runs: list, key: str) -> list[float]:
    out = []
    for r in runs:
        v = (r.csv_row or {}).get(key)
        if v is not None and math.isfinite(v):
            out.append(float(v))
    return out


def comparison_metrics(runs: list) -> tuple[list[tuple], list[dict]]:
    """(metrics compared, [{key, label, why}] left out): duplicates, constants, EXCLUDED_WHY."""
    keep, dropped = [], []
    for m in er.METRICS:
        key, label = m[0], m[1]
        values = _values(runs, key)
        if key in er.DUPLICATE_OF:
            why = f"same values as {er.DUPLICATE_OF[key]}"
        elif key in EXCLUDED_WHY:
            why = EXCLUDED_WHY[key]
        elif len({er.sig(v, 5) for v in values}) <= 1:  # runs.json precision
            why = "the same value in every run"
        else:
            keep.append(m)
            continue
        dropped.append({"key": key, "label": label, "why": why})
    return keep, dropped


def build_comparisons(runs: list) -> dict:
    """Per metric and pair of topologies: the number of runs and the median of each side."""
    metrics, excluded = comparison_metrics(runs)
    rows = []
    for key, label, _, unit, layer, _ in metrics:
        by_topo = {t: [r for r in runs if r.topology == t] for t in TOPOLOGIES}
        pairs = []
        for ta, tb in PAIRS:
            a, b = _values(by_topo[ta], key), _values(by_topo[tb], key)
            pairs.append(
                {
                    "n": [len(a), len(b)],
                    "median": [_r(statistics.median(a)), _r(statistics.median(b))],
                }
            )
        rows.append({"key": key, "label": label, "unit": unit, "layer": layer, "pairs": pairs})
    return {
        "pairs": [list(p) for p in PAIRS],
        "metrics": rows,
        "excluded": excluded,
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build(ctx: dict) -> dict:
    """load.json for the System page (see the module docstring for every definition)."""
    runs = ctx["runs"]
    source = Path(ctx["source"])
    by_key = {(r.experiment, r.task_dir): r for r in runs}
    per_run: dict[str, list[dict]] = {}
    calls_by_topo: dict[str, list[dict]] = {}
    n_used = 0
    for experiment, task_dir, path in find_response_files(source):
        run = by_key.get((experiment, task_dir))
        if run is None or run.topology not in TOPOLOGIES:
            continue
        requests = load_response(path).get("llm_requests") or []
        conc = run_concurrency(requests)
        if conc is not None:
            per_run.setdefault(run.topology, []).append(conc)
        calls = call_intervals(requests)
        counts = inflight_at_start([(c["start"], c["end"]) for c in calls])
        for c, n in zip(calls, counts):
            c["inflight"] = n
        calls_by_topo.setdefault(run.topology, []).extend(calls)
        n_used += 1
    if not n_used:
        raise ValueError(f"no responses for the scanned runs under {source}")
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "overlap_eps_ms": OVERLAP_EPS_MS,
        "n_runs": {t: len(per_run.get(t, [])) for t in TOPOLOGIES},
        "concurrency": build_concurrency(per_run),
        "contention": build_contention(calls_by_topo),
        "comparisons": build_comparisons(runs),
    }


def dumps(payload: dict) -> str:
    """Same serialisation as export_results.run_analyses."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, default=er.REPO_ROOT / "data" / "att-paper")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    args = ap.parse_args(argv)
    try:
        summary, _, report = er.build_all(args.source)
        text = dumps(build({"runs": report["runs"], "summary": summary, "source": args.source}))
        er.assert_no_leaks(text, "load.json")
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    except er.LeakError as exc:
        print(f"error: {exc}")
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "load.json"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
