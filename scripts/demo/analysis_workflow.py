"""Inside-the-workflow analyses for the System page -> ``workflow.json``.

Usage::

    python -m scripts.demo.analysis_workflow --source data/att-paper [--out ui/data/private]

writes only ``<out>/workflow.json``. ``export_results.py`` also calls ``build(ctx)`` through its
``run_analyses`` hook and writes the same file.

Output: aggregates only (no prompts, responses, task ids or run ids), per topology, for all runs
(``groups.all``) and for each task (``groups.<task>``), so the page can follow the filter bar.

Definitions
-----------
* **Iteration** of a call: a run's calls sorted by start; every ``expert_recruitment`` call starts
  a new iteration (``final_output`` belongs to the last one). The expert roster of an iteration
  is ``roles_by_iteration`` (or ``roles``), so ``agent`` / ``peer`` map to role names.
* **Stage breakdown**: per stage (``export_results.STAGE_CODES``), the share of all calls, of all
  tokens (prompt + completion), of LLM time (sum of call durations) and of wall time. Wall time
  of a stage = per iteration, first start to last end of that stage's calls, summed; the shares
  are of the sum over stages (gaps between stages, i.e. orchestrator work outside LLM calls, are
  left out).
* **Execution parallelism**: per iteration, the execution calls' summed duration over their span
  (mean calls in flight), and the peak number in flight (overlaps under 10 ms ignored, as the
  recorded durations are rounded to 10 ms).
* **Roles**: every call by role (expert roles, plus ``orchestrator`` for Agent A's own calls);
  per-call prompt / completion tokens and latency (``duration_seconds``), calls per run and the
  role's share of all tokens. ``discussion`` = discussion-stage calls only.
* **Messages** (Full mesh only): ``full_mesh_message`` calls by sender role (the caller) and
  receiver role (``peer``); count and mean completion tokens (the length of the message).
* **Consensus**: one discussion per iteration, from ``iteration_history[].decision``
  (``rounds``, ``consensus``). The loop stops at the first round where every agent signals
  agreement (Star: every reviewer approves the solver's proposal), so a discussion that agreed
  did so in its last round. ``per_round``: discussions that reached round r and how many agreed
  in it.
* **Context growth**: prompt tokens per discussion call by ``round`` (Star: solver and reviewer
  calls apart, ``round`` = solver iteration).
* **Retries**: iterations per run; why an iteration was not accepted (``unscored``: the
  evaluator's reply had no usable score, recorded as 0 with no criteria; ``low_score``: scored
  below the acceptance threshold); cost per iteration (calls, tokens, seconds from its
  recruitment call to the end of its last call) for first iterations and for retries.
* **Quality vs cost**: the final evaluation (``stages.evaluation``); ``score`` statistics use
  scored runs only (unscored ones are counted apart); run length = first call start to last call
  end (including ``final_output``). ``rho``: Spearman correlation of score with each cost within
  the group, scored runs only. ``score_ci95``: mean +- 1.96 standard errors.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts.demo import export_results as er
from scripts.demo.generate_fixtures import (
    TASKS,
    TOPOLOGIES,
    LeakError,
    assert_no_leaks,
    find_response_files,
    load_response,
    percentile,
)

GENERATOR = "scripts/demo/analysis_workflow.py"
SCHEMA_VERSION = 1
OUT_NAME = "workflow.json"
STAGES = er.STAGE_CODES
S_RECRUIT, S_DISC, S_SYNTH, S_EXEC, S_EVAL, S_FINAL = range(len(STAGES))
ROLE_ORDER = ("planner", "researcher", "critic", "executor", "summarizer")
ORCHESTRATOR = "orchestrator"
OVERLAP_EPS_MS = 10  # recorded durations are rounded to 10 ms
CONTEXT_KINDS = {
    "horizontal": ("discussion",),
    "vertical": ("solver", "reviewer"),
    "full_mesh": ("message",),
}
SIG = 4

# call row columns (export_results.CALL_FIELDS)
_F = {name: i for i, name in enumerate(er.CALL_FIELDS)}
START, DUR, STAGE, AGENT, PEER, ROUND, PTOK, CTOK = (
    _F[k]
    for k in (
        "start_ms",
        "dur_ms",
        "stage",
        "agent",
        "peer",
        "round",
        "prompt_tokens",
        "completion_tokens",
    )
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _num(x: Any) -> float:
    return float(x) if er.is_num(x) else 0.0


def _sig(x: float | None) -> float | int | None:
    return er.sig(x, SIG) if x is not None else None


def describe(values: list[float]) -> dict:
    """median / p25 / p75 / mean / n at 4 significant digits."""
    vals = [v for v in values if er.is_num(v)]
    if not vals:
        return {"median": None, "p25": None, "p75": None, "mean": None, "n": 0}
    return {
        "median": _sig(statistics.median(vals)),
        "p25": _sig(percentile(vals, 25)),
        "p75": _sig(percentile(vals, 75)),
        "mean": _sig(er.fmean(vals)),
        "n": len(vals),
    }


def _mean(values: list[float]) -> float | None:
    return _sig(er.fmean(values)) if values else None


def _share(parts: list[float]) -> list[float | None]:
    total = math.fsum(parts)
    return [_sig(p / total) if total > 0 else None for p in parts]


def peak_in_flight(intervals: list[tuple[float, float]], eps: float = OVERLAP_EPS_MS) -> int:
    """Most intervals open at once; an overlap shorter than ``eps`` does not count."""
    clean = [(s, e - eps) for s, e in intervals if e - eps > s]
    if not clean:
        return 1 if intervals else 0
    events = sorted([(s, 1) for s, _ in clean] + [(e, -1) for _, e in clean])
    active = peak = 0
    for _, delta in events:  # ends sort before starts at the same time
        active += delta
        peak = max(peak, active)
    return peak


def iterations_of(calls: list[list]) -> list[int]:
    """Iteration index of each call (calls sorted by start; recruitment starts an iteration)."""
    out, it = [], -1
    for c in calls:
        if c[STAGE] == S_RECRUIT:
            it += 1
        out.append(max(it, 0))
    return out


def role_order(roles: set[str]) -> list[str]:
    known = [r for r in ROLE_ORDER if r in roles]
    return known + sorted(roles - set(ROLE_ORDER) - {ORCHESTRATOR})


# ---------------------------------------------------------------------------
# Per-run extraction (internal only; nothing per run is written)
# ---------------------------------------------------------------------------


@dataclass
class Iteration:
    """One iteration's discussion and evaluation (iteration_history)."""

    rounds: int | None
    consensus: bool | None
    score: float | None
    goal: bool | None
    unscored: bool


