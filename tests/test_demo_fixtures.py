"""Tests for scripts/demo/generate_fixtures.py: stdlib only, no recorded data required."""

import copy
import gzip
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.demo import generate_fixtures as gf

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "ui" / "data" / "private" / "fixtures"
REAL_SOURCE = REPO_ROOT / "data" / "att-paper"
RESPONSE_KEYS = [
    "task_id",
    "original_task",
    "completed",
    "iterations",
    "duration_seconds",
    "final_output",
    "stages",
    "iteration_history",
    "llm_requests",
]


# ---------------------------------------------------------------------------
# Sanitiser
# ---------------------------------------------------------------------------


def _otel():
    return {"trace_id": "a" * 32, "span_id": "b" * 16, "trace_flags": 1, "is_remote": False}


def test_sanitise_rewrites_private_hosts_everywhere():
    doc = {
        "llm_requests": [
            {
                "endpoint": "http://172.23.0.30:8000/chat",
                "prompt": "see http://10.1.2.3:8101/agentverse and https://127.0.0.1:9090/q?x=1",
                "nested": [["fwd to 192.168.1.20:80 then 172.16.0.9"], {"deep": "10.0.0.1"}],
            }
        ],
        "stages": {
            "recruitment": {
                "experts": [
                    {"endpoint": "http://172.23.0.20:8102/subtask"},
                    {"endpoint": "http://172.23.0.23:8105/subtask"},
                ]
            }
        },
    }
    out = gf.sanitise(doc)
    req = out["llm_requests"][0]
    assert req["endpoint"] == "http://llm:8000/chat"
    assert req["prompt"] == (
        "see http://agent-a:8101/agentverse and https://internal-host:9090/q?x=1"
    )
    assert req["nested"][0][0] == "fwd to internal-host:80 then <redacted-ip>"
    assert req["nested"][1]["deep"] == "<redacted-ip>"
    experts = out["stages"]["recruitment"]["experts"]
    assert [e["endpoint"] for e in experts] == [
        "http://agent-b:8102/subtask",
        "http://agent-b:8105/subtask",
    ]
    assert gf.find_leaks(gf.dumps(out)) == []
    # input untouched
    assert doc["llm_requests"][0]["endpoint"] == "http://172.23.0.30:8000/chat"


@pytest.mark.parametrize(
    "text",
    [
        "8.8.8.8",
        "110.0.0.1",
        "172.32.0.1",
        "version 1.10.0.12",
        "192.169.1.1",
        "http://example.com:8000/x",
    ],
)
def test_sanitise_leaves_public_addresses_alone(text):
    assert gf.sanitise_text(text) == text


def test_sanitise_drops_otel_and_keeps_everything_else():
    req = {
        "seq": 1,
        "start_time_utc": "2026-05-01T08:39:59.388414+00:00",
        "duration_seconds": 3.03,
        "otel": {"agent_a": _otel(), "llm_backend": _otel()},
        "llm_meta": {"request_id": "61fbf7ab", "latency_ms": 3023, "otel": _otel()},
    }
    out = gf.sanitise({"llm_requests": [req]})["llm_requests"][0]
    assert "otel" not in out
    assert out["llm_meta"] == {"request_id": "61fbf7ab", "latency_ms": 3023}
    assert out["start_time_utc"] == req["start_time_utc"]
    assert out["duration_seconds"] == req["duration_seconds"]
    assert "otel" in req  # not mutated


@pytest.mark.parametrize(
    "payload, kind",
    [
        ({"endpoint": "http://10.0.0.5:8000/chat"}, "private IPv4"),
        ({"x": "log at /home/alice/run.log"}, "home directory"),
        ({"x": "/Users/bob/.cache"}, "home directory"),
        ({"x": "dlamagna@workstation"}, "username"),
        ({"x": "postgres://db.internal:5432/x"}, "internal hostname"),
        ({"x": "http://[::1]:8000/"}, "IPv6"),
        ({"otel": {"trace_id": "abc"}}, "telemetry key"),
        ({"meta": {"span_id": "abc"}}, "telemetry key"),
    ],
)
def test_leak_check_fails_loudly(payload, kind):
    text = gf.dumps(payload)
    with pytest.raises(gf.LeakError, match=kind):
        gf.assert_no_leaks(text, "test")


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "https://github.com/dlamagna/agentraffic"},
        {"code": "reversed = s[::-1]; t = x[::1]"},
        {"code": 'print(json.dumps({"trace_id": 1}))'},
        {"x": "threading.local() and self.internal"},
        {"endpoint": "http://llm:8000/chat"},
    ],
)
def test_leak_check_allows_benign_text(payload):
    gf.assert_no_leaks(gf.dumps(payload), "test")


