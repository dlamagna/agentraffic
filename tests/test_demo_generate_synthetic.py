"""Tests for scripts/demo/generate_synthetic.py: maths helpers, validation, structure, schema.

They read only ui/data/public/ and never need ui/data/private/.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter

import pytest

from scripts.demo import generate_synthetic as gs
from scripts.demo.generate_fixtures import REPO_ROOT, TASKS, TOPOLOGIES, parse_example_tasks

PUBLIC = REPO_ROOT / "ui" / "data" / "public"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


# ---------------------------------------------------------------------------
# Maths (fast)
# ---------------------------------------------------------------------------


def test_normal_cdf_and_inverse_match_stdlib():
    nd = statistics.NormalDist()
    for x in (-5, -2.3, -0.4, 0, 0.7, 1.96, 4.2):
        assert gs.norm_cdf(x) == pytest.approx(nd.cdf(x), abs=1e-12)
    for p in (1e-9, 0.001, 0.02, 0.3, 0.5, 0.77, 0.975, 0.99999):
        assert gs.norm_ppf(p) == pytest.approx(nd.inv_cdf(p), abs=1e-9)


def test_cholesky_and_eigh_reconstruct():
    a = [[4.0, 2.0, 0.6], [2.0, 3.0, 0.5], [0.6, 0.5, 2.0]]
    low = gs.cholesky(a)
    for i in range(3):
        for j in range(3):
            assert sum(low[i][k] * low[j][k] for k in range(3)) == pytest.approx(a[i][j])
    vals, v = gs.eigh(a)
    for i in range(3):
        for j in range(3):
            rec = sum(v[i][k] * vals[k] * v[j][k] for k in range(3))
            assert rec == pytest.approx(a[i][j], abs=1e-9)
    with pytest.raises(ValueError):
        gs.cholesky([[1.0, 2.0], [2.0, 1.0]])


def test_nearest_correlation_repairs_a_non_psd_matrix():
    bad = [[1.0, 0.9, -0.9], [0.9, 1.0, 0.9], [-0.9, 0.9, 1.0]]
    with pytest.raises(ValueError):
        gs.cholesky(bad)
    fixed = gs.nearest_correlation(bad)
    assert all(fixed[i][i] == pytest.approx(1.0) for i in range(3))
    assert min(gs.eigh(fixed)[0]) > -1e-9
    r, low = gs.make_pd_correlation(bad)
    assert low[0][0] > 0 and all(r[i][i] == pytest.approx(1.0, abs=1e-6) for i in range(3))


def test_spearman_with_ties_and_structure_table():
    x = [1.0, 2.0, 2.0, 3.0]
    assert gs.avg_ranks(x) == [1.0, 2.5, 2.5, 4.0]
    s = gs.spearman_matrix([x, [10.0, 20.0, 20.0, 30.0], [5.0] * 4])
    assert s[0][1] == pytest.approx(1.0) and s[0][2] is None
    seq = gs.structure_table("horizontal")
    assert seq[13] == (3,) and seq[22] == (3, 2) and seq[39] == (3, 3, 3)
    assert gs.structure_table("vertical")[24] == (3, 3)
    mesh = gs.structure_table("full_mesh")
    assert mesh[25] == (2,) and mesh[111] == (3, 3, 3)
    assert gs.snap_count(seq, 11) in (10, 13)


# ---------------------------------------------------------------------------
# The generated data set (one generation, shared)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def generated():
    if not (PUBLIC / "summary.json").is_file():
        pytest.skip("ui/data/public/summary.json not generated")
    files, report = gs.generate(PUBLIC)
    return files, report, json.loads(files["runs.json"])


def test_validation_meets_the_spec(generated):
    _, report, _ = generated
    assert gs.assert_validation(report) == []
    for topo in TOPOLOGIES:
        assert report["topologies"][topo]["max_rho_error"] <= 0.05
    assert report["pooled"]["max_rho_error"] <= 0.1


def test_generation_is_deterministic(generated):
    files, _, _ = generated
    again, _ = gs.generate(PUBLIC)
    assert again == files


def test_runs_document(generated):
    files, _, doc = generated
    assert doc["synthetic"] is True
    assert doc["experiments"] == ["synthetic"]
    runs = doc["runs"]
    assert Counter(r["topology"] for r in runs) == {
        "horizontal": 500,
        "vertical": 481,
        "full_mesh": 500,
    }
    assert all(r["synthetic"] is True for r in runs)
    ids = [r["id"] for r in runs]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"syn-\d{4}[0-9a-f]{4}", i) for i in ids)
    assert not UUID.search(files["runs.json"])
    keys = doc["metric_keys"]
    assert all(len(r["metrics"]) == len(keys) for r in runs)
    assert doc["outliers"]["n_flagged"] == sum(1 for r in runs if r.get("flags"))
    for r in runs:
        assert r["roles"] and len(r["roles"]) == 4
        assert r["task_id"] == r["id"] and r["experiment"] == 0
        starts = [c[0] for c in r["calls"]]
        assert starts == sorted(starts) and starts[0] == 0


def test_timelines_follow_each_topology(generated):
    _, _, doc = generated
    keys = doc["metric_keys"]
    i_n = keys.index("disc_n_requests")
    f = {name: i for i, name in enumerate(doc["call_fields"])}
    for r in doc["runs"][:300]:
        calls = r["calls"]
        disc = [c for c in calls if c[f["stage"]] in (1, 2)]
        assert len(disc) == r["metrics"][i_n]
        assert sum(1 for c in calls if c[f["stage"]] == 0) == r["iterations"]
        assert calls[-1][f["stage"]] == 5 or any(c[f["stage"]] == 5 for c in calls)
        if r["topology"] == "vertical":
            assert not any(c[f["stage"]] == 2 for c in calls)
            solvers = [c for c in disc if c[f["agent"]] == 0]
            assert len(solvers) * 4 == len(disc)
        if r["topology"] == "full_mesh":
            msgs = [c for c in disc if c[f["stage"]] == 1]
            assert len(msgs) % 12 == 0
            events = sorted(
                [(c[0], 1) for c in msgs] + [(c[0] + c[1], -1) for c in msgs],
                key=lambda e: (e[0], e[1]),
            )
            live = peak = 0
            for _, d in events:
                live += d
                peak = max(peak, live)
            assert peak <= gs.MAX_WORKERS + 1
        if r["topology"] == "horizontal":
            msgs = [c for c in disc if c[f["stage"]] == 1]
            ordered = sorted(msgs, key=lambda c: c[0])
            for a, b in zip(ordered, ordered[1:]):
                if (
                    a[f["round"]] is not None
                    and a[f["agent"]] != 3
                    and b[f["agent"]] == a[f["agent"]] + 1
                ):
                    assert b[0] >= a[0] + a[1] - 12  # one at a time (10 ms recording slack)


def test_fixtures(generated):
    files, _, doc = generated
    index = json.loads(files["fixtures/index.json"])
    assert index["synthetic"] is True
    assert len(index["fixtures"]) == len(TOPOLOGIES) * len(TASKS)
    examples = parse_example_tasks((REPO_ROOT / "ui/playground/js/config.js").read_text("utf-8"))
    by_id = {r["id"]: r for r in doc["runs"]}
    for e in index["fixtures"]:
        assert e["synthetic"] is True and e["experiment"] == "synthetic"
        assert e["original_task"] == examples[e["task"]]
        run = by_id[e["task_id"]]
        assert (
            run["fixture"] is True and run["topology"] == e["topology"] and run["task"] == e["task"]
        )
        response = json.loads(files[f"fixtures/{e['files']['response']}"])
        events = json.loads(files[f"fixtures/{e['files']['events']}"])
        assert response["original_task"] == examples[e["task"]]
        assert events[-1]["event"] == "complete"
        assert events[-1]["data"] == {"$ref": f"{e['task']}.response.json"}
        assert len(response["llm_requests"]) == len(run["calls"])
        assert {r["endpoint"] for r in response["llm_requests"]} == {"http://llm:8000/chat"}
        assert "[synthetic]" in response["llm_requests"][1]["response"]
    assert sum(1 for r in doc["runs"] if r["fixture"]) == 12
    text = "".join(files.values())
    assert not UUID.search(text) and "balanced_agents" not in text


def test_output_is_free_of_private_text(generated):
    files, _, _ = generated
    gs.assert_no_private_text(files, REPO_ROOT)  # no-op when ui/data/private/ is absent