@dataclass
class RunStats:
    topology: str
    task: str
    n_calls: int = 0
    tokens: float = 0.0
    span_s: float = 0.0
    stage_calls: list[float] = field(default_factory=lambda: [0.0] * len(STAGES))
    stage_tokens: list[float] = field(default_factory=lambda: [0.0] * len(STAGES))
    stage_llm_s: list[float] = field(default_factory=lambda: [0.0] * len(STAGES))
    stage_wall_s: list[float] = field(default_factory=lambda: [0.0] * len(STAGES))
    exec_parallel: list[float] = field(default_factory=list)  # per iteration
    exec_peak: list[int] = field(default_factory=list)
    exec_calls: list[int] = field(default_factory=list)
    exec_span_s: list[float] = field(default_factory=list)
    role_calls: list[tuple[str, bool, float, float, float]] = field(default_factory=list)
    messages: list[tuple[str, str, float]] = field(default_factory=list)
    context: list[tuple[str, int, float, float]] = field(default_factory=list)
    iter_cost: list[tuple[int, float, float]] = field(default_factory=list)  # calls, tokens, s
    iterations: list[Iteration] = field(default_factory=list)
    score: float | None = None
    goal: bool | None = None
    unscored: bool = False


def _is_unscored(score: Any, criteria: Any) -> bool:
    return (score is None or score == 0) and not criteria


def read_history(doc: dict) -> list[Iteration]:
    """Whitelisted per-iteration fields of a response (no text)."""
    out = []
    for h in doc.get("iteration_history") or []:
        dec = h.get("decision") or {}
        ev = h.get("evaluation") or {}
        score = ev.get("score")
        rounds = dec.get("rounds")
        out.append(
            Iteration(
                rounds=int(rounds) if er.is_num(rounds) else None,
                consensus=dec.get("consensus") if isinstance(dec.get("consensus"), bool) else None,
                score=float(score) if er.is_num(score) else None,
                goal=ev.get("goal_achieved") if isinstance(ev.get("goal_achieved"), bool) else None,
                unscored=_is_unscored(score, ev.get("criteria")),
            )
        )
    return out


def load_histories(source: Path | None) -> dict[tuple[str, str], list[Iteration]]:
    """(experiment, task_dir) -> iterations, from the raw responses (empty if unavailable)."""
    if source is None or not Path(source).is_dir():
        return {}
    out = {}
    for experiment, task_dir, path in find_response_files(Path(source)):
        try:
            out[(experiment, task_dir)] = read_history(load_response(path))
        except (OSError, ValueError):
            continue
    return out


