"""Tests for scripts/demo/export_results.py: stdlib only, synthetic inputs (CI has no data/)."""

import csv
import gzip
import json
import math
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.demo import export_results as er

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = REPO_ROOT / "data" / "att-paper"


# ---------------------------------------------------------------------------
# Spearman
# ---------------------------------------------------------------------------


def test_rankdata_averages_ties():
    assert er.rankdata([10, 20, 20, 5, 20]) == [2.0, 4.0, 4.0, 1.0, 4.0]
    assert er.rankdata([3.0, 3.0]) == [1.5, 1.5]
    assert er.rankdata([]) == []


def test_spearman_with_ties_matches_scipy():
    x = [1, 2, 2, 3, 5, 5, 5, 8]
    y = [2, 1, 4, 4, 3, 9, 9, 7]
    rho, n = er.spearman(x, y)
    assert n == 8
    assert rho == pytest.approx(0.6895607149652165, abs=1e-12)  # scipy.stats.spearmanr


def test_spearman_is_pairwise_complete_and_handles_degenerate_columns():
    rho, n = er.spearman([1, 2, None, 4, math.nan, 6], [1, 3, 2, 5, 4, 7])
    assert n == 4
    assert rho == pytest.approx(1.0)
    assert er.spearman([1, 1, 1], [1, 2, 3]) == (None, 3)  # constant column: undefined
    assert er.spearman([1], [2]) == (None, 1)
    assert er.spearman([1, 2, 3], [3, 2, 1])[0] == pytest.approx(-1.0)


def test_spearman_matrix_is_symmetric_with_unit_diagonal():
    cols = [[1, 2, 3, 4], [4, 3, 2, 1], [1, 3, 2, 4], [5, 5, 5, 5]]
    rho, npair = er.spearman_matrix(cols)
    assert [rho[i][i] for i in range(3)] == [1.0, 1.0, 1.0]
    assert rho[3][3] is None and rho[0][3] is None
    assert rho[0][1] == pytest.approx(-1.0)
    assert rho[0][2] == rho[2][0] == pytest.approx(0.8)
    assert npair[0][2] == 4


# ---------------------------------------------------------------------------
# KS distribution, statistic and fits
# ---------------------------------------------------------------------------

# scipy.stats.kstwo.sf(d, n), one case per branch of scipy's _kolmogn.
KSTWO_SF = [
    ((5, 0.3), 0.664),  # n <= 140, Durbin matrix
    ((20, 0.1), 0.976255094592155),
    ((20, 0.3), 0.04306706665851623),
    ((100, 0.15), 0.019839242125643017),  # n <= 140, n d^2 > 2.2 (Pomeranz region, exact)
    ((5, 0.6), 0.03008000000000001),  # d >= 0.5: 2 * smirnov
    ((500, 0.08), 0.0031305058199356268),  # n d^2 >= 2.2: 2 * smirnov
    ((6168, 0.027317), 0.00019713638679555955),  # the Sequential log-normal fit
    ((500, 0.03), 0.7473166700457021),  # Pelz-Good
    ((50000, 0.004), 0.3994316646755731),  # Pelz-Good, large n
    ((1000, 0.001), 1.0),  # Ruben-Gambino
    ((300, 0.002), 1.0),
    ((10, 0.05), 1.0),
]


@pytest.mark.parametrize("args,expected", KSTWO_SF)
def test_ks_pvalue_matches_scipy_kstwo(args, expected):
    n, d = args
    assert er.ks_pvalue(d, n) == pytest.approx(expected, rel=1e-9, abs=1e-15)


def test_ks_pvalue_edges():
    assert er.ks_pvalue(0.0, 10) == 1.0
    assert er.ks_pvalue(1.0, 10) == 0.0
    assert er.ks_pvalue(0.5, 10000) == 0.0  # n d^2 >= 370
    assert math.isnan(er.ks_pvalue(0.1, 0))
    assert er.ks_pvalue(0.999, 3) == pytest.approx(2 * (1 - 0.999) ** 3)


