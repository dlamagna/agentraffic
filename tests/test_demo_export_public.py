"""Tests for scripts/demo/export_public.py: the allow-list, determinism, leak refusal."""

from __future__ import annotations

import json

import pytest

from scripts.demo import export_public as ep
from scripts.demo.generate_fixtures import REPO_ROOT

TASK_ID = "8fb8c4c9-9079-4f0d-b236-fd973b68c1e4"


def private_summary() -> dict:
    return {
        "schema_version": 1,
        "generator": "scripts/demo/export_results.py",
        "future_per_run_table": [{"id": "abc", "task_id": TASK_ID}],  # not on the allow-list
        "source": {
            "repository": "dlamagna/agentraffic",
            "branch": "paper-branch",
            "experiments": ["balanced_agents4_a", "balanced_agents4_b"],
            "n_runs": {"horizontal": 2, "vertical": 1, "full_mesh": 2},
            "n_runs_total": 5,
            "files": {"table2": "data/agentverse/x/table2.md"},
            "join": {"runs": 5, "match_rate": 1.0, "method": "row i", "debug_row": [1, 2]},
            "checkout": "/srv/checkout",
        },
        "topologies": [{"key": "horizontal", "label": "Sequential"}],
        "tasks": [{"key": "math", "label": "Math"}],
        "table2": {"title": "T", "source": "x", "runs": {"horizontal": 2}, "sections": [], "extra": 1},
        "iat": {"definition": "d", "bins_s": [0.05, 0.1], "per_topology": {"horizontal": {"n": 3}}},
        "metrics": [{"key": "disc_n_requests"}],
        "layers": ["application"],
        "correlations": {"method": "m", "metric_keys": ["a"], "groups": {"all": {"rho": [[1]]}}},
        "aggregates": {
            "stats": ["median"],
            "by_topology": {"horizontal": {"a": {"median": 1}}},
            "by_topology_task": {},
            "by_run": {"abc": {"a": 1}},
        },
        "quantile_grid": [0, 50, 100],
        "quantiles": {"horizontal": {"a": [1, 2, 3]}},
        "scaling": None,
        "fixtures": [{"topology": "horizontal", "task": "math", "task_id": TASK_ID}],
    }


@pytest.fixture
def src(tmp_path):
    d = tmp_path / "private"
    d.mkdir()
    (d / "summary.json").write_text(json.dumps(private_summary()), encoding="utf-8")
    (d / "runs.json").write_text('{"runs":[{"id":"abc","task_id":"%s"}]}' % TASK_ID)
    for name, doc in (
        ("traffic.json", {"n_runs": 5}),
        ("load.json", {"a": [1]}),
        ("workflow.json", {}),
    ):
        (d / name).write_text(json.dumps(doc, separators=(",", ":")) + "\n", encoding="utf-8")
    (d / "manifest.json").write_text('{"mode":"private","generated":"2026-01-01"}\n')
    return d


def test_allow_list_drops_unlisted_keys_at_every_level():
    out = ep.public_summary(private_summary())
    assert "fixtures" not in out and "future_per_run_table" not in out
    assert set(out["source"]) == {
        "repository",
        "branch",
        "n_runs",
        "n_runs_total",
        "join",
    }
    assert set(out["source"]["join"]) == {"runs", "match_rate", "method"}
    assert set(out["table2"]) == {"title", "runs", "sections"}
    assert set(out["aggregates"]) == {"stats", "by_topology", "by_topology_task"}
    assert out["quantiles"] == {"horizontal": {"a": [1, 2, 3]}} and out["quantile_grid"] == [
        0,
        50,
        100,
    ]
    assert out["scaling"] is None
    assert "experiments" not in out["source"] and "source" not in out["table2"]
    assert TASK_ID not in json.dumps(out)


def test_scaling_keeps_numbers_but_not_experiment_names():
    private = private_summary()
    private["scaling"] = {
        "definition": "from full_mesh_agents3_experiment_x",
        "bins": "iat.bins_s",
        "agents": [{"n_agents": 3, "n_runs": 4, "experiments": ["full_mesh_agents3_experiment_x"]}],
    }
    out = ep.public_summary(private)
    assert out["scaling"] == {"bins": "iat.bins_s", "agents": [{"n_agents": 3, "n_runs": 4}]}