def run_stats(run: er.Run, history: list[Iteration] | None) -> RunStats:
    rs = RunStats(topology=run.topology, task=run.task)
    calls = run.calls
    its = iterations_of(calls)
    rosters = run.roles_by_iteration or []

    def roster(it: int) -> list[str]:
        return rosters[it] if it < len(rosters) else run.roles

    def role(agent: int, it: int) -> str:
        if agent < 0:
            return ORCHESTRATOR
        r = roster(it)
        return r[agent] if agent < len(r) else f"agent {agent + 1}"

    windows: dict[tuple[int, int], list[float]] = {}
    exec_iv: dict[int, list[tuple[float, float]]] = defaultdict(list)
    iter_win: dict[int, list[float]] = {}
    iter_calls: Counter = Counter()
    iter_tokens: Counter = Counter()
    t_first, t_last = math.inf, -math.inf
    for c, it in zip(calls, its):
        if c[START] is None:
            continue
        start = float(c[START])
        dur = _num(c[DUR])
        end = start + dur
        stage = c[STAGE]
        p, q = _num(c[PTOK]), _num(c[CTOK])
        tok = p + q
        rs.n_calls += 1
        rs.tokens += tok
        rs.stage_calls[stage] += 1
        rs.stage_tokens[stage] += tok
        rs.stage_llm_s[stage] += dur / 1000.0
        w = windows.setdefault((it, stage), [start, end])
        w[0], w[1] = min(w[0], start), max(w[1], end)
        t_first, t_last = min(t_first, start), max(t_last, end)
        if stage != S_FINAL:
            iw = iter_win.setdefault(it, [start, end])
            iw[0], iw[1] = min(iw[0], start), max(iw[1], end)
            iter_calls[it] += 1
            iter_tokens[it] += tok
        if stage == S_EXEC:
            exec_iv[it].append((start, end))
        who = role(c[AGENT], it)
        rs.role_calls.append((who, stage == S_DISC, p, q, dur / 1000.0))
        if stage == S_DISC:
            if run.topology == "full_mesh" and c[PEER] >= 0:
                rs.messages.append((who, role(c[PEER], it), q))
            if isinstance(c[ROUND], int):
                if run.topology == "vertical":
                    kind = "reviewer" if c[PEER] >= 0 else "solver"
                else:
                    kind = CONTEXT_KINDS[run.topology][0]
                rs.context.append((kind, c[ROUND], p, q))
    for (_, stage), (a, b) in windows.items():
        rs.stage_wall_s[stage] += (b - a) / 1000.0
    rs.span_s = (t_last - t_first) / 1000.0 if rs.n_calls else 0.0
    for it in sorted(exec_iv):
        iv = exec_iv[it]
        span = max(e for _, e in iv) - min(s for s, _ in iv)
        busy = math.fsum(e - s for s, e in iv)
        if span > 0:
            rs.exec_parallel.append(busy / span)
        rs.exec_peak.append(peak_in_flight(iv))
        rs.exec_calls.append(len(iv))
        rs.exec_span_s.append(span / 1000.0)
    for it in sorted(iter_win):
        a, b = iter_win[it]
        rs.iter_cost.append((iter_calls[it], iter_tokens[it], (b - a) / 1000.0))

    if history:
        rs.iterations = history
    else:  # final iteration only, from the Run
        rs.iterations = [
            Iteration(
                rounds=run.discussion_rounds,
                consensus=(
                    run.consensus_reached if isinstance(run.consensus_reached, bool) else None
                ),
                score=float(run.score) if er.is_num(run.score) else None,
                goal=run.goal_achieved if isinstance(run.goal_achieved, bool) else None,
                unscored=not er.is_num(run.score) or run.score == 0,
            )
        ]
    score = run.score
    rs.goal = run.goal_achieved if isinstance(run.goal_achieved, bool) else None
    rs.unscored = rs.iterations[-1].unscored
    rs.score = None if rs.unscored or not er.is_num(score) else float(score)
    return rs


# ---------------------------------------------------------------------------
# Aggregation per group (one topology, all tasks or one task)
# ---------------------------------------------------------------------------


def agg_stages(group: list[RunStats]) -> dict:
    n = len(group)

    def tot(attr: str) -> list[float]:
        return [math.fsum(getattr(r, attr)[i] for r in group) for i in range(len(STAGES))]

    calls, tokens, llm, wall = (
        tot(a) for a in ("stage_calls", "stage_tokens", "stage_llm_s", "stage_wall_s")
    )
    per_run = {
        "calls": [_sig(v / n) for v in calls],
        "tokens": [_sig(v / n) for v in tokens],
        "llm_time_s": [_sig(v / n) for v in llm],
        "wall_time_s": [_sig(v / n) for v in wall],
    }
    return {
        "share": {
            "calls": _share(calls),
            "tokens": _share(tokens),
            "llm_time": _share(llm),
            "wall_time": _share(wall),
        },
        "per_run": per_run,
    }