def test_smirnov_sf_matches_scipy():
    assert er.smirnov_sf(10, 0.3) == pytest.approx(0.1354635556, rel=1e-9)
    assert er.smirnov_sf(1000, 0.05) == pytest.approx(0.006506037390545166, rel=1e-9)
    assert er.smirnov_sf(10, 0.0) == 1.0 and er.smirnov_sf(10, 1.0) == 0.0


def test_ks_statistic_simple_cases():
    uniform = lambda x: min(max(x, 0.0), 1.0)  # noqa: E731
    assert er.ks_statistic([0.5], uniform) == pytest.approx(0.5)
    assert er.ks_statistic([0.1, 0.2, 0.3, 0.4], uniform) == pytest.approx(0.6)
    assert er.ks_statistic([0.125, 0.375, 0.625, 0.875], uniform) == pytest.approx(0.125)


SAMPLE = [0.5, 1.2, 0.8, 3.3, 2.2, 0.9, 1.7, 4.1, 0.3, 1.1]


def test_fits_match_scipy_mle():
    xs = sorted(SAMPLE)
    fits = er.fit_all(xs)
    ln, ex, wb = fits["lognormal"], fits["exponential"], fits["weibull"]
    # scipy.stats.lognorm.fit(xs, floc=0) -> (s, 0, scale)
    assert ln["sigma"] == pytest.approx(0.7721612758432229, rel=1e-7)
    assert ln["median_s"] == pytest.approx(1.2184752400291654, rel=1e-7)
    assert ln["mu"] == pytest.approx(math.log(1.2184752400291654), rel=1e-7)
    assert ln["ks"] == pytest.approx(0.1078933361308777, rel=1e-5)
    assert ln["p_value"] == pytest.approx(0.9987479810932305, rel=1e-5)
    assert ex["mean_s"] == pytest.approx(1.61) and ex["lambda"] == pytest.approx(1 / 1.61)
    assert ex["ks"] == pytest.approx(0.19158277676801466, rel=1e-5)
    assert ex["p_value"] == pytest.approx(0.7915587771068138, rel=1e-5)
    # scipy's Weibull optimiser stops ~1e-6 short of the MLE: compare loosely, check log L
    assert wb["shape"] == pytest.approx(1.4353620923621766, rel=1e-4)
    assert wb["scale_s"] == pytest.approx(1.7838215278276155, rel=1e-4)
    assert wb["aic"] == pytest.approx(2 * 2 + 2 * 13.83253500624407, abs=1e-5)
    assert ex["aic"] == pytest.approx(2 + 2 * (10 * math.log(1.61) + 10), rel=1e-7)


def test_weibull_recovers_exponential_shape():
    rng = random.Random(7)
    xs = [rng.expovariate(0.5) for _ in range(4000)]
    wb = er.fit_weibull(xs)
    assert wb["shape"] == pytest.approx(1.0, abs=0.05)
    assert wb["scale_s"] == pytest.approx(2.0, rel=0.05)


def test_reasoning_phase_sample_fence_threshold_and_clip():
    # 100 values: 40 bursts (< 50 ms incl. a 0 and a negative), 59 reasoning gaps, 1 outlier
    iats = [0.0, -0.001] + [0.001] * 38 + [1.0 + i / 10 for i in range(59)] + [1000.0]
    sample, scope = er.reasoning_phase_sample(iats, "horizontal")
    assert scope["n_positive"] == 98
    assert scope["fence_s"] is not None and 1000.0 > scope["fence_s"]
    assert scope["n_after_fence"] == 97
    assert scope["n_reasoning"] == 59
    assert sample == sorted(sample) and max(sample) <= scope["clip_s"]
    assert len(sample) == 59 - 1  # the top 1 % is clipped
    # Full mesh is never fenced
    _, mesh = er.reasoning_phase_sample(iats, "full_mesh")
    assert mesh["fence_s"] is None and mesh["n_reasoning"] == 60


# ---------------------------------------------------------------------------
# Log binning
# ---------------------------------------------------------------------------


