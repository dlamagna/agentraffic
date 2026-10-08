"""Outlier finder for the Run explorer.

Flags unusual runs in ``runs.json`` and says why, so the Run explorer can list them and open each
one in the drill-down. Hooked into ``export_results.run_analyses`` through ``annotate_runs``;
run on its own it rebuilds only ``runs.json``::

    python -m scripts.demo.analysis_outliers --source data/att-paper [--out ui/data/private]

Rules (thresholds are per topology, because the topologies differ by design: a "long" Full mesh
run is short for Star):

* ``long``: run time (first LLM call start to last call end) above the topology's far-out fence
  Q3 + 3 IQR (the same 3x IQR fence as the paper's fit pipeline).
* ``token_heavy``: prompt + completion tokens of all calls above the same kind of fence.
* ``slow_queue``: 95th percentile of the run's time to first token (``queue_wait_ms``, all calls)
  above the fence: the backend kept its calls waiting.
* ``output_cap``: at least one call stopped at the backend's output-token limit (6,144 completion
  tokens, in ``infra/docker-compose.yml``): a runaway generation, which also makes that call take
  60 to 95 s.
* ``retries``: the run needed all three iterations (two retries after a low evaluation score).
* ``goal_missed``: the final evaluation says the goal was not achieved.

Quartiles use linear interpolation (numpy's default). Output is deterministic: runs keep their
order, and the added fields depend only on runs.json's own content.

Added to runs.json: ``outliers`` (method, rules, per-topology thresholds and counts) at the top
level, and ``flags`` on each flagged run: ``[{"rule", "value", "reason"}, ...]`` in rule order.
Unflagged runs get no ``flags`` key.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path
from typing import Any

from scripts.demo.generate_fixtures import REPO_ROOT, TOPOLOGY_LABELS, percentile

DEFAULT_SOURCE = REPO_ROOT / "data" / "att-paper"
DEFAULT_OUT = REPO_ROOT / "ui" / "data" / "private"

# Topology names as the results pages write them ("Full mesh", not "Full Mesh").
LABELS = {t: v[0] + v[1:].lower() for t, v in TOPOLOGY_LABELS.items()}
FENCE_K = 3.0  # Q3 + 3 IQR: Tukey's far-out fence
OUTPUT_TOKEN_CAP = 6144  # the backend's output-token limit (infra/docker-compose.yml)
MAX_ITERATIONS = 3  # the AgentVerse loop's iteration limit in these experiments

# Call columns (runs.json call_fields order), checked against the document at run time.
_CALL_FIELDS = (
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

RULES: tuple[dict[str, str], ...] = (
    {
        "key": "long",
        "label": "Very long",
        "kind": "fence",
        "unit": "s",
        "description": "Run time (first call start to last call end) above Q3 + 3 IQR of its "
        "topology.",
    },
    {
        "key": "token_heavy",
        "label": "Token-heavy",
        "kind": "fence",
        "unit": "tokens",
        "description": "Prompt + completion tokens of all its LLM calls above Q3 + 3 IQR of its "
        "topology.",
    },
    {
        "key": "slow_queue",
        "label": "Slow to start",
        "kind": "fence",
        "unit": "s",
        "description": "95th percentile of its calls' time to first token (queueing + prefill) "
        "above Q3 + 3 IQR of its topology.",
    },
    {
        "key": "output_cap",
        "label": "Hit the output cap",
        "kind": "count",
        "unit": "calls",
        "description": "At least one call stopped at the backend's output-token limit: a runaway "
        "generation.",
    },
    {
        "key": "retries",
        "label": "Many retries",
        "kind": "count",
        "unit": "iterations",
        "description": f"Needed all {MAX_ITERATIONS} iterations: two retries after a low "
        "evaluation score.",
    },
    {
        "key": "goal_missed",
        "label": "Goal missed",
        "kind": "flag",
        "unit": "",
        "description": "The final evaluation says the goal was not achieved.",
    },
)
RULE_KEYS = tuple(r["key"] for r in RULES)
FENCE_RULES = tuple(r["key"] for r in RULES if r["kind"] == "fence")


# ---------------------------------------------------------------------------
# Per-run features
# ---------------------------------------------------------------------------


def _sig(x: float, digits: int = 5) -> float | int:
    y = float(f"{x:.{digits}g}")
    return int(y) if y.is_integer() else y


def run_features(run: dict, fields: tuple[str, ...] = _CALL_FIELDS) -> dict[str, Any]:
    """The values the rules look at, from one runs.json run entry."""
    col = {f: i for i, f in enumerate(fields)}
    calls = run.get("calls") or []
    i_start, i_dur = col["start_ms"], col["dur_ms"]
    i_pt, i_ct, i_qw = col["prompt_tokens"], col["completion_tokens"], col["queue_wait_ms"]
    ends = [c[i_start] + c[i_dur] for c in calls if c[i_start] is not None and c[i_dur] is not None]
    waits = [c[i_qw] for c in calls if c[i_qw] is not None]
    return {
        "long": max(ends) / 1000.0 if ends else None,
        "token_heavy": (sum((c[i_pt] or 0) + (c[i_ct] or 0) for c in calls) if calls else None),
        "slow_queue": percentile(waits, 95) / 1000.0 if waits else None,
        "output_cap": sum(1 for c in calls if (c[i_ct] or 0) >= OUTPUT_TOKEN_CAP),
        "retries": int(run.get("iterations") or 1),
        "goal_missed": run.get("goal_achieved") is False,
    }


def fence_stats(values: list[float]) -> dict[str, float] | None:
    """Median, quartiles and the far-out fence Q3 + 3 IQR (None without data)."""
    if not values:
        return None
    q1, med, q3 = (percentile(values, q) for q in (25, 50, 75))
    return {
        "median": _sig(med),
        "q1": _sig(q1),
        "q3": _sig(q3),
        "fence": _sig(q3 + FENCE_K * (q3 - q1)),
    }


# ---------------------------------------------------------------------------
# Reasons (British English, no em dashes; shown as is in the Run explorer)
# ---------------------------------------------------------------------------


def _fmt_s(x: float) -> str:
    if x < 1:
        return f"{x * 1000:.0f} ms"
    if x < 10:
        return f"{x:.2f} s"
    return f"{x:,.0f} s"


def _fmt_tokens(x: float) -> str:
    return f"{x / 1000:.1f}k" if x >= 1000 else f"{x:.0f}"


def _times(value: float, median: float) -> str:
    return f"{value / median:.1f}x the median" if median else "above the median"


def reason(rule: str, value: Any, stats: dict | None, topology: str) -> str:
    label = LABELS.get(topology, topology)
    if rule == "long":
        return (
            f"Ran for {_fmt_s(value)}, {_times(value, stats['median'])} of {label} runs "
            f"({_fmt_s(stats['median'])}; limit {_fmt_s(stats['fence'])})."
        )
    if rule == "token_heavy":
        return (
            f"Used {_fmt_tokens(value)} tokens, {_times(value, stats['median'])} of {label} runs "
            f"({_fmt_tokens(stats['median'])}; limit {_fmt_tokens(stats['fence'])})."
        )
    if rule == "slow_queue":
        return (
            f"Time to first token p95 of {_fmt_s(value)}, {_times(value, stats['median'])} of "
            f"{label} runs ({_fmt_s(stats['median'])}; limit {_fmt_s(stats['fence'])})."
        )
    if rule == "output_cap":
        calls = "call" if value == 1 else "calls"
        return (
            f"{value} {calls} stopped at the output-token limit (runaway generation)."
        )
    if rule == "retries":
        return f"Needed all {value} iterations (two retries after a low evaluation score)."
    if rule == "goal_missed":
        return "The final evaluation says the goal was not achieved."
    raise ValueError(f"unknown rule {rule!r}")


# ---------------------------------------------------------------------------
# The hook
# ---------------------------------------------------------------------------


def _is_flagged(rule: str, value: Any, stats: dict | None) -> bool:
    if value is None:
        return False
    if rule in FENCE_RULES:
        return stats is not None and value > stats["fence"]
    if rule == "output_cap":
        return value > 0
    if rule == "retries":
        return value >= MAX_ITERATIONS
    if rule == "goal_missed":
        return bool(value)
    raise ValueError(f"unknown rule {rule!r}")


def annotate_runs(runs_doc: dict, ctx: dict | None = None) -> dict:
    """Add outlier flags to runs_doc in place (see the module docstring); return the summary.

    ``ctx`` (export_results.run_analyses) is accepted but not needed: everything comes from
    runs_doc, so re-annotating an annotated document gives the same result.
    """
    fields = tuple(runs_doc.get("call_fields") or _CALL_FIELDS)
    missing = [f for f in _CALL_FIELDS if f not in fields]
    if missing:
        raise ValueError(f"runs.json call_fields lack {missing}")
    runs = runs_doc["runs"]
    feats = [run_features(r, fields) for r in runs]
    topologies = list(dict.fromkeys(r["topology"] for r in runs))
    order = [t for t in LABELS if t in topologies] + [t for t in topologies if t not in LABELS]

    thresholds: dict[str, dict[str, Any]] = {}
    for t in order:
        idx = [i for i, r in enumerate(runs) if r["topology"] == t]
        thresholds[t] = {
            rule: fence_stats([feats[i][rule] for i in idx if feats[i][rule] is not None])
            for rule in FENCE_RULES
        }
        thresholds[t]["output_cap"] = {"min_calls": 1, "cap_tokens": OUTPUT_TOKEN_CAP}
        thresholds[t]["retries"] = {"min_iterations": MAX_ITERATIONS}
        thresholds[t]["goal_missed"] = {"goal_achieved": False}

    counts = {t: {**{rule: 0 for rule in RULE_KEYS}, "any": 0, "runs": 0} for t in order}
    for run, f in zip(runs, feats):
        t = run["topology"]
        counts[t]["runs"] += 1
        flags = []
        for rule in RULE_KEYS:
            stats = thresholds[t].get(rule) if rule in FENCE_RULES else None
            value = f[rule]
            if _is_flagged(rule, value, stats):
                shown = _sig(value) if isinstance(value, float) else value
                flags.append(
                    {"rule": rule, "value": shown, "reason": reason(rule, value, stats, t)}
                )
                counts[t][rule] += 1
        run.pop("flags", None)
        if flags:
            run["flags"] = flags
            counts[t]["any"] += 1

    summary = {
        "generator": "scripts/demo/analysis_outliers.py",
        "method": (
            f"Per topology. Fence rules flag values above Q3 + {FENCE_K:g} IQR of the run's "
            "topology (quartiles by linear interpolation). output_cap: at least one call with "
            f"completion_tokens >= {OUTPUT_TOKEN_CAP} (the output-token limit). retries: iterations >= "
            f"{MAX_ITERATIONS}. goal_missed: goal_achieved is false. A run can carry several "
            "flags; unflagged runs have no flags key."
        ),
        "rules": [dict(r) for r in RULES],
        "thresholds": thresholds,
        "counts": counts,
        "n_flagged": sum(c["any"] for c in counts.values()),
    }
    runs_doc["outliers"] = summary
    return summary


# ---------------------------------------------------------------------------
# Command line: rebuild runs.json only
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    from scripts.demo import export_results as er

    ap = argparse.ArgumentParser(description="Rebuild runs.json with outlier flags.")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="paper-branch checkout")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--no-check", action="store_true", help="write even if a cross-check fails")
    args = ap.parse_args(argv)

    try:
        summary, runs_doc, report = er.build_all(args.source)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    with contextlib.redirect_stdout(io.StringIO()):
        failures = er.print_report(report)
    if failures and not args.no_check:
        print(f"error: {failures} export cross-check(s) failed; nothing written (use --no-check)")
        return 1

    result = annotate_runs(runs_doc, {"runs": report["runs"], "summary": summary})
    text = er.dumps_runs(runs_doc)
    try:
        er.assert_no_leaks(text, "runs.json")
    except er.LeakError as exc:
        print(f"error: {exc}")
        return 3

    labels = {r["key"]: r["label"] for r in RULES}
    print(f"flagged {result['n_flagged']} of {len(runs_doc['runs'])} runs")
    for t, c in result["counts"].items():
        parts = ", ".join(f"{labels[k]} {c[k]}" for k in RULE_KEYS)
        print(f"  {LABELS.get(t, t)}: {c['any']} of {c['runs']} ({parts})")
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "runs.json"
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
