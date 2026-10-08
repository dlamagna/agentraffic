"""Tests for scripts/demo/sse_events.py (SSE replay reconstruction for the static demo).

The recorded paper data under data/ is gitignored, so these tests build small synthetic
responses that follow the real ``response.json`` schema. The last test also runs on the real
data when it is checked out locally, and is skipped otherwise.
"""

import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.demo.sse_events import (
    SERVER_ONLY_EVENTS,
    UI_HANDLED_EVENTS,
    build_events,
    load_response,
    main,
)

T0 = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
ROLES = ("planner", "researcher", "executor")
ROUNDS = 2
WORKFLOW_STAGES = ["recruitment", "decision", "execution", "evaluation"]
ROUND_EVENT = {
    "horizontal": "discussion_round",
    "full_mesh": "full_mesh_round",
    "vertical": "vertical_iteration",
}


# ---------------------------------------------------------------------------
# Synthetic response builder (mimics agents/agent_a/orchestrator.py output)
# ---------------------------------------------------------------------------


class _Run:
    def __init__(self):
        self.requests = []
        self.t = 0.0

    def _entry(self, iteration, stage, label, start, duration, role, source, response, **extra):
        entry = {
            "seq": len(self.requests) + 1,
            "iteration": iteration,
            "stage": stage,
            "label": label,
            "source": source,
            "prompt": f"prompt for {label}",
            "response": response,
            "endpoint": "http://llm:8000/chat",
            "error": False,
            "start_time_utc": (T0 + timedelta(seconds=start)).isoformat(),
            "request_id": f"r{len(self.requests) + 1:04d}",
            "llm_meta": {
                "latency_ms": int(duration * 1000),
                "queue_wait_s": 0.01,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "agent_role": role,
            "duration_seconds": round(duration, 2),
        }
        entry.update(extra)
        self.requests.append(entry)
        return entry

    def call(
        self,
        iteration,
        stage,
        label,
        duration=1.0,
        role="orchestrator",
        source="Agent A",
        response="ok",
        **extra,
    ):
        entry = self._entry(
            iteration, stage, label, self.t, duration, role, source, response, **extra
        )
        self.t += duration + 0.004
        return entry

    def parallel(self, iteration, stage, specs):
        """specs: list of (label, duration, role, source, response, extra); seq = finish order."""
        start = self.t
        entries = [
            self._entry(iteration, stage, label, start, dur, role, src, resp, **extra)
            for label, dur, role, src, resp, extra in sorted(specs, key=lambda s: s[1])
        ]
        self.t = start + max(s[1] for s in specs) + 0.004
        return entries


def make_response(topology, iterations=1):
    run = _Run()
    history = []
    final = {}
    for it in range(iterations):
        roles = list(ROLES) if it == iterations - 1 else list(reversed(ROLES))
        recruitment_json = {
            "experts": [
                {"role": r, "responsibilities": f"{r} duties (iter {it})", "contract": "c"}
                for r in roles
            ],
            "communication_structure": topology,
            "execution_order": roles,
            "reasoning": f"reasoning for iteration {it}",
        }
        run.call(
            it,
            "recruitment",
            "expert_recruitment",
            1.2,
            response="```json\n" + json.dumps(recruitment_json) + "\n```",
        )

        rounds = []
        if topology == "horizontal":
            for rnd in range(1, ROUNDS + 1):
                responses = []
                for idx, role in enumerate(roles):
                    text = f"{role} round {rnd}" + (" [CONSENSUS]" if rnd == ROUNDS else "")
                    run.call(
                        it,
                        "decision",
                        f"horizontal_discussion_round{rnd}",
                        1.0 + idx / 10,
                        role=role,
                        source=f"agent-b-{idx + 1}",
                        response=text,
                        round=rnd,
                    )
                    responses.append(
                        {"expert": role, "index": idx, "response": text, "consensus": rnd == ROUNDS}
                    )
                rounds.append({"round": rnd, "responses": responses})
            run.call(it, "decision", "synthesize_discussion", 1.5, response=f"decision {it}")
            final_decision, consensus = f"decision {it}", True
        elif topology == "full_mesh":
            for rnd in range(1, ROUNDS + 1):
                specs, messages = [], []
                for s, sender in enumerate(roles):
                    for r, receiver in enumerate(roles):
                        if s == r:
                            continue
                        text = f"{sender}->{receiver} r{rnd}" + (" **CONSENSUS**" if s else "")
                        label = f"full_mesh_message_round{rnd}_agent{s + 1}_to_agent{r + 1}"
                        extra = {"round": rnd, "sender_role": sender, "receiver_role": receiver}
                        specs.append(
                            (label, 0.5 + (s * 3 + r) / 10, sender, f"agent-b-{s + 1}", text, extra)
                        )
                        messages.append(
                            {
                                "sender": sender,
                                "sender_index": s,
                                "receiver": receiver,
                                "receiver_index": r,
                                "response": text,
                                "consensus": bool(s),
                            }
                        )
                run.parallel(it, "decision", specs)
                rounds.append({"round": rnd, "messages": messages, "all_consensus": False})
            run.call(it, "decision", "synthesize_discussion", 1.5, response=f"decision {it}")
            final_decision, consensus = f"decision {it}", False
        else:  # vertical
            solver, reviewers = roles[0], roles[1:]
            for k in range(1, ROUNDS + 1):
                proposal = f"proposal {k} " + "x" * 250
                run.call(
                    it,
                    "decision",
                    f"vertical_solver_iter{k}",
                    2.0,
                    role=solver,
                    source="agent-b-1",
                    response=proposal,
                    round=k,
                )
                critiques = {
                    reviewers[0]: "fine **APPROVED**",  # current regex: yes; recorded rule: no
                    reviewers[1]: "fine [APPROVED]",
                }
                run.parallel(
                    it,
                    "decision",
                    [
                        (
                            f"vertical_reviewer_{rev}_iter{k}",
                            1.0 + j / 10,
                            rev,
                            f"agent-b-{roles.index(rev) + 1}",
                            critiques[rev],
                            {"round": k},
                        )
                        for j, rev in enumerate(reversed(reviewers))
                    ],
                )
                rounds.append(
                    {
                        "iteration": k,
                        "proposal": proposal,
                        "reviewer_responses": [
                            {
                                "reviewer": rev,
                                "critique": critiques[rev],
                                "approved": rev != reviewers[0],
                            }
                            for rev in reviewers
                        ],
                        "all_approved": False,
                    }
                )
            final_decision, consensus = proposal, False

        exec_entries = run.parallel(
            it,
            "execution",
            [
                (f"execute_{role}", 3.0 - idx / 2, role, f"agent-b-{idx + 1}", f"{role} output", {})
                for idx, role in enumerate(roles)
            ],
        )
        outputs = [
            {
                "expert": e["agent_role"],
                "index": int(e["source"].rsplit("-", 1)[1]) - 1,
                "subtask": "subtask",
                "output": e["response"],
                "success": True,
            }
            for e in exec_entries
        ]
        is_final = it == iterations - 1
        evaluation = {
            "goal_achieved": is_final,
            "score": 85 if is_final else 40,
            "criteria": None,
            "rationale": None,
            "feedback": f"feedback {it}",
        }
        run.call(it, "evaluation", "evaluate_results", 1.1, response=json.dumps(evaluation))
        history.append(
            {
                "iteration": it,
                "duration_seconds": 10.0,
                "recruitment": {"experts": roles, "structure": topology},
                "decision": {"consensus": consensus, "rounds": len(rounds)},
                "execution": {"success": len(roles), "failures": 0},
                "evaluation": evaluation,
            }
        )
        final = {
            "recruitment": {
                "experts": [
                    {
                        "role": r,
                        "responsibilities": f"{r} duties (iter {it})",
                        "endpoint": f"http://agent-b-{i + 1}:8102/subtask",
                    }
                    for i, r in enumerate(roles)
                ],
                "communication_structure": topology,
                "reasoning": f"reasoning for iteration {it}",
            },
            "decision": {
                "final_decision": final_decision,
                "consensus_reached": consensus,
                "structure_used": topology,
                "discussion_rounds": rounds,
                "solver_role": roles[0] if topology == "vertical" else None,
                "reviewer_roles": roles[1:] if topology == "vertical" else roles,
            },
            "execution": {"outputs": outputs, "success_count": len(roles), "failure_count": 0},
            "evaluation": dict(evaluation, missing_aspects=[]),
        }

    run.call(iterations - 1, "synthesis", "final_output", 2.5, response="the final answer")
    return {
        "task_id": f"test-{topology}-{iterations}",
        "original_task": "Plan a school fair.",
        "completed": True,
        "iterations": iterations,
        "duration_seconds": 10.0 * iterations,
        "final_output": "the final answer",
        "stages": final,
        "iteration_history": history,
        "llm_requests": run.requests,
    }


CASES = [
    ("horizontal", 1),
    ("full_mesh", 1),
    ("vertical", 1),
    ("horizontal", 2),
    ("full_mesh", 2),
    ("vertical", 2),
]


@pytest.fixture(params=CASES, ids=[f"{t}-{n}it" for t, n in CASES])
def case(request):
    topology, iterations = request.param
    response = make_response(topology, iterations)
    return topology, iterations, response, build_events(response)


def _of(events, name, **match):
    return [
        e
        for e in events
        if e["event"] == name and all(e["data"].get(k) == v for k, v in match.items())
    ]


# ---------------------------------------------------------------------------
# Generic invariants
# ---------------------------------------------------------------------------


def test_events_sorted_and_end_with_complete(case):
    _, _, response, events = case
    assert all(set(e) == {"t_ms", "event", "data"} for e in events)
    times = [e["t_ms"] for e in events]
    assert all(isinstance(t, int) for t in times)
    assert times[0] == 0
    assert times == sorted(times)
    assert events[-1]["event"] == "complete"
    assert events[-1]["data"] is response
    assert sum(e["event"] == "complete" for e in events) == 1
    json.dumps(events)  # must be serialisable as events.json


def test_one_llm_request_per_entry_in_seq_order(case):
    _, _, response, events = case
    emitted = [e["data"] for e in events if e["event"] == "llm_request"]
    assert len(emitted) == len(response["llm_requests"])
    assert all(a is b for a, b in zip(emitted, response["llm_requests"]))


def test_llm_request_emitted_at_completion_time(case):
    _, _, _, events = case
    for e in _of(events, "llm_request"):
        start = datetime.fromisoformat(e["data"]["start_time_utc"])
        expected = round(((start - T0).total_seconds() + e["data"]["duration_seconds"]) * 1000)
        assert e["t_ms"] == expected


def test_event_names_are_known(case):
    topology, _, _, events = case
    names = {e["event"] for e in events}
    assert names <= UI_HANDLED_EVENTS | SERVER_ONLY_EVENTS
    if topology == "full_mesh":
        # The real orchestrator sends full_mesh_round, which handleStreamEvent ignores.
        assert names - UI_HANDLED_EVENTS == {"full_mesh_round"}
    else:
        assert names <= UI_HANDLED_EVENTS


def test_stage_start_complete_pairing(case):
    _, iterations, _, events = case
    open_stage = None
    sequence = []
    for e in events:
        data = e["data"]
        if e["event"] == "stage_start":
            assert open_stage is None, f"{data['stage']} started inside {open_stage}"
            open_stage = (data["stage"], data["iteration"])
            sequence.append(open_stage)
        elif e["event"] == "stage_complete":
            assert open_stage == (data["stage"], data["iteration"])
            open_stage = None
        elif e["event"] == "llm_request":
            # every LLM call happens inside its own stage
            assert open_stage == (data["stage"], data["iteration"])
        elif e["event"] in ("iteration_start", "iteration_complete", "complete"):
            assert open_stage is None
    assert open_stage is None
    expected = [(s, it) for it in range(iterations) for s in WORKFLOW_STAGES]
    expected.append(("synthesis", iterations - 1))
    assert sequence == expected
    for e in _of(events, "stage_start") + _of(events, "stage_complete"):
        assert (
            e["data"]["stage_number"]
            == (WORKFLOW_STAGES + ["synthesis"]).index(e["data"]["stage"]) + 1
        )


def test_iteration_events(case):
    _, iterations, response, events = case
    starts = _of(events, "iteration_start")
    completes = _of(events, "iteration_complete")
    assert [e["data"]["iteration"] for e in starts] == list(range(iterations))
    assert all(e["data"]["max_iterations"] >= iterations for e in starts)
    assert [len(e["data"]["iteration_history"]) for e in completes] == list(
        range(1, iterations + 1)
    )
    assert completes[-1]["data"]["iteration_history"] == response["iteration_history"]


def test_round_events(case):
    topology, iterations, _, events = case
    name = ROUND_EVENT[topology]
    for other in set(ROUND_EVENT.values()) - {name}:
        assert not _of(events, other)
    for it in range(iterations):
        round_events = _of(events, name, iteration=it)
        assert len(round_events) == ROUNDS
        # each round event follows the last LLM call of its round and precedes the next round
        for e in round_events:
            idx = events.index(e)
            rnd = e["data"]["solver_iteration" if topology == "vertical" else "round"]
            before = [
                x["data"].get("round")
                for x in events[:idx]
                if x["event"] == "llm_request"
                and x["data"]["iteration"] == it
                and x["data"]["stage"] == "decision"
            ]
            after = [
                x["data"].get("round")
                for x in events[idx:]
                if x["event"] == "llm_request"
                and x["data"]["iteration"] == it
                and x["data"]["stage"] == "decision"
            ]
            assert before[-1] == rnd
            assert rnd not in after


def test_execution_results(case):
    _, iterations, _, events = case
    for it in range(iterations):
        results = _of(events, "execution_result", iteration=it)
        assert [r["data"]["completed"] for r in results] == list(range(1, len(ROLES) + 1))
        assert {r["data"]["total"] for r in results} == {len(ROLES)}
        for r in results:
            idx = events.index(r)
            prev = events[idx - 1]
            assert prev["event"] == "llm_request"
            assert prev["data"]["label"] == f"execute_{r['data']['expert']}"
            assert r["data"]["output_preview"] == prev["data"]["response"][:200]
            assert r["data"]["success"] is True


def test_stage_complete_payloads(case):
    topology, iterations, response, events = case
    for it in range(iterations):
        hist = response["iteration_history"][it]
        (rec,) = _of(events, "stage_complete", stage="recruitment", iteration=it)
        assert [x["role"] for x in rec["data"]["experts"]] == hist["recruitment"]["experts"]
        assert all(set(x) == {"role", "responsibilities"} for x in rec["data"]["experts"])
        assert rec["data"]["communication_structure"] == topology
        assert rec["data"]["reasoning"] == f"reasoning for iteration {it}"

        (dec,) = _of(events, "stage_complete", stage="decision", iteration=it)
        assert dec["data"]["structure"] == topology
        assert dec["data"]["rounds"] == ROUNDS
        assert dec["data"]["consensus_reached"] == hist["decision"]["consensus"]

        (exe,) = _of(events, "stage_complete", stage="execution", iteration=it)
        assert (exe["data"]["success_count"], exe["data"]["failure_count"]) == (len(ROLES), 0)
        assert exe["data"]["total"] == len(ROLES)

        (ev,) = _of(events, "stage_complete", stage="evaluation", iteration=it)
        assert ev["data"]["score"] == hist["evaluation"]["score"]
        assert ev["data"]["should_iterate"] is (it < iterations - 1)
        assert ev["data"]["feedback"] == hist["evaluation"]["feedback"]

    (syn,) = _of(events, "stage_complete", stage="synthesis")
    assert syn["data"]["final_output"] == response["final_output"]


# ---------------------------------------------------------------------------
# Topology- and iteration-specific payloads
# ---------------------------------------------------------------------------


def test_final_iteration_uses_recorded_stages():
    response = make_response("horizontal", 1)
    events = build_events(response)
    rounds = response["stages"]["decision"]["discussion_rounds"]
    payloads = [e["data"] for e in _of(events, "discussion_round")]
    assert [p["responses"] for p in payloads] == [r["responses"] for r in rounds]
    assert [p["consensus"] for p in payloads] == [False, True]
    (rec,) = _of(events, "stage_complete", stage="recruitment")
    assert rec["data"]["experts"][0] == {
        "role": "planner",
        "responsibilities": "planner duties (iter 0)",
    }


def test_vertical_iteration_payload():
    response = make_response("vertical", 1)
    events = build_events(response)
    first = _of(events, "vertical_iteration")[0]["data"]
    assert first["solver_iteration"] == 1
    assert len(first["proposal"]) == 203 and first["proposal"].endswith("...")
    assert [r["reviewer"] for r in first["reviewer_responses"]] == ["researcher", "executor"]
    assert first["all_approved"] is False


def test_earlier_iterations_rebuilt_from_history_and_requests():
    response = make_response("vertical", 2)
    events = build_events(response)
    (rec,) = _of(events, "stage_complete", stage="recruitment", iteration=0)
    assert rec["data"]["experts"] == [
        {"role": r, "responsibilities": f"{r} duties (iter 0)"} for r in reversed(ROLES)
    ]
    first = _of(events, "vertical_iteration", iteration=0)[0]["data"]
    # solver is the first recruited expert of iteration 0; reviewers in expert order
    assert [r["reviewer"] for r in first["reviewer_responses"]] == ["researcher", "planner"]
    # recorded runs flag approval only for the literal "[APPROVED]" marker
    assert [r["approved"] for r in first["reviewer_responses"]] == [False, True]
    assert first["proposal"].startswith("proposal 1 ")


def test_rebuild_matches_recorded_stages(case):
    """Payloads rebuilt without `stages` equal those taken from the recorded stages."""
    _, _, response, events = case
    stripped = dict(response, stages={})
    rebuilt = build_events(stripped)
    assert [(e["t_ms"], e["event"]) for e in rebuilt] == [(e["t_ms"], e["event"]) for e in events]
    for a, b in zip(events[:-1], rebuilt[:-1]):
        assert a["data"] == b["data"], a["event"]


def test_full_mesh_messages_sorted_by_sender_receiver():
    response = make_response("full_mesh", 2)
    events = build_events(response)
    for e in _of(events, "full_mesh_round"):
        keys = [(m["sender_index"], m["receiver_index"]) for m in e["data"]["messages"]]
        assert keys == sorted(keys) and len(keys) == len(ROLES) * (len(ROLES) - 1)
        assert e["data"]["consensus"] is False


def test_failed_call_is_llm_error():
    response = make_response("horizontal", 1)
    response["llm_requests"][3]["error"] = True
    events = build_events(response)
    errors = _of(events, "llm_error")
    assert len(errors) == 1 and errors[0]["data"] is response["llm_requests"][3]


def test_cli_summary(tmp_path, capsys):
    path = tmp_path / "response.json.gz"
    response = make_response("full_mesh", 1)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(response, fh)
    assert load_response(str(path)) == response
    assert main([str(path), "--timeline"]) == 0
    out = capsys.readouterr().out
    assert "topology=full_mesh" in out
    assert "full_mesh_round" in out
    assert "complete" in out


# ---------------------------------------------------------------------------
# Real recorded data (local only; data/ is gitignored)
# ---------------------------------------------------------------------------

REAL_DATA = Path(__file__).resolve().parents[1] / "data" / "att-paper" / "data" / "agentverse"


def test_real_recorded_runs():
    files = sorted(REAL_DATA.glob("balanced_agents4_*/tasks/*/response.json.gz"))
    if not files:
        pytest.skip("paper data not checked out under data/att-paper")
    for path in files[:: max(1, len(files) // 60)]:
        response = load_response(str(path))
        events = build_events(response)
        times = [e["t_ms"] for e in events]
        assert times == sorted(times) and times[0] == 0, path
        assert events[-1]["event"] == "complete" and events[-1]["data"] is response, path
        emitted = [e["data"] for e in events if e["event"] in ("llm_request", "llm_error")]
        assert len(emitted) == len(response["llm_requests"]), path
        assert {e["event"] for e in events} <= UI_HANDLED_EVENTS | SERVER_ONLY_EVENTS, path