def agg_execution(group: list[RunStats]) -> dict:
    peaks = Counter(p for r in group for p in r.exec_peak)
    return {
        "stages": sum(len(r.exec_peak) for r in group),
        "calls": describe([c for r in group for c in r.exec_calls]),
        "parallelism": describe([v for r in group for v in r.exec_parallel]),
        "span_s": describe([v for r in group for v in r.exec_span_s]),
        "peak": {str(k): peaks[k] for k in sorted(peaks)},
    }


def agg_roles(group: list[RunStats], order: list[str]) -> dict:
    n = len(group)
    out = {}
    for scope in ("all", "discussion"):
        rows = [rc for r in group for rc in r.role_calls if scope == "all" or rc[1]]
        total = math.fsum(p + q for _, _, p, q, _ in rows)
        by_role: dict[str, list] = defaultdict(list)
        for rc in rows:
            by_role[rc[0]].append(rc)
        scope_out = {}
        for role in [*order, ORCHESTRATOR]:
            rc = by_role.get(role)
            if not rc:
                continue
            toks = math.fsum(p + q for _, _, p, q, _ in rc)
            scope_out[role] = {
                "calls_per_run": _sig(len(rc) / n),
                "token_share": _sig(toks / total) if total else None,
                "prompt_tokens": describe([x[2] for x in rc]),
                "completion_tokens": describe([x[3] for x in rc]),
                "latency_s": describe([x[4] for x in rc]),
            }
        out[scope] = scope_out
    return out


def agg_messages(group: list[RunStats], order: list[str]) -> dict | None:
    msgs = [m for r in group for m in r.messages]
    if not msgs:
        return None
    idx = {r: i for i, r in enumerate(order)}
    k = len(order)
    count = [[0] * k for _ in range(k)]
    toks: list[list[list[float]]] = [[[] for _ in range(k)] for _ in range(k)]
    for s, r, q in msgs:
        if s in idx and r in idx:
            count[idx[s]][idx[r]] += 1
            toks[idx[s]][idx[r]].append(q)
    return {
        "roles": order,
        "runs": len(group),
        "count": count,
        "completion_tokens_mean": [[_mean(c) for c in row] for row in toks],
        "per_run": _sig(len(msgs) / len(group)),
    }


def agg_consensus(group: list[RunStats]) -> dict:
    discs = [(i.rounds, i.consensus) for r in group for i in r.iterations if i.rounds]
    hist = Counter(rounds for rounds, _ in discs)
    max_r = max(hist) if hist else 0
    per_round = []
    for rnd in range(1, max_r + 1):
        reached = sum(1 for rounds, _ in discs if rounds >= rnd)
        agreed = sum(1 for rounds, ok in discs if rounds == rnd and ok)
        per_round.append(
            {
                "round": rnd,
                "reached": reached,
                "agreed": agreed,
                "rate": _sig(agreed / reached) if reached else None,
            }
        )
    agreed = sum(1 for _, ok in discs if ok)
    return {
        "discussions": len(discs),
        "agreed": agreed,
        "rate": _sig(agreed / len(discs)) if discs else None,
        "rounds": {str(k): hist[k] for k in sorted(hist)},
        "rounds_mean": _mean([float(rounds) for rounds, _ in discs]),
        "per_round": per_round,
    }


def agg_context(group: list[RunStats], topology: str) -> dict:
    out = {}
    for kind in CONTEXT_KINDS[topology]:
        by_round: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for r in group:
            for k, rnd, p, q in r.context:
                if k == kind:
                    by_round[rnd].append((p, q))
        out[kind] = [
            {
                "round": rnd,
                "prompt_tokens": describe([p for p, _ in by_round[rnd]]),
                "completion_tokens": describe([q for _, q in by_round[rnd]]),
            }
            for rnd in sorted(by_round)
        ]
    return out


