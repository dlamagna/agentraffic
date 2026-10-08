"""Tests for scripts/demo/analysis_traffic.py: stdlib only, synthetic runs (CI has no data/)."""

import importlib
import json
import math
import random
from pathlib import Path

import pytest

from scripts.demo import analysis_traffic as at
from scripts.demo import export_results as er
from scripts.demo.generate_fixtures import assert_no_leaks

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = REPO_ROOT / "data" / "att-paper"


def make_run(topology: str, iats: list[float], durations_ms: list[int] | None = None) -> er.Run:
    """A Run with discussion IATs and matching discussion calls (start_ms, dur_ms, stage=1)."""
    starts = [0.0]
    for gap in iats:
        starts.append(starts[-1] + gap)
    durations_ms = durations_ms or [1000] * len(starts)
    calls = [
        [round(t * 1000), d, 1, 0, -1, 1, None, None, None] for t, d in zip(starts, durations_ms)
    ]
    return er.Run(
        experiment="exp",
        task_dir="t",
        category="consulting",
        task_id="",
        topology=topology,
        structure_used=topology,
        disc_iats=iats,
        response_metrics={},
        n_disc_errors=0,
        calls=calls,
    )


# ---------------------------------------------------------------------------
# Bursts
# ---------------------------------------------------------------------------


def test_burst_groups_join_gaps_below_the_threshold():
    assert at.burst_groups([]) == []
    assert at.burst_groups([5.0, 0.001, 0.002, 4.0]) == [[0], [1, 2, 3], [4]]
    assert at.burst_groups([0.05]) == [[0], [1]]  # 50 ms is not a burst gap (< 50 ms is)
    assert at.burst_groups([0.049]) == [[0, 1]]


def test_run_bursts_on_off_and_merged_gaps():
    # star-like: solver, 9 s, three reviewers 1 ms apart, 8 s, solver
    b = at.run_bursts([9.0, 0.001, 0.001, 8.0])
    assert b["sizes"] == [1, 3, 1]
    assert b["on"] == [pytest.approx(0.002)]
    assert b["off"] == [9.0, 8.0]
    assert b["merged"] == [pytest.approx(9.0), pytest.approx(8.002)]  # merged gap = OFF + ON


def test_build_bursts_counts_and_shares():
    runs = [
        make_run("horizontal", [4.0, 5.0]),
        make_run("vertical", [9.0, 0.001, 0.001, 8.0]),
        make_run("full_mesh", [0.001, 0.001, 0.001, 0.001, 0.5, 0.4]),
    ]
    b = at.build_bursts(runs)
    assert b["horizontal"]["sizes"] == [[1, 3]]
    assert b["horizontal"]["calls_in_bursts"] == 0
    assert b["horizontal"]["on"] == {"n": 0}
    assert b["vertical"]["sizes"] == [[1, 2], [3, 1]]
    assert b["vertical"]["n_calls"] == 5
    assert b["vertical"]["calls_in_bursts"] == 0.6
    assert b["full_mesh"]["sizes"] == [[1, 2], [5, 1]]
    assert b["full_mesh"]["mean_size"] == pytest.approx(7 / 3, rel=1e-5)
    assert b["full_mesh"]["bursts_per_run"] == 1


def test_build_gaps_merges_bursts_and_bins_them():
    edges = er.log_bin_edges()
    runs = [make_run("vertical", [9.0, 0.001, 0.001, 8.0]), make_run("horizontal", [4.0])]
    runs.append(make_run("full_mesh", [0.2, 0.3]))
    g = at.build_gaps(runs, edges)
    v = g["vertical"]
    assert v["raw"]["n"] == 4 and v["merged"]["n"] == 2 and v["dropped_0p1"]["n"] == 2
    assert sum(v["counts"]) + v["underflow"] + v["overflow"] == 2
    assert v["merged"]["p50_s"] == pytest.approx(8.501, rel=1e-5)


# ---------------------------------------------------------------------------
# Subsampling robustness
# ---------------------------------------------------------------------------


def test_slow_mode_pool_fences_sequential_and_star_only():
    iats = [0.0, 0.01, 1.0, 1.1, 1.2, 1.3, 1.4, 100.0]
    # Q1 = 0.7525... fence well below 100 s: the outlier goes for Sequential / Star only
    assert 100.0 not in at.slow_mode_pool(iats, "horizontal")
    assert 100.0 not in at.slow_mode_pool(iats, "vertical")
    assert at.slow_mode_pool(iats, "full_mesh") == [1.0, 1.1, 1.2, 1.3, 1.4, 100.0]
    assert all(x > 0.05 for x in at.slow_mode_pool(iats, "horizontal"))