def test_render_fixture_refuses_unsanitised_response():
    with pytest.raises(gf.LeakError):
        gf.render_fixture("horizontal", "math", {"endpoint": "http://172.23.0.30:8000/chat"}, None)


def test_render_fixture_replaces_complete_payload_with_ref():
    response = {"task_id": "t1", "llm_requests": []}

    def builder(resp):
        return [
            {"t_ms": 0, "event": "stage_start", "data": {}},
            {"t_ms": 5, "event": "complete", "data": resp},
        ]

    files = gf.render_fixture("vertical", "coding", response, builder)
    events = json.loads(files["vertical/coding.events.json"])
    assert events[-1] == {"t_ms": 5, "event": "complete", "data": {"$ref": "coding.response.json"}}
    assert events[0] == {"t_ms": 0, "event": "stage_start", "data": {}}


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def _big_doc():
    reqs = []
    for i in range(6):
        reqs.append(
            {
                "seq": i + 1,
                "label": f"horizontal_discussion_round{i}",
                "start_time_utc": f"2026-05-01T08:40:{i:02d}.000000+00:00",
                "duration_seconds": 1.5 + i,
                "prompt": ("p%d " % i) * (3000 * (i + 1)),
                "response": "short answer",
                "llm_meta": {"latency_ms": 1500, "prompt_tokens": 900, "total_tokens": 1000},
            }
        )
    return {
        "task_id": "t",
        "duration_seconds": 64.89,
        "stages": {"decision": {"discussion_rounds": [{"responses": [{"response": "r" * 50000}]}]}},
        "llm_requests": reqs,
    }


def test_truncation_fits_and_preserves_timing():
    doc = _big_doc()
    original = copy.deepcopy(doc)
    limit = 60_000
    assert gf.encoded_size(doc) > limit
    out, info = gf.truncate_to_fit(doc, limit)
    assert gf.encoded_size(out) <= limit
    assert info["truncated"] is True and info["truncated_strings"] > 0
    assert doc == original  # input untouched
    assert out["duration_seconds"] == doc["duration_seconds"]
    for a, b in zip(doc["llm_requests"], out["llm_requests"]):
        for key in ("seq", "label", "start_time_utc", "duration_seconds", "llm_meta"):
            assert a[key] == b[key]
        assert b["response"] == "short answer"  # short strings untouched
    # Water-filling: every prompt/response longer than the common cap is cut to exactly it.
    cap = info["cap_chars"]
    pairs = [(a["prompt"], b["prompt"]) for a, b in zip(doc["llm_requests"], out["llm_requests"])]
    nested_path = ("stages", "decision", "discussion_rounds")
    src_nested = doc[nested_path[0]][nested_path[1]][nested_path[2]][0]["responses"][0]
    out_nested = out[nested_path[0]][nested_path[1]][nested_path[2]][0]["responses"][0]
    pairs.append((src_nested["response"], out_nested["response"]))
    for before, after in pairs:
        if len(before) > cap + len(gf.TRUNCATION_MARKER):
            assert after == before[:cap] + gf.TRUNCATION_MARKER
        else:
            assert after == before
    assert sum(after != before for before, after in pairs) == info["truncated_strings"]


def test_truncation_is_deterministic():
    a, info_a = gf.truncate_to_fit(_big_doc(), 60_000)
    b, info_b = gf.truncate_to_fit(_big_doc(), 60_000)
    assert gf.dumps(a) == gf.dumps(b)
    assert info_a == info_b


