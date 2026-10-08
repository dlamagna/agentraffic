"""Tests for scripts/demo/analysis_outliers.py: stdlib only, synthetic runs.json (CI has no data/)."""

import copy
import importlib
import json
from pathlib import Path

import pytest

from scripts.demo import analysis_outliers as ao
from scripts.demo import export_results as er

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_RUNS = REPO_ROOT / "ui" / "data" / "private" / "runs.json"


def call(start, dur, prompt=100, completion=100, wait=50.0, stage=1):
    return [start, dur, stage, 0, -1, 1, prompt, completion, wait]


def run(rid, topology, *, length_s=100, tokens=1000, wait=50.0, iterations=1, goal=True, cap=0):
    """A run with two calls: its run time, total tokens and TTFT are set directly."""
    half = tokens // 2
    calls = [
        call(0, 1000, half // 2, half - half // 2, wait),
        call(length_s * 1000 - 1000, 1000, half // 2, half - half // 2, wait),
    ]
    for i in range(cap):
        calls.append(call(2000 + i, 500, 10, ao.OUTPUT_TOKEN_CAP, wait))
    calls.sort(key=lambda c: c[0])
    return {
        "id": rid,
        "topology": topology,
        "iterations": iterations,
        "goal_achieved": goal,
        "calls": calls,
    }


def doc(runs):
    return {"call_fields": list(er.CALL_FIELDS), "notes": [], "runs": runs}


def base_runs(topology="horizontal", n=20):
    # run time 100..119 s, tokens 1000..1190, TTFT 50..69 ms: quartiles are easy to check
    return [
        run(f"{topology[:1]}{i:03d}", topology, length_s=100 + i, tokens=1000 + 10 * i, wait=50 + i)
        for i in range(n)
    ]


def flags_of(d, rid):
    r = next(r for r in d["runs"] if r["id"] == rid)
    return [f["rule"] for f in r.get("flags", [])]


def test_call_fields_match_the_export():
    assert tuple(er.CALL_FIELDS) == ao._CALL_FIELDS


def test_fence_stats_uses_q3_plus_three_iqr():
    st = ao.fence_stats([float(x) for x in range(1, 102)])  # 1..101
    assert st == {"median": 51, "q1": 26, "q3": 76, "fence": 226}
    assert ao.fence_stats([]) is None


def test_run_features():
    r = run("x", "vertical", length_s=50, tokens=4000, wait=80.0, iterations=3, goal=False, cap=2)
    f = ao.run_features(r)
    assert f["long"] == 50.0
    assert f["token_heavy"] == 4000 + 2 * (10 + ao.OUTPUT_TOKEN_CAP)
    assert f["slow_queue"] == pytest.approx(0.080)
    assert f["output_cap"] == 2
    assert f["retries"] == 3
    assert f["goal_missed"] is True


def test_typical_runs_are_not_flagged():
    d = doc(base_runs())
    summary = ao.annotate_runs(d)
    assert summary["n_flagged"] == 0
    assert all("flags" not in r for r in d["runs"])
    assert summary["counts"]["horizontal"]["runs"] == 20


def test_each_rule_fires_with_a_reason():
    runs = base_runs()
    runs += [
        run("long", "horizontal", length_s=1000),
        run("heavy", "horizontal", tokens=20_000),
        run("queue", "horizontal", wait=5000.0),
        run("capped", "horizontal", cap=1),
        run("retry", "horizontal", iterations=3),
        run("retry2", "horizontal", iterations=2),
        run("failed", "horizontal", goal=False),
    ]
    d = doc(runs)
    summary = ao.annotate_runs(d)
    assert flags_of(d, "long") == ["long"]
    assert flags_of(d, "heavy") == ["token_heavy"]
    assert flags_of(d, "queue") == ["slow_queue"]
    assert flags_of(d, "capped") == ["token_heavy", "output_cap"]  # 6,144 extra tokens
    assert flags_of(d, "retry") == ["retries"]
    assert flags_of(d, "retry2") == []  # one retry is common, not an outlier
    assert flags_of(d, "failed") == ["goal_missed"]
    c = summary["counts"]["horizontal"]
    assert c["any"] == 6 and c["long"] == 1 and c["retries"] == 1
    long_flag = next(r for r in d["runs"] if r["id"] == "long")["flags"][0]
    assert long_flag["value"] == 1000
    assert "Sequential" in long_flag["reason"] and "limit" in long_flag["reason"]
    reasons = [f["reason"] for r in d["runs"] for f in r.get("flags", [])]
    assert all("—" not in t and "–" not in t for t in reasons)  # no em / en dashes


def test_thresholds_are_per_topology():
    # A Star run as long as a typical Full mesh run x 5 is normal for Star but not for Full mesh.
    star = [run(f"s{i}", "vertical", length_s=500 + i) for i in range(20)]
    mesh = [run(f"m{i}", "full_mesh", length_s=50 + i) for i in range(20)]
    mesh.append(run("mlong", "full_mesh", length_s=300))
    d = doc(star + mesh)
    summary = ao.annotate_runs(d)
    assert flags_of(d, "mlong") == ["long"]
    assert all(flags_of(d, r["id"]) == [] for r in star)
    assert list(summary["thresholds"]) == ["vertical", "full_mesh"]  # first-seen order
    assert summary["thresholds"]["vertical"]["long"]["fence"] > 300


def test_annotate_is_idempotent_and_deterministic():
    runs = base_runs() + [run("long", "horizontal", length_s=1000)]
    d1 = doc(copy.deepcopy(runs))
    ao.annotate_runs(d1)
    once = er.dumps_runs(d1)
    ao.annotate_runs(d1)
    assert er.dumps_runs(d1) == once
    d2 = doc(copy.deepcopy(runs))
    ao.annotate_runs(d2, {"runs": [], "summary": {}})
    assert er.dumps_runs(d2) == once
    # stale flags from an earlier pass are removed
    d1["runs"][0]["flags"] = [{"rule": "long", "value": 1, "reason": "stale"}]
    ao.annotate_runs(d1)
    assert er.dumps_runs(d1) == once


def test_missing_call_fields_are_an_error():
    d = doc(base_runs())
    d["call_fields"] = ["start_ms", "dur_ms"]
    with pytest.raises(ValueError):
        ao.annotate_runs(d)


def test_export_hook_finds_the_module():
    # run_analyses imports scripts.demo.analysis_<name> and calls annotate_runs / build.
    assert "outliers" in er.ANALYSES
    mod = importlib.import_module("scripts.demo.analysis_outliers")
    assert hasattr(mod, "annotate_runs")
    assert not hasattr(mod, "build")  # annotate only: nothing extra is published
    d = doc(base_runs() + [run("long", "horizontal", length_s=1000)])
    mod.annotate_runs(d, {"runs": [], "summary": {}, "source": Path(".")})
    assert flags_of(d, "long") == ["long"]
    er.assert_no_leaks(er.dumps_runs(d), "runs.json")


@pytest.mark.skipif(not REAL_RUNS.is_file(), reason="no local runs.json")
def test_real_runs_json_is_annotated_consistently():
    d = json.loads(REAL_RUNS.read_text(encoding="utf-8"))
    if "outliers" not in d:
        pytest.skip("runs.json predates the outlier finder")
    stored = d["outliers"]
    flagged = {r["id"]: r["flags"] for r in d["runs"] if "flags" in r}
    assert stored["n_flagged"] == len(flagged)
    fresh = copy.deepcopy(d)
    ao.annotate_runs(fresh)
    assert fresh["outliers"] == stored
    assert {r["id"]: r["flags"] for r in fresh["runs"] if "flags" in r} == flagged