def test_log_bin_edges_anchor_and_spacing():
    edges = er.log_bin_edges()
    lo, hi = er.BIN_J_RANGE
    assert len(edges) == hi - lo + 1
    assert er.BURST_THRESHOLD_S in edges  # 50 ms is an exact edge
    assert edges == sorted(edges)
    ratio = 10 ** (1 / er.BINS_PER_DECADE)
    for a, b in zip(edges, edges[1:]):
        assert b / a == pytest.approx(ratio, rel=1e-5)
    assert er.log_bin_edges(1.0, 1, (0, 2)) == [1, 10, 100]


def test_histogram_half_open_bins_and_out_of_range():
    edges = [1, 10, 100]
    h = er.histogram([0.5, 1, 9.99, 10, 99, 100, 250], edges)
    assert h == {"counts": [2, 2], "underflow": 1, "overflow": 2}
    edges = er.log_bin_edges()
    i50 = edges.index(er.BURST_THRESHOLD_S)
    h = er.histogram([0.0499, 0.05, 0.0501], edges)
    assert sum(h["counts"][:i50]) == 1  # bins below the threshold edge hold exactly the bursts


# ---------------------------------------------------------------------------
# Table 2
# ---------------------------------------------------------------------------

TABLE2_MD = """# Table 2 — Discussion-stage metrics by topology

Source: `exp_a` + `exp_b`
Runs: Sequential n=3, Star n=2, Full Mesh n=4
Pooled IATs (raw, unfiltered): Sequential n=30, Star n=20, Full Mesh n=40

> All metrics are **discussion-stage only** unless marked **[NOT disc-only]**.

| Metric | Sequential | Star | Full Mesh |
|--------|-----------|------|-----------|
| **Mean LLM req / rep** | 14.03 | 16.29 (+16%) | 29.99 (+114%) |
| **Failed discussion calls** | 0 | 0 | 0 |
| | | | |
| **Median IAT** | 4.56 s | 0.41 ms (-100%) | 236 ms (-95%) |
| | | | |
| **LLM TCP bytes / run** ¹ | 50.7k | 86.3k (+70%) | 38.6k (-24%) |
| **TCP flow dur p50** ² | 20.14 s | 24.36 s (+21%) | 26.32 s (+31%) | <!-- NOT discussion-only -->

---

**Footnotes**

¹ *LLM TCP bytes / run*: computed as `rate × duration`.

² *TCP flow duration p50/p95*: **[NOT discussion-only]** — spans the task.
"""


def test_parse_table2_sections_notes_and_footnotes():
    t = er.parse_table2(TABLE2_MD)
    assert t["title"].startswith("Table 2")
    assert t["source"] == "exp_a + exp_b"
    assert t["runs"] == {"horizontal": 3, "vertical": 2, "full_mesh": 4}
    assert t["pooled_iats"] == {"horizontal": 30, "vertical": 20, "full_mesh": 40}
    assert t["notes"] == ["All metrics are discussion-stage only unless marked [NOT disc-only]."]
    assert [len(s["rows"]) for s in t["sections"]] == [2, 1, 2]
    assert "title" not in t["sections"][0]  # titles only when there are exactly four sections
    first = t["sections"][0]["rows"][0]
    assert first == {
        "metric": "Mean LLM req / rep",
        "values": {"horizontal": "14.03", "vertical": "16.29 (+16%)", "full_mesh": "29.99 (+114%)"},
    }
    tcp_bytes, flow = t["sections"][2]["rows"]
    assert tcp_bytes["metric"] == "LLM TCP bytes / run" and tcp_bytes["footnote"] == "¹"
    assert flow["note"] == "NOT discussion-only" and flow["values"]["full_mesh"] == "26.32 s (+31%)"
    # the note on the TCP flow-duration rows is dropped, with the mark that pointed to it
    assert "footnote" not in flow
    assert [f["mark"] for f in t["footnotes"]] == ["¹"]
    assert t["footnotes"][0]["text"] == "LLM TCP bytes / run: computed as rate × duration."


def test_table2_formatting_matches_compute_table2():
    assert er._t2_fmt_s(4.5606) == "4.56 s"
    assert er._t2_fmt_s(0.000408888) == "0.41 ms"
    assert er._t2_fmt_s(0.236142) == "236 ms"
    assert er._t2_fmt_k(25512) == "25.5k" and er._t2_fmt_k(999) == "999"
    assert er._t2_rate(617.4) == "617 B/s" and er._t2_rate(1090) == "1.09 kB/s"
    assert er._t2_pct(0.207, 0.208) == "-0%"
    assert er._t2_pct(16.29, 14.03) == "+16%"
    assert er._t2_pct(1, 0) == "—"


