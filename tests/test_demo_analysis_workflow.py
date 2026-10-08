"""Tests for scripts/demo/analysis_workflow.py: stdlib only, synthetic inputs (CI has no data/)."""

import gzip
import json
import math
from pathlib import Path

import pytest

from scripts.demo import analysis_workflow as wf
from scripts.demo import export_results as er
from scripts.demo.generate_fixtures import assert_no_leaks
from tests.test_demo_export_results import build_source

REAL_SOURCE = Path(__file__).resolve().parents[1] / "data" / "att-paper"
FORBIDDEN = {"task_id", "run_id", "id", "prompt", "response", "final_output", "original_task"}


def _keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _source(root: Path) -> None:
    """build_source plus per-iteration decisions and evaluations in iteration_history."""
    build_source(root)
    for i, path in enumerate(sorted(root.glob("data/agentverse/*/tasks/*/response.json.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            doc = json.load(fh)
        consensus = i % 2 == 0
        doc["iteration_history"][0]["decision"] = {"rounds": 2, "consensus": consensus}
        doc["iteration_history"][0]["evaluation"] = {
            "score": doc["stages"]["evaluation"]["score"],
            "goal_achieved": True,
            "criteria": {"completeness": 90},
        }
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)


def _ctx(src: Path) -> dict:
    runs, _ = er.scan_runs(src)
    return {"runs": runs, "summary": {}, "source": src}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_peak_in_flight_ignores_overlaps_under_10_ms():
    assert wf.peak_in_flight([]) == 0
    assert wf.peak_in_flight([(0, 100)]) == 1
    assert wf.peak_in_flight([(0, 100), (95, 200)]) == 1  # 5 ms overlap: rounding, not real
    assert wf.peak_in_flight([(0, 100), (50, 200)]) == 2
    assert wf.peak_in_flight([(0, 100), (0, 100), (0, 100), (200, 300)]) == 3
    assert wf.peak_in_flight([(0, 100), (100, 200)]) == 1  # back to back


def test_iterations_follow_recruitment_calls():
    def row(stage):
        return [0, 10, stage, -1, -1, None, 1, 1, 0]

    stages = [0, 1, 1, 3, 4, 0, 1, 3, 4, 5]
    assert wf.iterations_of([row(s) for s in stages]) == [0, 0, 0, 0, 0, 1, 1, 1, 1, 1]
    assert wf.iterations_of([row(1), row(0), row(1)]) == [0, 0, 0]


def test_role_order_known_roles_first():
    assert wf.role_order({"critic", "planner", "zeta", "orchestrator", "alpha"}) == [
        "planner",
        "critic",
        "alpha",
        "zeta",
    ]


def test_read_history_marks_unparsed_evaluations():
    doc = {
        "iteration_history": [
            {"decision": {"rounds": 3, "consensus": False}, "evaluation": {"score": 0}},
            {
                "decision": {"rounds": 3, "consensus": False},
                "evaluation": {"score": 0, "criteria": {"completeness": 0}, "goal_achieved": False},
            },
            {"decision": {"rounds": 1, "consensus": True}, "evaluation": {"score": 92}},
        ]
    }
    its = wf.read_history(doc)
    assert [i.unscored for i in its] == [True, False, False]
    assert [i.rounds for i in its] == [3, 3, 1]
    assert its[2].consensus is True and its[1].goal is False


def test_consensus_per_round_counts_discussions_that_got_that_far():
    def stats(*iters):
        rs = wf.RunStats(topology="full_mesh", task="math")
        rs.iterations = [wf.Iteration(r, c, 92.0, True, False) for r, c in iters]
        return rs

    group = [stats((1, True)), stats((2, True)), stats((3, False), (3, True)), stats((2, True))]
    c = wf.agg_consensus(group)
    assert c["discussions"] == 5 and c["agreed"] == 4
    assert c["rounds"] == {"1": 1, "2": 2, "3": 2}
    assert [(p["reached"], p["agreed"]) for p in c["per_round"]] == [(5, 1), (4, 2), (2, 1)]
    assert c["per_round"][1]["rate"] == 0.5


def test_retries_split_unscored_and_low_score_rejections():
    rs = wf.RunStats(topology="vertical", task="math")
    rs.iterations = [
        wf.Iteration(3, False, None, False, True),
        wf.Iteration(3, False, 85.0, False, False),
        wf.Iteration(3, False, 92.0, True, False),
    ]
    rs.iter_cost = [(18, 50000.0, 100.0), (18, 52000.0, 110.0), (18, 54000.0, 120.0)]
    rs.score, rs.goal = 92.0, True
    one = wf.RunStats(topology="vertical", task="math")
    one.iterations = [wf.Iteration(3, False, 92.0, True, False)]
    one.iter_cost = [(19, 40000.0, 90.0)]
    one.score, one.goal = 92.0, True
    r = wf.agg_retries([rs, one])
    assert r["iterations"] == {"1": 1, "3": 1}
    assert r["not_accepted"] == {"iterations": 2, "unscored": 1, "low_score": 1}
    assert r["cost"]["first"]["calls"] == 18.5 and r["cost"]["retry"]["n"] == 2
    assert r["cost"]["retry"]["tokens"] == 53000
    assert r["never_accepted"] == 0


# ---------------------------------------------------------------------------
# build() on a synthetic source
# ---------------------------------------------------------------------------


def test_build_shape_aggregates_only_and_deterministic(tmp_path):
    src = tmp_path / "src"
    _source(src)
    ctx = _ctx(src)
    out = wf.build(ctx)
    text = wf.dumps(out)
    assert text == wf.dumps(wf.build(_ctx(src)))  # byte-identical
    assert_no_leaks(text, "workflow.json")
    assert not (_keys(out, set()) & FORBIDDEN)
    assert out["source"] == {"runs": 24, "iteration_history": 24}
    assert out["topologies"] == list(er.TOPOLOGIES)
    assert set(out["groups"]) == {"all", *er.TASKS}
    assert out["roles"] == ["planner", "researcher", "critic", "executor"]

    g = out["groups"]["all"]
    for t in er.TOPOLOGIES:
        a = g[t]
        assert a["runs"] == 8
        for key, shares in a["stages"]["share"].items():
            assert math.isclose(sum(v or 0 for v in shares), 1.0, abs_tol=1e-3), (t, key)
        assert a["execution"]["peak"] == {"2": 8}  # two execution calls, 10 ms apart
        assert a["consensus"]["discussions"] == 8 and a["consensus"]["rounds"] == {"2": 8}
        assert a["retries"]["iterations"] == {"1": 8}
        assert a["quality"]["scored"] == 8 and a["quality"]["goal_rate"] == 1
        assert (a["messages"] is None) == (t != "full_mesh")
        assert set(a["context"]) == set(wf.CONTEXT_KINDS[t])
    # Star has no synthesis call; recruitment is one call of the run
    assert g["vertical"]["stages"]["share"]["calls"][wf.S_SYNTH] is None or (
        g["vertical"]["stages"]["share"]["calls"][wf.S_SYNTH] == 0
    )
    assert g["horizontal"]["stages"]["per_run"]["calls"][wf.S_RECRUIT] == 1
    assert g["horizontal"]["stages"]["per_run"]["calls"][wf.S_DISC] == 8  # 2 rounds x 4

    m = g["full_mesh"]["messages"]
    assert sum(map(sum, m["count"])) == 8 * 2 * 12  # runs x rounds x N(N-1)
    assert all(m["count"][i][i] == 0 for i in range(len(m["roles"])))
    assert m["per_run"] == 24

    ctxv = g["vertical"]["context"]
    assert [p["round"] for p in ctxv["solver"]] == [1, 2]
    assert ctxv["solver"][0]["prompt_tokens"]["n"] == 8
    assert ctxv["reviewer"][0]["prompt_tokens"]["n"] == 8 * 3
    assert g["horizontal"]["roles"]["discussion"].get("orchestrator") is None
    assert g["horizontal"]["roles"]["all"]["orchestrator"]["calls_per_run"] == 4
    # consensus alternates by file order: half the runs of the whole source agreed
    assert sum(g[t]["consensus"]["agreed"] for t in er.TOPOLOGIES) == 12


def test_build_without_raw_responses_falls_back_to_the_final_iteration(tmp_path):
    src = tmp_path / "src"
    _source(src)
    ctx = _ctx(src)
    ctx["source"] = tmp_path / "missing"
    out = wf.build(ctx)
    assert out["source"]["iteration_history"] == 0
    fm = out["groups"]["all"]["full_mesh"]["consensus"]
    assert fm["discussions"] == 8 and fm["agreed"] == 8  # make_response: full mesh agreed


def test_main_writes_only_workflow_json(tmp_path, monkeypatch):
    src = tmp_path / "src"
    _source(src)
    monkeypatch.setattr(er, "FIXTURE_INDEX", tmp_path / "no-index.json")
    out = tmp_path / "out"
    assert wf.main(["--source", str(src), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["workflow.json"]
    doc = json.loads((out / "workflow.json").read_text(encoding="utf-8"))
    assert doc["generator"] == wf.GENERATOR
    assert wf.main(["--source", str(tmp_path / "nothing"), "--out", str(out)]) == 2


def test_export_results_hook_finds_the_module(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "ANALYSES", ("workflow",))  # the other modules are not under test
    src = tmp_path / "src"
    _source(src)
    ctx = _ctx(src)
    texts = er.run_analyses(ctx["runs"], {}, {"runs": []}, src)
    assert texts["workflow.json"] == wf.dumps(wf.build(ctx))


@pytest.mark.skipif(not REAL_SOURCE.is_dir(), reason="paper-branch checkout not present")
def test_real_data_findings():
    out = wf.build(_ctx(REAL_SOURCE))
    g = out["groups"]["all"]
    assert out["source"] == {"runs": 1481, "iteration_history": 1481}
    assert g["vertical"]["consensus"]["agreed"] == 0  # Star never gets full approval
    assert g["full_mesh"]["consensus"]["rate"] > g["horizontal"]["consensus"]["rate"]
    assert g["full_mesh"]["messages"]["per_run"] > 20
    # Full mesh makes the most calls but does not score higher than Sequential
    fm, sq = g["full_mesh"]["quality"], g["horizontal"]["quality"]
    assert fm["calls"]["median"] > sq["calls"]["median"]
    assert fm["score"]["mean"] <= sq["score"]["mean"]
    assert not (_keys(out, set()) & FORBIDDEN)