def test_truncation_noop_when_small():
    doc = {"llm_requests": [{"prompt": "hi", "response": "there"}]}
    out, info = gf.truncate_to_fit(doc, 10_000)
    assert out is doc
    assert info == {"truncated": False, "truncated_strings": 0, "cap_chars": None}


def test_truncation_impossible_raises():
    doc = {"final_output": "x" * 20_000, "llm_requests": [{"prompt": "y" * 5000}]}
    with pytest.raises(gf.TruncationError):
        gf.truncate_to_fit(doc, 5_000)


# ---------------------------------------------------------------------------
# IAT / burst computation
# ---------------------------------------------------------------------------

T0 = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)


def _req(label, t_s, **kw):
    return {"label": label, "start_time_utc": (T0 + timedelta(seconds=t_s)).isoformat(), **kw}


def test_discussion_iats_filters_sorts_and_diffs():
    reqs = [
        _req("expert_recruitment", 0.0),
        _req("horizontal_discussion_round1", 7.0),
        _req("horizontal_discussion_round1", 3.0),
        _req("execute_planner", 3.5),
        _req("synthesize_discussion", 12.0),
        _req("horizontal_discussion_round2", 9.5),
        {"label": "horizontal_discussion_round2"},  # no timestamp: skipped
    ]
    iats = gf.discussion_iats(reqs, "horizontal")
    assert iats == pytest.approx([4.0, 2.5, 2.5])
    assert gf.burst_fraction(iats) == 0.0
    assert gf.shows_expected_burst("horizontal", iats)


def test_vertical_fanout_is_a_burst():
    reqs = [
        _req("vertical_solver_iter1", 0.0),
        _req("vertical_reviewer_critic_iter1", 6.0),
        _req("vertical_reviewer_executor_iter1", 6.0004),
        _req("vertical_reviewer_researcher_iter1", 6.001),
        _req("final_output", 30.0),
    ]
    iats = gf.discussion_iats(reqs, "vertical")
    assert len(iats) == 3
    assert gf.burst_fraction(iats) == pytest.approx(2 / 3)
    assert gf.shows_expected_burst("vertical", iats)
    assert not gf.shows_expected_burst("horizontal", iats)
    assert not gf.shows_expected_burst("full_mesh", [1.0, 2.0])
    assert gf.label_topology(reqs) == "vertical"


def test_percentile_matches_numpy_linear():
    assert gf.percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert gf.percentile([5.0], 95) == 5.0
    assert gf.percentile([3, 1, 2], 50) == 2
    s = gf.iat_summary([0.01, 0.02, 1.0, 4.0])
    assert s == {"n": 4, "median_s": 0.51, "p95_s": 3.55, "burst_fraction": 0.5}


def test_label_topology():
    assert gf.label_topology([{"label": "full_mesh_message_round1_agent0_to_agent1"}]) == (
        "full_mesh"
    )
    assert gf.label_topology([{"label": "horizontal_discussion_round1"}]) == "horizontal"
    assert gf.label_topology([{"label": "expert_recruitment"}]) is None


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _run(name, topology="full_mesh", n=13, dur=34.0, burst=True, iterations=1, **kw):
    iats = [0.001, 2.0] if burst else [2.0, 3.0]
    defaults = dict(
        experiment="exp",
        task_dir=name,
        path=Path(name),
        category="research-task",
        topology=topology,
        iterations=iterations,
        duration_s=dur,
        n_disc_calls=n,
        disc_iats=iats,
        labels_topology=topology,
    )
    defaults.update(kw)
    return gf.RunSummary(**defaults)


def _pool():
    return [
        _run("d_far", n=37, dur=80.0),
        _run("b_median", n=13, dur=34.0),
        _run("c_near", n=13, dur=35.0),
        _run("a_twin", n=13, dur=34.0),  # same features as b_median: tie-break by name
        _run("e_low", n=13, dur=30.0),
        _run("f_multi", n=13, dur=34.0, iterations=2),
        _run("g_error", n=13, dur=34.0, n_errors=1),
        _run("h_incomplete", n=13, dur=34.0, completed=False),
    ]