# ---------------------------------------------------------------------------
# Synthetic responses
# ---------------------------------------------------------------------------

T0 = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
ROLES = ["planner", "researcher", "executor", "critic"]
CATEGORIES = list(er.CATEGORY_TO_TASK)


def _req(label, stage, start, dur, source="Agent A", role="orchestrator", **extra):
    meta = {"prompt_tokens": 100 + int(dur * 10), "completion_tokens": 50, "queue_wait_s": 0.12}
    return {
        "seq": 0,
        "iteration": extra.pop("iteration", 0),
        "stage": stage,
        "label": label,
        "source": source,
        "agent_role": role,
        "start_time_utc": (T0 + timedelta(seconds=start)).isoformat(),
        "duration_seconds": round(dur, 2),
        "error": False,
        "llm_meta": meta,
        **extra,
    }


def make_response(topology: str, seed: int) -> dict:
    """A small but structurally faithful response.json for one topology."""
    rng = random.Random(seed)
    t = 0.0
    reqs = [_req("expert_recruitment", "recruitment", t, 2.0)]
    t += 2.0
    for rnd in (1, 2):
        if topology == "horizontal":
            for i, role in enumerate(ROLES):
                d = rng.uniform(2, 6)
                reqs.append(
                    _req(
                        f"horizontal_discussion_round{rnd}",
                        "decision",
                        t,
                        d,
                        f"agent-b-{i + 1}",
                        role,
                        round=rnd,
                    )
                )
                t += d + 0.001
        elif topology == "vertical":
            d = rng.uniform(3, 8)
            reqs.append(
                _req(
                    f"vertical_solver_iter{rnd}",
                    "decision",
                    t,
                    d,
                    "agent-b-1",
                    "planner",
                    round=rnd,
                )
            )
            t += d + 0.001
            longest = 0.0
            for i, role in enumerate(ROLES[1:], start=1):
                d = rng.uniform(2, 9)
                longest = max(longest, d)
                reqs.append(
                    _req(
                        f"vertical_reviewer_{role}_iter{rnd}",
                        "decision",
                        t + i * 0.0004,
                        d,
                        f"agent-b-{i + 1}",
                        role,
                        round=rnd,
                    )
                )
            t += longest + 0.01
        else:
            longest = 0.0
            k = 0
            for s, sender in enumerate(ROLES):
                for r, receiver in enumerate(ROLES):
                    if s == r:
                        continue
                    d = rng.uniform(1, 4)
                    longest = max(longest, d)
                    reqs.append(
                        _req(
                            f"full_mesh_message_round{rnd}_agent{s + 1}_to_agent{r + 1}",
                            "decision",
                            t + k * 0.0003 + (0.7 if k >= 5 else 0),
                            d,
                            f"agent-b-{s + 1}",
                            sender,
                            round=rnd,
                            sender_role=sender,
                            receiver_role=receiver,
                        )
                    )
                    k += 1
            t += longest + 0.8
    if topology != "vertical":
        reqs.append(_req("synthesize_discussion", "decision", t, 3.0))
        t += 3.0
    reqs.append(_req("execute_planner", "execution", t, 4.0, "agent-b-1", "planner"))
    reqs.append(_req("execute_critic", "execution", t + 0.01, 5.0, "agent-b-4", "critic"))
    t += 5.1
    reqs.append(_req("evaluate_results", "evaluation", t, 2.0))
    reqs.append(_req("final_output", "synthesis", t + 2.1, 3.0))
    for i, r in enumerate(reqs, start=1):
        r["seq"] = i
    return {
        "task_id": "",
        "original_task": "||synthetic",
        "completed": True,
        "iterations": 1,
        "duration_seconds": t + 5.1,
        "stages": {
            "recruitment": {"experts": [{"role": r} for r in ROLES]},
            "decision": {
                "structure_used": topology,
                "discussion_rounds": [{"round": 1}, {"round": 2}],
                "consensus_reached": topology == "full_mesh",
                "solver_role": "planner" if topology == "vertical" else None,
            },
            "evaluation": {"score": 80 + seed % 20, "goal_achieved": True},
        },
        "iteration_history": [{"iteration": 0, "recruitment": {"experts": list(ROLES)}}],
        "llm_requests": reqs,
    }


