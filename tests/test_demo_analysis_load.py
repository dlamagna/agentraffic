"""Tests for scripts/demo/analysis_load.py: stdlib only, synthetic inputs (CI has no data/)."""

import json
from pathlib import Path

import pytest

from scripts.demo import analysis_load as al
from scripts.demo import export_results as er
from tests.test_demo_export_results import T0, _req, build_source

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_SOURCE = REPO_ROOT / "data" / "att-paper"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_overlap_eps_removes_rounding_overlaps():
    # A ends at 2.004 s (rounded duration), B starts at 2.0: a fake 4 ms overlap.
    reqs = [
        _req("horizontal_discussion_r1", "decision", 0.0, 2.0),
        _req("horizontal_discussion_r1", "decision", 1.996, 2.0),
    ]
    calls = al.call_intervals(reqs)
    iv = [(c["start"], c["end"]) for c in calls]
    raw = [(c["start"], c["raw_end"]) for c in calls]
    assert al.true_peak(iv) == 1
    assert al.raw_peak(raw) == 2  # the paper's peak counts the rounding overlap
    assert calls[0]["end"] - calls[0]["start"] == pytest.approx(1.99)


def test_true_peak_counts_real_overlaps_and_ignores_zero_length():
    assert al.true_peak([(0, 3), (1, 4), (2, 5)]) == 3
    assert al.true_peak([(0, 1), (1, 2)]) == 1  # an end at t is processed before a start at t
    assert al.true_peak([(0, 0), (0, 0)]) == 0
    assert al.raw_peak([(0, 1), (1, 2)]) == 2  # paper order: starts before ends


def test_level_times_and_mean():
    window, times = al.level_times([(0, 2), (1, 3), (5, 6)])
    assert window == 6
    assert times == {1: 3.0, 2: 1.0, 0: 2.0}
    conc = al.run_concurrency(
        [
            _req("vertical_solver_iter1", "decision", 0.0, 1.01),
            _req("vertical_reviewer_a", "decision", 1.0, 2.01),
            _req("vertical_reviewer_b", "decision", 1.0, 2.01),
            _req("execute_planner", "execution", 0.0, 9.0),  # not a discussion call
        ]
    )
    assert conc["peak"] == 2
    assert conc["raw_peak"] == 3
    assert conc["window"] == pytest.approx(3.0)
    assert conc["mean"] == pytest.approx((1.0 * 1 + 2.0 * 2) / 3.0)


def test_inflight_at_start_includes_itself_and_same_instant_starts():
    iv = [(0, 4), (0, 4), (1, 2), (3, 3), (4, 5)]
    # (0,4) x2 see each other; (1,2) sees both; (3,3) is zero-length: 1 + 2 running; (4,5)
    # starts as the first two end.
    assert al.inflight_at_start(iv) == [2, 2, 3, 3, 1]


def test_build_concurrency_shares_and_peaks():
    rows = [
        {"mean": 1.0, "peak": 1, "raw_peak": 2, "window": 4.0, "times": {1: 3.0, 0: 1.0}},
        {"mean": 1.5, "peak": 2, "raw_peak": 2, "window": 4.0, "times": {1: 2.0, 2: 2.0}},
    ]
    out = al.build_concurrency({"horizontal": rows})
    h = out["horizontal"]
    assert h["true_peak"] == 2 and h["true_peak_runs"] == {"1": 1, "2": 1}
    assert h["time_share"] == [0.125, 0.625, 0.25, 0, 0, 0]
    assert h["mean"] == 1.25 and h["raw_peak_mean"] == 2
    assert "vertical" not in out


# ---------------------------------------------------------------------------
# build(ctx) on a synthetic source
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    src = tmp_path_factory.mktemp("src")
    build_source(src, n_per_topology=8)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(er, "FIXTURE_INDEX", src / "no-index.json")
        summary, _, report = er.build_all(src)
    ctx = {"runs": report["runs"], "summary": summary, "source": src}
    return ctx, al.build(ctx)