def test_selection_is_deterministic_and_tie_breaks_by_name():
    picks = set()
    for seed in range(5):
        runs = _pool()
        random.Random(seed).shuffle(runs)
        sel = gf.select_representative(runs, lambda r: 1000, max_bytes=10_000)
        picks.add(sel.run.task_dir)
        assert sel.n_runs == 8 and sel.n_valid == 6 and sel.n_pool == 5
        assert sel.modal_iterations == 1
    assert picks == {"a_twin"}


def test_selection_prefers_runs_that_fit():
    sizes = {"a_twin": 50_000, "b_median": 50_000}
    sel = gf.select_representative(_pool(), lambda r: sizes.get(r.task_dir, 1000), 10_000)
    assert sel.run.task_dir == "c_near"
    assert sel.fits


def test_selection_falls_back_to_closest_when_nothing_fits():
    sel = gf.select_representative(_pool(), lambda r: 50_000, 10_000)
    assert sel.run.task_dir == "a_twin"
    assert not sel.fits


def test_selection_skips_runs_failing_the_burst_check():
    runs = [
        _run("a_median_no_burst", n=13, dur=34.0, burst=False),
        _run("b_burst", n=13, dur=36.0),
        _run("c_burst", n=13, dur=31.0),
    ]
    sel = gf.select_representative(runs, lambda r: 1000, 10_000)
    assert sel.run.task_dir == "b_burst"
    seq = [
        _run("a_seq", topology="horizontal", burst=True),
        _run("b_seq", topology="horizontal", burst=False, dur=40.0),
    ]
    assert gf.select_representative(seq, lambda r: 1000, 10_000).run.task_dir == "b_seq"


def test_selection_uses_modal_iteration_count():
    runs = [_run(f"m{i}", iterations=2, dur=60.0 + i) for i in range(3)]
    runs += [_run("s0", iterations=1, dur=61.0), _run("t0", iterations=3, dur=61.0)]
    sel = gf.select_representative(runs, lambda r: 1000, 10_000)
    assert sel.modal_iterations == 2
    assert sel.run.task_dir == "m1"


def test_selection_ignores_topology_label_mismatch():
    runs = [_run("a_bad", labels_topology="vertical"), _run("b_ok", dur=50.0)]
    assert gf.select_representative(runs, lambda r: 1000, 10_000).run.task_dir == "b_ok"


# ---------------------------------------------------------------------------
# Task texts and Table 2 parsing
# ---------------------------------------------------------------------------


def test_example_tasks_parse_and_normalise():
    tasks = gf.parse_example_tasks(gf.CONFIG_JS.read_text(encoding="utf-8"))
    assert set(tasks) == set(gf.TASKS)
    recorded = "||" + " ".join(tasks["math"].split())
    assert gf.normalise_task_text(recorded) == gf.normalise_task_text(tasks["math"])


TABLE2_SNIPPET = """
Runs: Sequential n=500, Star n=481, Full Mesh n=500
Pooled IATs (raw, unfiltered): Sequential n=6513, Star n=7355, Full Mesh n=14493

| Metric | Sequential | Star | Full Mesh |
| **Median IAT** | 4.56 s | 0.41 ms (-100%) | 236 ms (-95%) |
| **Burst fraction (IAT < 50 ms)** | 0.0% | 53.3% | 38.2% |
"""


def test_parse_table2():
    t = gf.parse_table2(TABLE2_SNIPPET)
    assert t["horizontal"] == {
        "n_runs": 500,
        "n_iats": 6513,
        "median_iat_s": 4.56,
        "burst_pct": 0.0,
    }
    assert t["vertical"]["median_iat_s"] == pytest.approx(0.00041)
    assert t["full_mesh"]["median_iat_s"] == pytest.approx(0.236)
    assert t["full_mesh"]["n_iats"] == 14493
    for topo in gf.TOPOLOGIES:
        assert t[topo] == pytest.approx(gf.PAPER_TABLE2_FALLBACK[topo])


# ---------------------------------------------------------------------------
# End to end on a synthetic source tree
# ---------------------------------------------------------------------------