def build_source(root: Path, n_per_topology: int = 4) -> list[tuple[str, str, dict]]:
    """A fake paper-branch checkout: responses, per_run_metrics.csv, selected CSV, table2.md."""
    runs = []
    seed = 0
    for e, exp in enumerate(
        [
            "balanced_agents4_experiment_2026-05-01_08-39-59",
            "balanced_agents4_experiment_2026-05-02_17-17-48",
        ]
    ):
        for k in range(n_per_topology * 3):
            topology = er.TOPOLOGIES[k % 3]
            category = CATEGORIES[k % 4]
            uid = str(uuid.UUID(int=random.Random(seed).getrandbits(128)))
            task_dir = f"2026-05-0{e + 1}_10-{k:02d}-00_{category}_{uid}"
            doc = make_response(topology, seed)
            doc["task_id"] = uid
            path = root / "data" / "agentverse" / exp / "tasks" / task_dir / "response.json.gz"
            path.parent.mkdir(parents=True)
            with gzip.open(path, "wt", encoding="utf-8") as fh:
                json.dump(doc, fh)
            runs.append((exp, task_dir, doc))
            seed += 1
    csv_path = root / er.PER_RUN_CSV_RELPATH
    csv_path.parent.mkdir(parents=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["structure", "task_slug", *er.METRIC_KEYS])
        for i, (_, task_dir, doc) in enumerate(runs):
            m = er.response_metrics(doc["llm_requests"])
            tcp = {
                k: 300.0 + 17 * i + j for j, k in enumerate(er.METRIC_KEYS) if k.startswith("tcp_")
            }
            values = [repr(m[k]) if k in m else repr(tcp[k]) for k in er.METRIC_KEYS]
            writer.writerow(
                [doc["stages"]["decision"]["structure_used"], task_dir.split("_")[2], *values]
            )
    with (root / er.SELECTED_CSV_RELPATH).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["relationship", "x_metric", "y_metric", "spearman_rho", "n"])
        writer.writerow(["calls vs bytes", "disc_n_requests", "tcp_bytes_llm_mean_Bps", "0.5", "1"])
    t2 = root / er.TABLE2_RELPATH
    t2.parent.mkdir(parents=True)
    t2.write_text(TABLE2_MD, encoding="utf-8")
    return runs


# ---------------------------------------------------------------------------
# Per-run extraction and call encoding
# ---------------------------------------------------------------------------


def test_response_metrics_follow_correlate_structure_metrics():
    reqs = [
        _req("expert_recruitment", "recruitment", 0, 1.0),
        _req("vertical_solver_iter1", "decision", 1.0, 2.0, "agent-b-1", "planner"),
        _req("vertical_reviewer_critic_iter1", "decision", 3.0, 4.0, "agent-b-2", "critic"),
        _req("vertical_reviewer_executor_iter1", "decision", 3.0, 2.0, "agent-b-3", "executor"),
        _req("evaluate_results", "evaluation", 9.0, 1.0),
    ]
    m = er.response_metrics(reqs)
    assert m["disc_n_requests"] == 3
    assert m["disc_duration_s"] == pytest.approx(2.0)
    assert m["disc_mean_iat_s"] == pytest.approx(1.0)
    assert m["disc_mean_latency_s"] == pytest.approx(8 / 3)
    # window [1, 7]: 1 call for 2 s, 2 calls for 2 s, 1 call for 2 s -> mean 4/3. Starts sort
    # before ends at the same instant (as in the paper), so the solver ending at 3.0 still
    # overlaps the reviewers starting at 3.0: peak 3.
    assert m["llm_inflight_mean"] == pytest.approx(8 / 6)
    assert m["llm_inflight_peak"] == 3
    assert m["iat_jitter_p50_mean_s"] == pytest.approx(1.0)
    assert m["burstiness_max"] == pytest.approx(2.0)
    assert m["burstiness_mean"] == pytest.approx(2.0)
    assert m["llm_ttft_p50_mean_s"] == m["llm_queue_wait_p50_mean_s"] == pytest.approx(0.12)
    tokens = sum(r["llm_meta"]["prompt_tokens"] for r in reqs[1:4])
    assert m["prompt_tokens_per_s_mean"] == pytest.approx(tokens / 2.0)
    few = er.response_metrics(reqs[:3])  # < 3 discussion calls: jitter undefined
    assert math.isnan(few["iat_jitter_p50_mean_s"]) and few["iat_mean_s"] == few["disc_mean_iat_s"]