def test_build_shape_and_determinism(synthetic):
    ctx, out = synthetic
    assert out["overlap_eps_ms"] == al.OVERLAP_EPS_MS == 10
    assert set(out["concurrency"]) == set(er.TOPOLOGIES)
    assert out["n_runs"] == {t: 16 for t in er.TOPOLOGIES}
    # make_response: Sequential one call at a time, Star 1 solver then 3 reviewers together,
    # full mesh all 12 messages of a round overlapping (no worker cap in the synthetic runs)
    peaks = {t: out["concurrency"][t]["true_peak"] for t in er.TOPOLOGIES}
    assert peaks == {"horizontal": 1, "vertical": 3, "full_mesh": 12}
    for c in out["concurrency"].values():
        assert sum(c["time_share"]) == pytest.approx(1.0, abs=1e-3)
    cont = out["contention"]
    assert cont["levels"] == [1, 2, 3, 4, 5]
    assert all(len(v) == 5 for v in cont["per_topology"].values())
    first = cont["all"][0]
    assert first["inflight"] == 1 and first["calls"] >= al.MIN_BIN_CALLS
    # the synthetic responses have no latency_ms: duration_seconds is the fallback
    assert first["latency_s"]["median"] > 0
    assert set(cont["discussion"]) == set(er.TOPOLOGIES)
    comp = out["comparisons"]
    assert comp["pairs"] == [list(p) for p in al.PAIRS]
    keys = [m["key"] for m in comp["metrics"]]
    excluded = {e["key"] for e in comp["excluded"]}
    assert "llm_inflight_peak" in excluded and "iat_mean_s" in excluded
    assert not excluded & set(keys)
    pair = comp["metrics"][0]["pairs"][0]
    assert set(pair) == {"n", "median"} and len(pair["n"]) == len(pair["median"]) == 2
    assert set(comp) == {"pairs", "metrics", "excluded"}
    # serialisable without NaN, and identical on a second build
    text = al.dumps(out)
    assert text == al.dumps(al.build(ctx))
    er.assert_no_leaks(text, "load.json")


def test_output_has_no_per_call_points_or_ids(synthetic):
    ctx, out = synthetic
    text = al.dumps(out)
    for run in ctx["runs"]:
        assert run.task_id not in text and run.run_id not in text and run.task_dir not in text
    assert T0.isoformat()[:10] not in text  # no timestamps

    def longest_list(o):
        if isinstance(o, dict):
            return max((longest_list(v) for v in o.values()), default=0)
        if isinstance(o, list):
            return max([len(o)] + [longest_list(v) for v in o])
        return 0

    assert longest_list(out) <= len(er.METRICS)  # aggregates only, nothing per call or run


def test_main_writes_only_load_json(tmp_path, monkeypatch):
    src = tmp_path / "src"
    build_source(src)
    monkeypatch.setattr(er, "FIXTURE_INDEX", tmp_path / "no-index.json")
    out = tmp_path / "out"
    assert al.main(["--source", str(src), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["load.json"]
    doc = json.loads((out / "load.json").read_text(encoding="utf-8"))
    assert doc["generator"] == al.GENERATOR
    assert al.main(["--source", str(tmp_path / "missing"), "--out", str(out)]) == 2


def test_run_analyses_hook_picks_up_the_module(synthetic):
    ctx, out = synthetic
    texts = er.run_analyses(ctx["runs"], ctx["summary"], {"runs": []}, ctx["source"])
    assert json.loads(texts["load.json"]) == out


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="paper-branch checkout not present")
def test_real_data_true_peaks_and_means():
    summary, _, report = er.build_all(REAL_SOURCE)
    out = al.build({"runs": report["runs"], "summary": summary, "source": REAL_SOURCE})
    conc = out["concurrency"]
    assert {t: conc[t]["true_peak"] for t in er.TOPOLOGIES} == {
        "horizontal": 1,
        "vertical": 3,
        "full_mesh": 5,
    }
    # every run reaches the topology's peak; Table 2's inflated peak is reproduced without the rule
    assert all(len(conc[t]["true_peak_runs"]) == 1 for t in er.TOPOLOGIES)
    assert [conc[t]["raw_peak_mean"] for t in er.TOPOLOGIES] == pytest.approx(
        [1.99, 3.80, 6.03], abs=0.005
    )
    assert [conc[t]["mean"] for t in er.TOPOLOGIES] == pytest.approx([0.97, 1.62, 2.94], abs=0.01)
    disc = out["contention"]["discussion"]
    # Star's latency tail is long outputs, not contention: alone-rate p95 within 10% of real
    v = disc["vertical"]
    assert v["latency_p95_s"] == max(d["latency_p95_s"] for d in disc.values())
    assert v["latency_p95_alone_s"] > 0.9 * v["latency_p95_s"]
    assert v["completion_tokens_p95"] > 2 * disc["horizontal"]["completion_tokens_p95"]
