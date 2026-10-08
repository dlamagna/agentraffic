"""Reconstruct the SSE progress-event stream of a recorded AgentVerse run.

The paper's runs were recorded as ``response.json`` only; the SSE stream that
``POST /agentverse`` with ``stream: true`` sends to the UI was not saved. This module rebuilds
it from the response's ``stages``, ``iteration_history`` and the timing of ``llm_requests[]``,
so that the static demo can replay a run through ``handleStreamEvent(event, data)`` in
``ui/playground/js/streaming.js``.

Event sequence (mirrors ``AgentVerseOrchestrator.run_workflow`` and ``server.py``)::

    per iteration i:
      iteration_start      {iteration, max_iterations, message}
      stage_start          {stage: "recruitment", stage_number: 1, iteration, message}
      llm_request          <llm_requests[] entry, unmodified>
      stage_complete       {stage, stage_number, iteration, experts: [{role, responsibilities}],
                            communication_structure, reasoning}
      stage_start          {stage: "decision", stage_number: 2, iteration, message, structure}
        horizontal: per round: llm_request x N (sequential), then
                    discussion_round {stage, round, iteration, consensus,
                                      responses: [{expert, index, response, consensus}]}
                    then llm_request (synthesize_discussion)
        full_mesh:  per round: llm_request x N(N-1) (parallel), then
                    full_mesh_round  {stage, round, iteration, consensus,
                                      messages: [{sender, sender_index, receiver,
                                                  receiver_index, response, consensus}]}
                    then llm_request (synthesize_discussion)
        vertical:   per solver iteration: llm_request (solver), llm_request x reviewers, then
                    vertical_iteration {stage, iteration, solver_iteration, proposal (<=200
                                        chars + "..."), reviewer_responses: [{reviewer,
                                        critique, approved}], all_approved}
      stage_complete       {stage, stage_number, iteration, consensus_reached, structure, rounds}
      stage_start          {stage: "execution", stage_number: 3, iteration, message,
                            expert_count}
      per finished subtask: llm_request, then
      execution_result     {stage, iteration, expert, success, output_preview, completed, total}
      stage_complete       {stage, stage_number, iteration, success_count, failure_count, total}
      stage_start          {stage: "evaluation", stage_number: 4, iteration, message}
      llm_request
      stage_complete       {stage, stage_number, iteration, goal_achieved, score,
                            should_iterate, feedback}
      iteration_complete   {iteration_history: iteration_history[:i + 1]}
    stage_start            {stage: "synthesis", stage_number: 5, iteration, message}
    llm_request
    stage_complete         {stage, stage_number, iteration, final_output}
    complete               <the full response, exactly as server.py sends it>

A failed LLM call (``error: true``) is emitted as ``llm_error``, as the orchestrator does.

Timing model (``t_ms`` = ms since the earliest ``llm_requests[].start_time_utc``):

* ``llm_request`` is sent when the call returns (``_record_llm_request`` runs after the call),
  so ``t = start_time_utc + duration_seconds``. Requests are emitted in ``seq`` order, which
  is the order the orchestrator recorded and streamed them.
* Every other event is emitted right after the previous step in the orchestrator's control
  flow, so it takes the time of the latest preceding event: a ``stage_start`` fires as soon
  as the previous stage completes (before Agent A builds the stage's first prompt), and a
  ``stage_complete`` / round event / ``execution_result`` fires when its last LLM call
  returns.
* ``t_ms`` is forced to be non-decreasing. This only absorbs the skew from ``duration_seconds``
  being rounded to 10 ms: on the paper runs, 48 of 42,837 requests move, by at most 9 ms.

Approximations (things the recording does not contain):

* Exact instants of non-LLM events: Agent A's own processing between calls is not recorded.
  It is a few ms in practice, apart from evaluation-prompt tokenisation (~1 s), which is
  correctly placed after the evaluation ``stage_start``.
* ``iteration_start`` and the first ``stage_start`` happen a few ms before the first LLM call
  and are clamped to ``t = 0``.
* ``max_iterations`` (a request field) is not stored in the response. ``DEFAULT_MAX_ITERATIONS``
  (the server default, 3) is used, raised to the number of iterations actually run, unless
  the response carries ``max_iterations``.
* ``stages`` only holds the *final* iteration. For earlier iterations of multi-iteration
  runs the payloads are rebuilt from ``iteration_history`` (roles, structure, counts, score,
  feedback) and from the iteration's ``llm_requests``: expert responsibilities and recruitment
  reasoning are re-parsed from the recruitment LLM response, and discussion responses /
  critiques / execution outputs are taken from the LLM responses. On the 1,481 paper runs
  these sources are byte-identical to what ``stages`` records for the final iteration.
  Reviewer approval is rebuilt with the ``"[APPROVED]"`` substring rule. The orchestrator
  that recorded the paper runs evidently used this rule: it matches all 4,329 recorded
  reviewer verdicts, while the current ``_APPROVED_SIGNAL_RE`` matches only 2,841.
* ``full_mesh_round`` and ``llm_error`` are reproduced under the server's names although
  ``handleStreamEvent`` ignores them (see ``SERVER_ONLY_EVENTS``). Full-mesh rounds
  therefore only appear in the UI once ``complete`` arrives, as with the live server.
* Not reconstructed: ``workflow_error`` / ``error`` (no failed runs were recorded) and the
  solo-mode (0 sub-agents) ``discussion_round`` events (no solo runs were recorded; the
  solo decision stage is replayed as plain ``llm_request`` events).

CLI (spot checks)::

    python -m scripts.demo.sse_events <response.json[.gz]> [...] [--timeline]
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

#: Events ``handleStreamEvent`` acts on, plus ``complete``, which the stream reader handles.
UI_HANDLED_EVENTS = frozenset(
    {
        "iteration_start",
        "stage_start",
        "stage_complete",
        "llm_request",
        "discussion_round",
        "execution_result",
        "vertical_iteration",
        "iteration_complete",
        "error",
        "complete",
    }
)

#: Events the real server sends but ``handleStreamEvent`` silently ignores.
SERVER_ONLY_EVENTS = frozenset({"full_mesh_round", "llm_error"})

#: Server default for ``max_iterations`` (``server.py``); not recorded in ``response.json``.
DEFAULT_MAX_ITERATIONS = 3

_WORKFLOW_STAGES = ("recruitment", "decision", "execution", "evaluation")
_VALID_ROLES = {"planner", "researcher", "executor", "critic", "summarizer"}

# Copied from agents/agent_a/orchestrator.py (importing it would pull in OpenTelemetry etc.).
_CONSENSUS_SIGNAL_RE = re.compile(r"(?i)(\[CONSENSUS\]|\*{1,2}CONSENSUS[*:]*\*{0,2})")
_APPROVED_MARKER = "[APPROVED]"
_MESH_LABEL_RE = re.compile(r"_agent(\d+)_to_agent(\d+)$")
_TRAILING_INT_RE = re.compile(r"(\d+)$")


def build_events(response: dict) -> list[dict]:
    """Return events sorted by t_ms, each {"t_ms": int, "event": str, "data": dict}."""
    return _EventBuilder(response).build()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _parse_json_response(text: Any) -> dict:
    """Lenient JSON extraction, same strategy as ``_parse_json_response`` in the orchestrator."""
    if not isinstance(text, str):
        return {}
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    candidates = [text]
    start, end = text.find("{"), text.rfind("}") + 1
    if start != -1 and end > start:
        candidates.append(text[start:end])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _agent_index(entry: dict) -> int | None:
    """Expert index from ``source`` ("agent-b-<index + 1>")."""
    match = _TRAILING_INT_RE.search(str(entry.get("source") or ""))
    return int(match.group(1)) - 1 if match else None


def _response_text(entry: dict) -> str:
    value = entry.get("response")
    return value if isinstance(value, str) else ""


def _has_consensus(text: str) -> bool:
    return bool(_CONSENSUS_SIGNAL_RE.search(text or ""))


def _is_approved(text: str) -> bool:
    return _APPROVED_MARKER in (text or "")


def _preview_proposal(proposal: str) -> str:
    return proposal[:200] + "..." if len(proposal) > 200 else proposal


def _decision_kind(entries: list[dict], fallback: str | None) -> str:
    """Which decision code path ran, judged from the request labels."""
    labels = [str(e.get("label") or "") for e in entries]
    if any(lbl.startswith("full_mesh_message") for lbl in labels):
        return "full_mesh"
    if any(lbl.startswith("vertical_") for lbl in labels):
        return "vertical"
    if any(lbl.startswith("horizontal_discussion") for lbl in labels):
        return "horizontal"
    if any(lbl.startswith("solo_") for lbl in labels):
        return "solo"
    return fallback or "horizontal"


def _recruitment_reasoning_fallback(structure: str, roles: list[str]) -> str:
    desc = {
        "horizontal": "democratic discussion among all experts",
        "full_mesh": "directed all-to-all discussion among all experts",
    }.get(structure, "solver proposes, reviewers critique, solver refines")
    return (
        f"Selected {structure} communication structure ({desc}) "
        f"with {len(roles)} expert(s): {', '.join(roles)}."
    )


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class _EventBuilder:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.stages = response.get("stages") or {}
        self.history = [h for h in (response.get("iteration_history") or []) if isinstance(h, dict)]
        self.requests = sorted(
            (e for e in (response.get("llm_requests") or []) if isinstance(e, dict)),
            key=lambda e: e.get("seq") or 0,
        )
        self.events: list[dict] = []
        self._t_ms = 0
        self._end_s: dict[int, float] = {}
        self._compute_request_times()

        iteration_ids = {
            int(e.get("iteration") or 0) for e in self.requests if e.get("stage") != "synthesis"
        }
        iteration_ids.update(int(h.get("iteration") or 0) for h in self.history)
        self.iterations = sorted(iteration_ids)
        n_run = int(response.get("iterations") or len(self.iterations) or 1)
        self.final_iteration = n_run - 1
        recorded_max = response.get("max_iterations")
        self.max_iterations = max(
            int(recorded_max) if isinstance(recorded_max, int) else DEFAULT_MAX_ITERATIONS,
            n_run,
            len(self.iterations),
        )

    # -- timing ---------------------------------------------------------------

    def _compute_request_times(self) -> None:
        starts = [_parse_ts(e.get("start_time_utc")) for e in self.requests]
        known = [s for s in starts if s is not None]
        t0 = min(known) if known else 0.0
        prev_end = 0.0
        for entry, start in zip(self.requests, starts):
            rel_start = start - t0 if start is not None else prev_end
            try:
                duration = float(entry.get("duration_seconds") or 0.0)
            except (TypeError, ValueError):
                duration = 0.0
            end = rel_start + max(duration, 0.0)
            self._end_s[id(entry)] = end
            prev_end = max(prev_end, end)

    def _emit(self, event: str, data: dict, t_s: float | None = None) -> None:
        """Append an event at ``t_s`` seconds (default: now), keeping t_ms non-decreasing."""
        if t_s is not None:
            self._t_ms = max(self._t_ms, int(round(t_s * 1000)))
        self.events.append({"t_ms": self._t_ms, "event": event, "data": data})

    def _llm(self, entry: dict) -> None:
        event = "llm_error" if entry.get("error") else "llm_request"
        self._emit(event, entry, self._end_s[id(entry)])

    # -- lookups --------------------------------------------------------------

    def _history_pos(self, iteration: int) -> int | None:
        for pos, h in enumerate(self.history):
            if int(h.get("iteration") or 0) == iteration:
                return pos
        return None

    def _stage(self, name: str) -> dict:
        value = self.stages.get(name)
        return value if isinstance(value, dict) else {}

    # -- top level ------------------------------------------------------------

    def build(self) -> list[dict]:
        groups: dict[int, dict[str, list[dict]]] = {}
        synthesis: list[dict] = []
        for entry in self.requests:
            if entry.get("stage") == "synthesis":
                synthesis.append(entry)
                continue
            iteration = int(entry.get("iteration") or 0)
            stage = str(entry.get("stage") or "")
            groups.setdefault(iteration, {}).setdefault(stage, []).append(entry)

        for iteration in self.iterations:
            self._iteration(iteration, groups.get(iteration, {}))

        if synthesis or self.response.get("completed"):
            self._synthesis(synthesis)

        self._emit("complete", self.response)
        return self.events

    def _iteration(self, iteration: int, groups: dict[str, list[dict]]) -> None:
        pos = self._history_pos(iteration)
        hist = self.history[pos] if pos is not None else {}
        final = iteration == self.final_iteration

        self._emit(
            "iteration_start",
            {
                "iteration": iteration,
                "max_iterations": self.max_iterations,
                "message": f"Starting iteration {iteration + 1} of {self.max_iterations}...",
            },
        )
        experts, structure = self._recruitment(
            iteration, groups.get("recruitment", []), hist, final
        )
        self._decision(iteration, groups.get("decision", []), hist, final, structure)
        self._execution(iteration, groups.get("execution", []), hist, final, experts)
        self._evaluation(iteration, groups.get("evaluation", []), hist, final)

        # Stages the orchestrator does not produce; keep one event per request regardless.
        for stage, entries in groups.items():
            if stage not in _WORKFLOW_STAGES:
                for entry in entries:
                    self._llm(entry)

        if pos is not None:
            self._emit("iteration_complete", {"iteration_history": self.history[: pos + 1]})

    # -- stage 1: recruitment -------------------------------------------------

    def _recruitment(
        self, iteration: int, entries: list[dict], hist: dict, final: bool
    ) -> tuple[list[dict], str]:
        self._emit(
            "stage_start",
            {
                "stage": "recruitment",
                "stage_number": 1,
                "iteration": iteration,
                "message": "Analyzing task and recruiting expert agents...",
            },
        )
        for entry in entries:
            self._llm(entry)

        recorded = self._stage("recruitment")
        if final and isinstance(recorded.get("experts"), list):
            experts = [
                {"role": e.get("role"), "responsibilities": e.get("responsibilities", "")}
                for e in recorded["experts"]
                if isinstance(e, dict)
            ]
            structure = recorded.get("communication_structure") or "horizontal"
            reasoning = recorded.get("reasoning") or ""
        else:
            experts, structure, reasoning = self._rebuild_recruitment(entries, hist)

        self._emit(
            "stage_complete",
            {
                "stage": "recruitment",
                "stage_number": 1,
                "iteration": iteration,
                "experts": experts,
                "communication_structure": structure,
                "reasoning": reasoning,
            },
        )
        return experts, structure

    def _rebuild_recruitment(self, entries: list[dict], hist: dict) -> tuple[list[dict], str, str]:
        parsed = _parse_json_response(_response_text(entries[-1])) if entries else {}
        raw = [x for x in parsed.get("experts") or [] if isinstance(x, dict)]
        rec_hist = hist.get("recruitment") if isinstance(hist.get("recruitment"), dict) else {}
        roles = rec_hist.get("experts")
        if not isinstance(roles, list):
            roles = [str(x.get("role", "executor")).strip().lower() for x in raw]
            roles = [r if r in _VALID_ROLES else "executor" for r in roles]
        experts = [
            {
                "role": role,
                "responsibilities": (
                    raw[idx].get("responsibilities", "")
                    if idx < len(raw)
                    else "Execute an assigned subtask thoroughly"
                ),
            }
            for idx, role in enumerate(roles)
        ]
        structure = rec_hist.get("structure") or parsed.get("communication_structure")
        structure = str(structure or "horizontal").lower()
        reasoning = str(parsed.get("reasoning") or "").strip()
        if not reasoning:
            reasoning = _recruitment_reasoning_fallback(structure, [str(r) for r in roles])
        return experts, structure, reasoning

    # -- stage 2: decision ----------------------------------------------------

    def _decision(
        self, iteration: int, entries: list[dict], hist: dict, final: bool, structure: str
    ) -> None:
        self._emit(
            "stage_start",
            {
                "stage": "decision",
                "stage_number": 2,
                "iteration": iteration,
                "message": f"Starting {structure} decision-making...",
                "structure": structure,
            },
        )

        recorded = self._stage("decision") if final else {}
        kind = _decision_kind(entries, recorded.get("structure_used") or structure)
        recorded_rounds = [
            r for r in recorded.get("discussion_rounds") or [] if isinstance(r, dict)
        ]
        round_consensus: list[bool] = []

        def flush(round_num: Any, group: list[dict]) -> None:
            event, payload = self._round_event(kind, iteration, round_num, group, recorded_rounds)
            round_consensus.append(bool(payload.get("consensus", payload.get("all_approved"))))
            self._emit(event, payload)

        current_round: Any = None
        group: list[dict] = []
        for entry in entries:
            round_num = (
                entry.get("round") if kind in ("horizontal", "full_mesh", "vertical") else None
            )
            if group and round_num != current_round:
                flush(current_round, group)
                group = []
            self._llm(entry)
            if round_num is not None:
                current_round = round_num
                group.append(entry)
        if group:
            flush(current_round, group)

        dec_hist = hist.get("decision") if isinstance(hist.get("decision"), dict) else {}
        if final and recorded:
            consensus = bool(recorded.get("consensus_reached"))
            rounds = len(recorded_rounds)
        elif dec_hist:
            consensus = bool(dec_hist.get("consensus"))
            rounds = int(dec_hist.get("rounds") or 0)
        else:
            consensus = any(round_consensus)
            rounds = len(round_consensus)
        self._emit(
            "stage_complete",
            {
                "stage": "decision",
                "stage_number": 2,
                "iteration": iteration,
                "consensus_reached": consensus,
                "structure": recorded.get("structure_used") or kind,
                "rounds": rounds,
            },
        )

    def _round_event(
        self,
        kind: str,
        iteration: int,
        round_num: Any,
        group: list[dict],
        recorded_rounds: list[dict],
    ) -> tuple[str, dict]:
        if kind == "vertical":
            rec = next((r for r in recorded_rounds if r.get("iteration") == round_num), None)
            if rec is not None:
                proposal = str(rec.get("proposal") or "")
                reviews = list(rec.get("reviewer_responses") or [])
                all_approved = bool(rec.get("all_approved"))
            else:
                solver = [e for e in group if str(e.get("label", "")).startswith("vertical_solver")]
                proposal = _response_text(solver[-1]) if solver else ""
                reviewer_entries = sorted(
                    (e for e in group if all(e is not s for s in solver)),
                    key=lambda e: (_agent_index(e) is None, _agent_index(e) or 0),
                )
                reviews = [
                    {
                        "reviewer": e.get("agent_role"),
                        "critique": _response_text(e),
                        "approved": _is_approved(_response_text(e)),
                    }
                    for e in reviewer_entries
                ]
                all_approved = all(r["approved"] for r in reviews)
            return "vertical_iteration", {
                "stage": "decision",
                "iteration": iteration,
                "solver_iteration": round_num,
                "proposal": _preview_proposal(proposal),
                "reviewer_responses": reviews,
                "all_approved": all_approved,
            }

        rec = next((r for r in recorded_rounds if r.get("round") == round_num), None)
        if kind == "full_mesh":
            if rec is not None:
                messages = list(rec.get("messages") or [])
                consensus = bool(
                    rec.get(
                        "all_consensus",
                        bool(messages) and all(m.get("consensus") for m in messages),
                    )
                )
            else:
                messages = sorted(
                    (self._mesh_message(e) for e in group),
                    key=lambda m: (m["sender_index"], m["receiver_index"]),
                )
                consensus = bool(messages) and all(m["consensus"] for m in messages)
            return "full_mesh_round", {
                "stage": "decision",
                "round": round_num,
                "iteration": iteration,
                "messages": messages,
                "consensus": consensus,
            }

        if rec is not None:
            responses = list(rec.get("responses") or [])
        else:
            responses = [
                {
                    "expert": e.get("agent_role"),
                    "index": _agent_index(e),
                    "response": _response_text(e),
                    "consensus": _has_consensus(_response_text(e)),
                }
                for e in group
            ]
        return "discussion_round", {
            "stage": "decision",
            "round": round_num,
            "iteration": iteration,
            "responses": responses,
            "consensus": all(bool(r.get("consensus")) for r in responses),
        }

    @staticmethod
    def _mesh_message(entry: dict) -> dict:
        match = _MESH_LABEL_RE.search(str(entry.get("label") or ""))
        sender_index = int(match.group(1)) - 1 if match else (_agent_index(entry) or 0)
        receiver_index = int(match.group(2)) - 1 if match else 0
        text = _response_text(entry)
        return {
            "sender": entry.get("sender_role") or entry.get("agent_role"),
            "sender_index": sender_index,
            "receiver": entry.get("receiver_role"),
            "receiver_index": receiver_index,
            "response": text,
            "consensus": _has_consensus(text),
        }

    # -- stage 3: execution ---------------------------------------------------

    def _execution(
        self, iteration: int, entries: list[dict], hist: dict, final: bool, experts: list[dict]
    ) -> None:
        self._emit(
            "stage_start",
            {
                "stage": "execution",
                "stage_number": 3,
                "iteration": iteration,
                "message": f"Executing tasks with {len(experts)} agents...",
                "expert_count": len(experts),
            },
        )
        total = len(experts) or max(len(entries), 1)
        recorded = self._stage("execution") if final else {}
        pending = [o for o in recorded.get("outputs") or [] if isinstance(o, dict)]
        completed = 0
        successes = failures = 0

        def emit_result(output: dict) -> None:
            nonlocal completed, successes, failures
            completed += 1
            if output.get("success"):
                successes += 1
            else:
                failures += 1
            self._emit(
                "execution_result",
                {
                    "stage": "execution",
                    "iteration": iteration,
                    "expert": output.get("expert"),
                    "success": output.get("success"),
                    "output_preview": str(output.get("output") or "")[:200],
                    "completed": completed,
                    "total": total,
                },
            )

        for entry in entries:
            self._llm(entry)
            output = self._pop_output(pending, entry) if final else None
            if output is None:
                output = {
                    "expert": entry.get("agent_role"),
                    "output": _response_text(entry),
                    "success": not entry.get("error"),
                }
            emit_result(output)
        for output in pending:  # outputs without an LLM call (e.g. invalid endpoint)
            emit_result(output)

        exec_hist = hist.get("execution") if isinstance(hist.get("execution"), dict) else {}
        if final and recorded:
            successes = int(recorded.get("success_count") or 0)
            failures = int(recorded.get("failure_count") or 0)
        elif exec_hist:
            successes = int(exec_hist.get("success") or 0)
            failures = int(exec_hist.get("failures") or 0)
        self._emit(
            "stage_complete",
            {
                "stage": "execution",
                "stage_number": 3,
                "iteration": iteration,
                "success_count": successes,
                "failure_count": failures,
                "total": successes + failures,
            },
        )

    @staticmethod
    def _pop_output(pending: list[dict], entry: dict) -> dict | None:
        """Take the recorded output produced by this request (match by agent index, then role)."""
        index = _agent_index(entry)
        role = entry.get("agent_role")
        for matches in (
            lambda o: o.get("index") == index and o.get("expert") == role,
            lambda o: o.get("expert") == role,
        ):
            for pos, output in enumerate(pending):
                if matches(output):
                    return pending.pop(pos)
        return None

    # -- stage 4: evaluation --------------------------------------------------

    def _evaluation(self, iteration: int, entries: list[dict], hist: dict, final: bool) -> None:
        self._emit(
            "stage_start",
            {
                "stage": "evaluation",
                "stage_number": 4,
                "iteration": iteration,
                "message": "Evaluating results and determining if iteration is needed...",
            },
        )
        for entry in entries:
            self._llm(entry)
        evaluation = hist.get("evaluation") if isinstance(hist.get("evaluation"), dict) else None
        if evaluation is None:
            evaluation = self._stage("evaluation") if final else {}
        self._emit(
            "stage_complete",
            {
                "stage": "evaluation",
                "stage_number": 4,
                "iteration": iteration,
                "goal_achieved": bool(evaluation.get("goal_achieved")),
                "score": evaluation.get("score", 0),
                "should_iterate": not final,
                "feedback": evaluation.get("feedback") or "",
            },
        )

    # -- stage 5: synthesis ---------------------------------------------------

    def _synthesis(self, entries: list[dict]) -> None:
        self._emit(
            "stage_start",
            {
                "stage": "synthesis",
                "stage_number": 5,
                "iteration": self.final_iteration,
                "message": "Generating final synthesized output...",
            },
        )
        for entry in entries:
            self._llm(entry)
        self._emit(
            "stage_complete",
            {
                "stage": "synthesis",
                "stage_number": 5,
                "iteration": self.final_iteration,
                "final_output": self.response.get("final_output") or "",
            },
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_response(path: str) -> dict:
    """Read a ``response.json`` or ``response.json.gz``."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _describe(event: dict) -> str:
    data = event["data"]
    name = event["event"]
    if name in ("llm_request", "llm_error"):
        return f"#{data.get('seq')} {data.get('stage')}/{data.get('label')}"
    if name in ("stage_start", "stage_complete"):
        return f"{data.get('stage')} (iteration {data.get('iteration')})"
    if name in ("discussion_round", "full_mesh_round"):
        return f"round {data.get('round')} consensus={data.get('consensus')}"
    if name == "vertical_iteration":
        return f"solver_iteration {data.get('solver_iteration')}"
    if name == "execution_result":
        return f"{data.get('expert')} {data.get('completed')}/{data.get('total')}"
    if name in ("iteration_start",):
        return f"iteration {data.get('iteration')}"
    if name == "iteration_complete":
        return f"{len(data.get('iteration_history') or [])} iteration(s) in history"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.demo.sse_events",
        description="Summarise the SSE events reconstructed from recorded AgentVerse responses.",
    )
    parser.add_argument("paths", nargs="+", help="response.json or response.json.gz files")
    parser.add_argument(
        "--timeline", action="store_true", help="also print one line per reconstructed event"
    )
    args = parser.parse_args(argv)

    for path in args.paths:
        response = load_response(path)
        events = build_events(response)
        topology = (response.get("stages") or {}).get("decision", {}).get("structure_used")
        counts = Counter(e["event"] for e in events)
        print(path)
        print(
            f"  task_id={response.get('task_id')} topology={topology} "
            f"iterations={response.get('iterations')} "
            f"llm_requests={len(response.get('llm_requests') or [])}"
        )
        print(f"  events={len(events)} duration={events[-1]['t_ms'] / 1000:.2f}s")
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"    {name:20s} {count}")
        if args.timeline:
            for event in events:
                print(f"  {event['t_ms']:>9d} ms  {event['event']:20s} {_describe(event)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