def test_encode_calls_agents_and_peers_per_topology():
    stage = {code: i for i, code in enumerate(er.STAGE_CODES)}
    h = make_response("horizontal", 1)
    rows, problems = er.encode_calls(h["llm_requests"], "horizontal", lambda it: ROLES)
    assert problems == []
    assert rows[0][:5] == [0, 2000, stage["recruitment"], -1, -1]
    disc = [r for r in rows if r[2] == stage["discussion"]]
    assert [(r[3], r[4]) for r in disc[:4]] == [(0, -1), (1, 0), (2, 1), (3, 2)]
    assert {r[5] for r in disc} == {1, 2}
    assert [r[2] for r in rows].count(stage["discussion_synthesis"]) == 1
    assert rows[-1][2] == stage["final_output"] and rows[-1][5] is None
    assert len(rows[0]) == len(er.CALL_FIELDS)
    assert rows[0][6:] == [120, 50, 120]  # prompt, completion tokens, queue_wait_ms

    v = make_response("vertical", 2)
    rows, _ = er.encode_calls(v["llm_requests"], "vertical", lambda it: ROLES)
    disc = [r for r in rows if r[2] == stage["discussion"]]
    assert [(r[3], r[4]) for r in disc[:4]] == [(0, -1), (1, 0), (2, 0), (3, 0)]

    m = make_response("full_mesh", 3)
    rows, problems = er.encode_calls(m["llm_requests"], "full_mesh", lambda it: ROLES)
    disc = [r for r in rows if r[2] == stage["discussion"]]
    assert problems == [] and len(disc) == 24
    assert {(r[3], r[4]) for r in disc} == {(s, t) for s in range(4) for t in range(4) if s != t}
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)

    # A wrong roster is reported, not silently accepted
    _, problems = er.encode_calls(h["llm_requests"], "horizontal", lambda it: ROLES[::-1])
    assert problems


def test_encode_calls_rejects_unknown_stage():
    with pytest.raises(ValueError):
        er.encode_calls([_req("mystery", "elsewhere", 0, 1.0)], "horizontal")


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


def _runs_and_rows(tmp_path):
    build_source(tmp_path, n_per_topology=2)
    runs, warnings = er.scan_runs(tmp_path)
    rows = er.read_per_run_csv(tmp_path / er.PER_RUN_CSV_RELPATH)
    return runs, rows, warnings


def test_join_by_row_order(tmp_path):
    runs, rows, warnings = _runs_and_rows(tmp_path)
    assert warnings == []
    j = er.join_csv(runs, rows)
    assert j["matched_by_order"] == len(runs) == 12 and j["unmatched_runs"] == 0
    assert all(r.csv_row is rows[i] for i, r in enumerate(runs))


def test_join_recovers_shuffled_rows_by_fingerprint(tmp_path):
    runs, rows, _ = _runs_and_rows(tmp_path)
    rows[0], rows[5] = rows[5], rows[0]
    j = er.join_csv(runs, rows)
    assert j["matched_by_order"] == 10 and j["matched_by_fingerprint"] == 2
    assert runs[0].csv_row is rows[5] and runs[5].csv_row is rows[0]


def test_join_never_guesses(tmp_path):
    runs, rows, _ = _runs_and_rows(tmp_path)
    # One changed value: no row matches run 3 any more -> unmatched, its row stays unused
    rows[3] = {**rows[3], "disc_total_tokens": rows[3]["disc_total_tokens"] + 1}
    j = er.join_csv(runs, rows)
    assert runs[3].csv_row is None and runs[3].join_method is None
    assert j["unmatched_runs"] == 1 and j["unused_csv_rows"] == 1
    assert j["match_rate"] == pytest.approx(11 / 12, abs=1e-6)