def test_build_robustness_is_the_papers_published_table():
    gen = random.Random(3)
    runs = [
        make_run(t, [math.exp(gen.gauss(0.5, 0.5)) for _ in range(120)])
        for t in ("horizontal", "vertical", "full_mesh")
    ]
    r = at.build_robustness(runs, ns=(50, 100, 200))
    assert r["draws"] == 500 and r["alpha"] == 0.05
    assert not {"seed", "paper_pct", "monte_carlo_se_at_50pct"} & set(r)
    for idx, t in enumerate(("horizontal", "vertical", "full_mesh")):
        cells = r["per_topology"][t]["cells"]
        assert set(cells) == {"50", "100", "200"}  # always the paper's grid, whatever the pool
        for n, cell in cells.items():
            assert set(cell) == set(at.FAMILIES)
            for fam, c in cell.items():
                assert c["source"] == "paper"
                assert set(c) == {"reject_rate", "source"}
                assert c["reject_rate"] == at.PAPER_KS_SUBSAMPLE[int(n)][fam][idx] / 100
    assert r["per_topology"]["vertical"]["n_runs"] == 1  # run counts describe the runs, unchanged
    assert r["per_topology"]["horizontal"]["cells"]["200"]["lognormal"]["reject_rate"] == 0.01
    assert r["per_topology"]["vertical"]["cells"]["200"]["lognormal"]["reject_rate"] == 0.5
    assert r["ks_critical"]["100"] == 0.136


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def fake_ctx() -> dict:
    gen = random.Random(11)
    runs = []
    for i in range(6):
        runs.append(make_run("horizontal", [4 + gen.random() for _ in range(8)]))
        star = []
        for _ in range(4):
            star += [8 + gen.random(), 0.0006, 0.0007]
        runs.append(make_run("vertical", star))
        mesh = [0.001] * 4 + [0.3 + gen.random() for _ in range(6)]
        runs.append(make_run("full_mesh", mesh, [500 + 10 * i] * (len(mesh) + 1)))
    fits = {}
    for t in ("horizontal", "vertical", "full_mesh"):
        pool = [x for r in runs if r.topology == t for x in r.disc_iats if x > 0.05]
        sample, scope = er.reasoning_phase_sample(pool, t)
        fits[t] = {"range_s": [sample[0], sample[-1]], **er.fit_all(sample)}
    summary = {"iat": {"bins_s": er.log_bin_edges(), "fits": fits}}
    return {"runs": runs, "summary": summary, "source": Path("/nonexistent")}


def test_build_is_deterministic_aggregate_json():
    ctx = fake_ctx()
    a = at.dumps(at.build(ctx))
    b = at.dumps(at.build(ctx))
    assert a == b
    assert_no_leaks(a, "traffic.json")
    doc = json.loads(a)
    assert set(doc) >= {"bursts", "gaps", "robustness", "playground", "n_runs"}
    pg = doc["playground"]["full_mesh"]
    assert len(pg["duration_quantiles_s"]) == at.N_DURATION_QUANTILES + 1
    assert pg["duration_quantiles_s"] == sorted(pg["duration_quantiles_s"])
    assert pg["calls_per_s"] > 0 and pg["model_mean_inflight"] > 0
    assert doc["playground"]["horizontal"]["measured_mean_inflight"] > 0


def test_export_hook_contract():
    # export_results.run_analyses imports scripts.demo.analysis_<name> and calls build(ctx)
    assert "traffic" in er.ANALYSES
    mod = importlib.import_module("scripts.demo.analysis_traffic")
    assert callable(mod.build) and not hasattr(mod, "annotate_runs")


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="needs the paper-branch checkout")
def test_real_data_burst_sizes():
    summary, _, report = er.build_all(REAL_SOURCE)
    b = at.build_bursts(report["runs"])
    assert b["horizontal"]["sizes"] == [[1, 7013]]  # one call at a time
    assert [k for k, _ in b["vertical"]["sizes"]] == [1, 3]  # solver alone, three reviewers
    assert max(k for k, _ in b["full_mesh"]["sizes"]) == 5  # MAX_PARALLEL_WORKERS
    # burst fraction (Table 2) = gaps inside bursts / all gaps
    for t, frac in (("vertical", 0.533), ("full_mesh", 0.382)):
        inside = sum((k - 1) * n for k, n in b[t]["sizes"])
        assert inside / summary["iat"]["per_topology"][t]["n"] == pytest.approx(frac, abs=5e-4)