CATEGORIES = list(gf.CATEGORY_TO_TASK)


def _synthetic_response(topology, category, uid, start, jitter):
    def ts(t):
        return (start + timedelta(seconds=t)).isoformat()

    def req(seq, label, stage, t, **kw):
        return {
            "seq": seq,
            "iteration": 0,
            "stage": stage,
            "label": label,
            "source": "Agent A",
            "prompt": f"prompt {label}",
            "response": f"response {label}",
            "endpoint": "http://172.23.0.30:8000/chat",
            "error": False,
            "start_time_utc": ts(t),
            "request_id": f"{seq:08x}",
            "otel": {"agent_a": _otel(), "llm_backend": _otel()},
            "llm_meta": {"latency_ms": 1000, "total_tokens": 100, "otel": _otel()},
            "duration_seconds": 1.0,
            **kw,
        }

    reqs = [req(1, "expert_recruitment", "recruitment", 0.0)]
    t = 2.0 + jitter
    if topology == "horizontal":
        for i in range(4):
            reqs.append(req(len(reqs) + 1, "horizontal_discussion_round1", "decision", t))
            t += 3.0
    elif topology == "vertical":
        reqs.append(req(len(reqs) + 1, "vertical_solver_iter1", "decision", t))
        for j, role in enumerate(("critic", "executor", "researcher")):
            label = f"vertical_reviewer_{role}_iter1"
            reqs.append(req(len(reqs) + 1, label, "decision", t + 5.0 + j * 0.0004))
        t += 9.0
    else:
        for j in range(4):
            label = f"full_mesh_message_round1_agent{j}_to_agent{(j + 1) % 4}"
            reqs.append(req(len(reqs) + 1, label, "decision", t + j * 0.001))
        t += 3.0
    if topology != "vertical":
        reqs.append(req(len(reqs) + 1, "synthesize_discussion", "decision", t))
    reqs.append(req(len(reqs) + 1, "final_output", "synthesis", t + 3.0))
    return {
        "task_id": uid,
        "original_task": "||Synthetic task for " + category,
        "completed": True,
        "iterations": 1,
        "duration_seconds": round(t + 4.0, 2),
        "final_output": "done",
        "stages": {
            "recruitment": {
                "experts": [{"role": "critic", "endpoint": "http://172.23.0.20:8102/subtask"}],
                "communication_structure": topology,
            },
            "decision": {"structure_used": topology, "discussion_rounds": []},
            "execution": {"outputs": []},
            "evaluation": {"score": 90},
        },
        "iteration_history": [],
        "llm_requests": reqs,
    }


def _write_source(root: Path, extra_text: str = "") -> Path:
    tasks = root / "data" / "agentverse" / "balanced_agents4_experiment_2026-01-01_00-00-00"
    tasks = tasks / "tasks"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    n = 0
    for topology in gf.TOPOLOGIES:
        for category in CATEGORIES:
            for k in range(3):
                n += 1
                uid = f"{n:08x}-0000-4000-8000-{k:012x}"
                begin = start + timedelta(minutes=n)
                doc = _synthetic_response(topology, category, uid, begin, jitter=k * 0.5)
                doc["final_output"] += extra_text
                d = tasks / f"{begin:%Y-%m-%d_%H-%M-%S}_{category}_{uid}"
                d.mkdir(parents=True)
                with gzip.open(d / "response.json.gz", "wt", encoding="utf-8") as fh:
                    json.dump(doc, fh)
    return root


def _stub_events(response):
    return [{"t_ms": 0, "event": "complete", "data": response}]