def test_join_ambiguous_fingerprint_left_unmatched(tmp_path):
    runs, rows, _ = _runs_and_rows(tmp_path)
    # Run 0 gets no positional match, and two unused rows carry its fingerprint
    dup = dict(rows[0])
    rows[0] = {**rows[0], "structure": "nope"}
    rows.append(dup)
    rows.append(dict(dup))
    j = er.join_csv(runs, rows)
    assert runs[0].csv_row is None
    assert j["ambiguous_runs"] == 1 and j["unmatched_runs"] == 1


# ---------------------------------------------------------------------------
# End to end: determinism and output shape
# ---------------------------------------------------------------------------


def test_main_is_deterministic_and_writes_expected_shape(tmp_path, monkeypatch):
    src = tmp_path / "src"
    build_source(src)
    monkeypatch.setattr(er, "FIXTURE_INDEX", tmp_path / "no-index.json")
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    # Synthetic data cannot reproduce the paper's numbers: the checks fail, nothing is written
    assert er.main(["--source", str(src), "--out", str(out1)]) == 1
    assert not out1.exists()
    assert er.main(["--source", str(src), "--out", str(out1), "--no-check"]) == 0
    assert er.main(["--source", str(src), "--out", str(out2), "--no-check"]) == 0
    for name in ("summary.json", "runs.json"):
        assert (out1 / name).read_bytes() == (out2 / name).read_bytes()

    summary = json.loads((out1 / "summary.json").read_text(encoding="utf-8"))
    runs_doc = json.loads((out1 / "runs.json").read_text(encoding="utf-8"))
    assert summary["source"]["join"]["match_rate"] == 1.0
    assert summary["source"]["n_runs"] == {"horizontal": 8, "vertical": 8, "full_mesh": 8}
    assert [t["key"] for t in summary["topologies"]] == list(er.TOPOLOGIES)
    assert [t["key"] for t in summary["tasks"]] == list(er.TASKS)
    iat = summary["iat"]
    for t, v in iat["per_topology"].items():
        assert sum(v["counts"]) + v["underflow"] + v["overflow"] == v["n"]
        assert len(v["counts"]) == len(iat["bins_s"]) - 1
        assert set(iat["fits"][t]) >= {"lognormal", "exponential", "weibull", "n"}
    assert iat["per_topology"]["horizontal"]["n"] == 8 * 8  # 2 rounds x 4 agents + synthesis - 1
    assert iat["per_topology"]["horizontal"]["burst_fraction"] == 0
    assert iat["per_topology"]["full_mesh"]["burst_fraction"] > 0.5
    keys = [m["key"] for m in summary["metrics"]]
    assert keys == list(er.METRIC_KEYS) == summary["correlations"]["metric_keys"]
    layers = [m["layer"] for m in summary["metrics"]]
    assert layers == sorted(layers, key=er.LAYERS.index)  # grouped by layer
    rho = summary["correlations"]["groups"]["all"]["rho"]
    assert len(rho) == len(keys) and all(len(row) == len(keys) for row in rho)
    assert summary["correlations"]["groups"]["vertical"]["n"] == 8
    agg = summary["aggregates"]["by_topology_task"]["full_mesh"]["math"]["disc_n_requests"]
    assert set(agg) == {"median", "p25", "p75", "mean", "n"}
    assert summary["scaling"] is None and summary["fixtures"] == []
    grid = summary["quantile_grid"]
    assert grid[:4] == [0, 1, 5, 10] and grid[-3:] == [95, 99, 100] and grid == sorted(set(grid))
    assert list(summary["quantiles"]) == list(er.TOPOLOGIES)
    for t in er.TOPOLOGIES:
        assert list(summary["quantiles"][t]) == list(er.METRIC_KEYS)
        for table in summary["quantiles"][t].values():
            assert len(table) == len(grid)
            nums = [v for v in table if v is not None]
            assert nums == sorted(nums) and (len(nums) in (0, len(grid)))
    n_req = summary["quantiles"]["full_mesh"]["disc_n_requests"]
    agg_med = summary["aggregates"]["by_topology"]["full_mesh"]["disc_n_requests"]["median"]
    assert n_req[grid.index(50)] == agg_med
    assert json.loads((out1 / "manifest.json").read_text(encoding="utf-8"))["mode"] == "private"
    assert summary["table2"]["sections"][0]["rows"][0]["metric"] == "Mean LLM req / rep"

    assert runs_doc["metric_keys"] == keys
    assert runs_doc["call_fields"] == list(er.CALL_FIELDS)
    run = runs_doc["runs"][0]
    assert set(run) >= {
        "id",
        "topology",
        "task",
        "task_id",
        "experiment",
        "fixture",
        "metrics",
        "roles",
        "calls",
        "iterations",
        "score",
        "goal_achieved",
        "consensus_reached",
        "discussion_rounds",
    }
    assert run["discussion_rounds"] == 2 and run["roles"] == ROLES
    assert len(run["metrics"]) == len(keys)
    assert all(len(c) == len(er.CALL_FIELDS) for r in runs_doc["runs"] for c in r["calls"])
    assert len({r["id"] for r in runs_doc["runs"]}) == len(runs_doc["runs"])