def test_allow_list_skips_missing_keys_and_rejects_shape_mismatch():
    assert ep.allow({"a": 1}, {"a": True, "b": True}) == {"a": 1}
    with pytest.raises(ValueError):
        ep.allow([1], {"a": True})


def test_every_allowed_top_level_key_is_a_real_summary_key():
    """The allow-list must not drift from what export_results writes."""
    from scripts.demo import export_results as er

    produced = {
        "schema_version",
        "generator",
        "source",
        "topologies",
        "tasks",
        "table2",
        "iat",
        "metrics",
        "layers",
        "correlations",
        "aggregates",
        "quantile_grid",
        "quantiles",
        "scaling",
        "fixtures",
    }
    assert set(ep.SUMMARY_ALLOW) == produced - {"fixtures"}
    assert er.QUANTILE_GRID[0] == 0 and er.QUANTILE_GRID[-1] == 100


def test_main_writes_public_files_deterministically(src, tmp_path):
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    assert ep.main(["--src", str(src), "--out", str(out1)]) == 0
    assert ep.main(["--src", str(src), "--out", str(out2)]) == 0
    names = {"summary.json", "traffic.json", "load.json", "workflow.json", "manifest.json"}
    assert {p.name for p in out1.iterdir()} == names  # no runs.json, no fixtures/
    for n in names:
        assert (out1 / n).read_bytes() == (out2 / n).read_bytes()
    for n in ep.COPIED:  # aggregates copied unchanged
        assert (out1 / n).read_bytes() == (src / n).read_bytes()
    assert json.loads((out1 / "manifest.json").read_text()) == {"mode": "public", "synthetic": True}
    assert TASK_ID not in (out1 / "summary.json").read_text()


def test_main_leaves_other_files_in_out_alone(src, tmp_path):
    out = tmp_path / "pub"
    (out / "fixtures").mkdir(parents=True)
    (out / "runs.json").write_text("synthetic runs")
    (out / "fixtures" / "index.json").write_text("{}")
    assert ep.main(["--src", str(src), "--out", str(out)]) == 0
    assert (out / "runs.json").read_text() == "synthetic runs"
    assert (out / "fixtures" / "index.json").read_text() == "{}"


@pytest.mark.parametrize(
    "payload",
    [
        '{"path":"/home/someone/data"}',  # home path
        '{"host":"http://192.168.1.20:8101"}',  # private IP
        '{"trace_id":"x"}',  # telemetry key
        '{"id":"%s"}' % TASK_ID,  # a task id
        '{"id":"0123456789abcdef0123456789abcdef"}',  # a trace id
    ],
)
def test_leaks_in_copied_files_fail_and_write_nothing(src, tmp_path, payload, capsys):
    (src / "traffic.json").write_text(payload + "\n")
    out = tmp_path / "pub"
    assert ep.main(["--src", str(src), "--out", str(out)]) == 3
    assert not out.exists()
    assert "traffic.json" in capsys.readouterr().out


def test_leak_in_an_allowed_summary_value_fails(src, tmp_path):
    doc = private_summary()
    doc["iat"]["definition"] = "see /home/someone/notes"
    (src / "summary.json").write_text(json.dumps(doc))
    assert ep.main(["--src", str(src), "--out", str(tmp_path / "pub")]) == 3


def test_missing_or_broken_input_is_a_clean_error(src, tmp_path):
    (src / "load.json").unlink()
    assert ep.main(["--src", str(src), "--out", str(tmp_path / "pub")]) == 2
    (src / "load.json").write_text("{not json")
    assert ep.main(["--src", str(src), "--out", str(tmp_path / "pub")]) == 2
    assert ep.main(["--src", str(tmp_path / "nowhere"), "--out", str(tmp_path / "pub")]) == 2


REAL_PRIVATE = REPO_ROOT / "ui" / "data" / "private"


@pytest.mark.skipif(not (REAL_PRIVATE / "summary.json").is_file(), reason="no private data here")
def test_real_private_data_exports_without_ids(tmp_path):
    texts = ep.build(REAL_PRIVATE)
    summary = json.loads(texts["summary.json"])
    assert "fixtures" not in summary
    private = json.loads((REAL_PRIVATE / "summary.json").read_text(encoding="utf-8"))
    blob = "".join(texts.values())
    for f in private.get("fixtures", []):
        assert f["task_id"] not in blob