def test_main_end_to_end_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setattr(gf, "load_events_builder", lambda: _stub_events)
    src = _write_source(tmp_path / "src")
    # Synthetic data does not reproduce the paper's Table 2, so the check must fail ...
    assert gf.main(["--source", str(src), "--out", str(tmp_path / "x")]) == 1
    assert not (tmp_path / "x").exists()
    # ... and --no-check writes anyway, byte-identically across runs.
    outs = []
    for name in ("a", "b"):
        out = tmp_path / name
        assert gf.main(["--source", str(src), "--out", str(out), "--no-check"]) == 0
        outs.append({p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()})
    assert outs[0] == outs[1]
    files = outs[0]
    assert len(files) == 12 * 2 + 1
    index = json.loads(files[Path("index.json")])
    assert index["schema_version"] == gf.SCHEMA_VERSION
    assert len(index["fixtures"]) == 12
    for entry in index["fixtures"]:
        text = files[Path(entry["files"]["response"])].decode("utf-8")
        assert gf.find_leaks(text) == []
        resp = json.loads(text)
        assert list(resp) == RESPONSE_KEYS
        assert resp["llm_requests"][0]["endpoint"] == "http://llm:8000/chat"
        assert entry["files"]["response_bytes"] == len(text.encode("utf-8"))
        assert entry["files"]["events"] == entry["files"]["response"].replace(
            ".response.", ".events."
        )
        assert entry["original_task"].startswith("Synthetic task")
        assert entry["matches_example_task"] is False
        expect_burst = entry["topology"] != "horizontal"
        assert (entry["discussion_iat"]["burst_fraction"] > 0) == expect_burst


def test_main_aborts_on_sensitive_data(tmp_path, monkeypatch):
    monkeypatch.setattr(gf, "load_events_builder", lambda: None)
    src = _write_source(tmp_path / "src", extra_text=" saved to /home/someone/out.txt")
    out = tmp_path / "out"
    assert gf.main(["--source", str(src), "--out", str(out), "--no-check"]) == 3
    assert not out.exists()


# ---------------------------------------------------------------------------
# Committed fixtures (runs in CI) and real data (skipped without data/att-paper)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not (FIXTURES_DIR / "index.json").exists(), reason="fixtures not generated yet")
def test_committed_fixtures_are_clean_and_consistent():
    index = json.loads((FIXTURES_DIR / "index.json").read_text(encoding="utf-8"))
    assert gf.find_leaks((FIXTURES_DIR / "index.json").read_text(encoding="utf-8")) == []
    combos = {(e["topology"], e["task"]) for e in index["fixtures"]}
    assert combos == {(t, k) for t in gf.TOPOLOGIES for k in gf.TASKS}
    for entry in index["fixtures"]:
        for key in ("response", "events"):
            rel = entry["files"][key]
            if rel is None:
                continue
            text = (FIXTURES_DIR / rel).read_text(encoding="utf-8")
            assert gf.find_leaks(text) == [], rel
            assert len(text.encode("utf-8")) == entry["files"][f"{key}_bytes"]
        resp = json.loads((FIXTURES_DIR / entry["files"]["response"]).read_text("utf-8"))
        assert list(resp) == RESPONSE_KEYS
        if entry["files"]["events"] is not None:
            events = json.loads((FIXTURES_DIR / entry["files"]["events"]).read_text("utf-8"))
            assert events[-1]["event"] == "complete"
            assert events[-1]["data"] == {"$ref": Path(entry["files"]["response"]).name}
            n_llm = sum(e["event"] == "llm_request" for e in events)
            assert n_llm == len(resp["llm_requests"])
        assert entry["files"]["response_bytes"] <= index["max_kb"] * 1024
        assert resp["stages"]["decision"]["structure_used"] == entry["topology"]
        iats = gf.discussion_iats(resp["llm_requests"], entry["topology"])
        assert gf.shows_expected_burst(entry["topology"], iats)
        assert len(iats) == entry["discussion_iat"]["n"]


@pytest.mark.skipif(not REAL_SOURCE.exists(), reason="data/att-paper not fetched")
def test_real_data_reproduces_table2_counts():
    runs, _ = gf.scan_source(REAL_SOURCE)
    stats = gf.dataset_stats(runs)
    assert [stats[t]["n_runs"] for t in gf.TOPOLOGIES] == [500, 481, 500]
    assert [stats[t]["n_iats"] for t in gf.TOPOLOGIES] == [6513, 7355, 14493]
    assert all(row["ok"] for row in gf.compare_with_paper(stats, gf.PAPER_TABLE2_FALLBACK))