def test_dumps_summary_inlines_scalar_lists():
    text = er.dumps_summary({"a": [1, 2.5, None], "b": {"c": [[1, 2], [3, 4]]}, "d": []})
    assert '"a": [1,2.5,null]' in text
    assert "[1,2]" in text and "[3,4]" in text
    assert json.loads(text) == {"a": [1, 2.5, None], "b": {"c": [[1, 2], [3, 4]]}, "d": []}


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="paper-branch checkout not present")
def test_real_data_reproduces_the_paper():
    summary, runs_doc, report = er.build_all(REAL_SOURCE)
    assert report["join"]["match_rate"] == 1.0
    assert all(c["ok"] for c in report["table2"])
    assert all(c["ok"] for c in report["rho"])
    assert all(c["ok"] or c["known_deviation"] for c in report["fits"])
    iat = summary["iat"]["per_topology"]
    assert [iat[t]["n"] for t in er.TOPOLOGIES] == [6513, 7355, 14493]
    fits = summary["iat"]["fits"]
    assert [fits[t]["n"] for t in er.TOPOLOGIES] == [6168, 3303, 8870]
    # Star carries the paper's row with provenance; the others stay computed
    assert fits["vertical"]["source"] == "paper"
    assert "source" not in fits["horizontal"] and "source" not in fits["full_mesh"]
    assert fits["vertical"]["lognormal"]["median_s"] == 9.70
    assert fits["vertical"]["lognormal"]["aic"] == 18377
    assert fits["vertical"]["sample"]["n"] == 3198  # recomputed from the published runs
    assert fits["vertical"]["best_aic"] == "lognormal"
    # run counts and per-run data are untouched
    per = summary["iat"]["per_topology"]
    assert [per[t]["n_runs"] for t in er.TOPOLOGIES] == [500, 481, 500]
    assert [per[t]["n"] for t in er.TOPOLOGIES] == [6513, 7355, 14493]
    assert len(runs_doc["runs"]) == 1481


def test_paper_fit_is_labelled_and_consistent():
    recomputed = {
        "range_s": [1, 30], "fence_s": 36.0, "clip_s": 32.0, "n": 3198,
        "fraction_of_iats": 0.43, "n_positive": 7355, "n_after_fence": 7149, "n_reasoning": 3231,
    }
    f = er.paper_fit("vertical", recomputed)
    g = er.PAPER_GOF["vertical"]
    assert f["source"] == "paper" and f["n"] == g["n"] == 3303
    assert abs(f["lognormal"]["mu"] - math.log(9.70)) < 1e-6
    assert abs(f["exponential"]["lambda"] - 1 / 10.55) < 1e-6
    assert f["weibull"]["shape"] == 2.38 and f["weibull"]["ks"] == 0.104
    assert 0 <= f["lognormal"]["p_value"] <= 1
    assert f["sample"]["source"] == "published_runs" and f["sample"]["n"] == 3198