def agg_retries(group: list[RunStats]) -> dict:
    n_iter = Counter(max(len(r.iter_cost), len(r.iterations), 1) for r in group)
    failed = [i for r in group for i in r.iterations if i.goal is False]
    first = [r.iter_cost[0] for r in group if r.iter_cost]
    retry = [c for r in group for c in r.iter_cost[1:]]

    def cost(rows: list[tuple[int, float, float]]) -> dict:
        return {
            "n": len(rows),
            "calls": _mean([float(c) for c, _, _ in rows]),
            "tokens": _mean([t for _, t, _ in rows]),
            "time_s": _mean([s for _, _, s in rows]),
        }

    by_iterations = {}
    for k in sorted(n_iter):
        rows = [r for r in group if max(len(r.iter_cost), len(r.iterations), 1) == k]
        by_iterations[str(k)] = {
            "n": len(rows),
            "calls": describe([float(r.n_calls) for r in rows]),
            "tokens": describe([r.tokens for r in rows]),
            "span_s": describe([r.span_s for r in rows]),
        }
    retried = [r for r in group if len(r.iterations) > 1]
    return {
        "runs": len(group),
        "iterations": {str(k): n_iter[k] for k in sorted(n_iter)},
        "not_accepted": {
            "iterations": len(failed),
            "unscored": sum(1 for i in failed if i.unscored),
            "low_score": sum(1 for i in failed if not i.unscored),
        },
        "never_accepted": sum(1 for r in group if r.goal is False),
        "cost": {"first": cost(first), "retry": cost(retry)},
        "by_iterations": by_iterations,
        "retried_final_score": describe([r.score for r in retried if r.score is not None]),
    }


def agg_quality(group: list[RunStats]) -> dict:
    scored = [r for r in group if r.score is not None]
    scores = [r.score for r in scored]
    ci = None
    if len(scores) >= 2:
        m = er.fmean(scores)
        se = statistics.stdev(scores) / math.sqrt(len(scores))
        ci = [_sig(m - 1.96 * se), _sig(m + 1.96 * se)]
    goals = [r.goal for r in group if r.goal is not None]
    dist = Counter(int(s) for s in scores)
    rho = {}
    for key, get in (
        ("tokens", lambda r: r.tokens),
        ("calls", lambda r: float(r.n_calls)),
        ("span_s", lambda r: r.span_s),
    ):
        value, n = er.spearman([get(r) for r in scored], scores)
        rho[key] = _sig(value) if value is not None else None
    return {
        "runs": len(group),
        "scored": len(scored),
        "unscored": sum(1 for r in group if r.unscored),
        "score": describe(scores),
        "score_ci95": ci,
        "score_counts": {str(k): dist[k] for k in sorted(dist)},
        "goal_rate": _sig(sum(goals) / len(goals)) if goals else None,
        "tokens": describe([r.tokens for r in group]),
        "calls": describe([float(r.n_calls) for r in group]),
        "span_s": describe([r.span_s for r in group]),
        "rho": rho,
    }


def aggregate(group: list[RunStats], topology: str, order: list[str]) -> dict:
    return {
        "runs": len(group),
        "stages": agg_stages(group),
        "execution": agg_execution(group),
        "roles": agg_roles(group, order),
        "messages": agg_messages(group, order) if topology == "full_mesh" else None,
        "consensus": agg_consensus(group),
        "context": agg_context(group, topology),
        "retries": agg_retries(group),
        "quality": agg_quality(group),
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build(ctx: dict) -> dict:
    """The run_analyses hook: ctx = {"runs": [Run], "summary": dict, "source": Path}."""
    runs = [r for r in ctx["runs"] if r.topology in TOPOLOGIES]
    histories = load_histories(ctx.get("source"))
    stats = [run_stats(r, histories.get((r.experiment, r.task_dir))) for r in runs]
    roles = {rc[0] for s in stats for rc in s.role_calls}
    order = role_order(roles)
    groups: dict[str, dict] = {}
    for gkey in ("all", *TASKS):
        groups[gkey] = {}
        for t in TOPOLOGIES:
            group = [s for s in stats if s.topology == t and (gkey == "all" or s.task == gkey)]
            groups[gkey][t] = aggregate(group, t, order) if group else None
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "source": {
            "runs": len(stats),
            "iteration_history": sum(1 for r in runs if (r.experiment, r.task_dir) in histories),
        },
        "notes": [" ".join(b.split()) for b in __doc__.split("Definitions")[1].split("\n* ")[1:]],
        "topologies": list(TOPOLOGIES),
        "tasks": list(TASKS),
        "stages": list(STAGES),
        "roles": order,
        "context_kinds": {t: list(k) for t, k in CONTEXT_KINDS.items()},
        "groups": groups,
    }


def dumps(payload: dict) -> str:
    """The same bytes export_results.run_analyses writes."""
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
    text = dumps(build({"runs": report["runs"], "summary": summary, "source": args.source}))
    try:
        assert_no_leaks(text, OUT_NAME)
    except LeakError as exc:
        print(f"error: {exc}")
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / OUT_NAME
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
