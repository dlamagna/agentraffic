"""
Agent A HTTP server.

Exposes two endpoints:
  POST /agentverse  — 4-stage AgentVerse workflow (sequential / star / full_mesh)
  POST /task        — Simple single-agent or parallel task (sanity-check / baseline)

Both endpoints support an optional ?stream=true flag to receive Server-Sent Events
while the workflow runs, in addition to the final JSON result.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Optional
from urllib.parse import parse_qs, urlparse

from opentelemetry import context as otel_context
from opentelemetry import propagate
from opentelemetry.trace import SpanKind

from agents.agent_a.main import AGENT_B_URLS, LLM_SERVER_URL, call_agent_b, call_llm
from agents.agent_a.orchestrator import AgentVerseOrchestrator
from agents.common.metrics_logger import MetricsLogger
from agents.common.telemetry import TelemetryLogger
from agents.common.tracing import get_tracer

HOST = "0.0.0.0"
PORT = int(os.environ.get("AGENT_A_PORT", "8101"))
MAX_AGENT_B_TURNS = int(os.environ.get("MAX_AGENT_B_TURNS", "3"))
CONTEXT_PREVIEW_LEN = 300
MAX_PARALLEL_WORKERS = int(os.environ.get("MAX_PARALLEL_WORKERS", "5"))
AGENT_B_TIMEOUT_SECONDS = float(os.environ.get("AGENT_B_TIMEOUT_SECONDS", "120"))
LOG_LLM_REQUESTS = os.environ.get("LOG_LLM_REQUESTS", "").lower() in ("1", "true", "yes", "on")
LLM_LOG_MAX_CHARS = int(os.environ.get("LLM_LOG_MAX_CHARS", "500"))


def _clean_string(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_workers(
    requested_count: Optional[int],
    worker_payloads: Any,
    fallback_urls: Iterable[str],
) -> list[Dict[str, Optional[str]]]:
    urls = [url for url in fallback_urls if url]
    if not urls:
        urls = ["http://agent-b:8102/subtask"]

    count = (
        requested_count if isinstance(requested_count, int) and requested_count > 0 else len(urls)
    )
    count = min(count, MAX_PARALLEL_WORKERS)

    payloads: list[Dict[str, Any]] = worker_payloads if isinstance(worker_payloads, list) else []
    normalized: list[Dict[str, Optional[str]]] = []

    for idx in range(count):
        payload = payloads[idx] if idx < len(payloads) and isinstance(payloads[idx], dict) else {}
        endpoint = _clean_string(payload.get("endpoint"))
        role = _clean_string(payload.get("role"))
        contract = _clean_string(payload.get("contract"))
        if not endpoint:
            endpoint = urls[idx % len(urls)]
        normalized.append({"endpoint": endpoint, "role": role, "contract": contract})

    return normalized


def _parse_subtasks(raw: str, desired_count: int, fallback_task: str) -> list[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None

    subtasks: list[str] = []
    if isinstance(parsed, list):
        subtasks = [str(item).strip() for item in parsed if str(item).strip()]
    elif isinstance(parsed, dict):
        items = parsed.get("subtasks")
        if isinstance(items, list):
            subtasks = [str(item).strip() for item in items if str(item).strip()]

    if not subtasks:
        subtasks = [f"Subtask {idx + 1}: {fallback_task}" for idx in range(desired_count)]

    if len(subtasks) < desired_count:
        subtasks += [
            f"Subtask {idx + 1}: {fallback_task}" for idx in range(len(subtasks), desired_count)
        ]
    return subtasks[:desired_count]


def _log_llm_prompt(label: str, prompt: str) -> None:
    if not LOG_LLM_REQUESTS:
        return
    max_chars = max(LLM_LOG_MAX_CHARS, 0)
    preview = prompt[:max_chars] if max_chars else ""
    suffix = (
        ""
        if not max_chars or len(prompt) <= max_chars
        else f"... [truncated {len(prompt) - max_chars} chars]"
    )
    print(f"[agent-a][llm] {label} prompt_len={len(prompt)} prompt={preview}{suffix}")


class AgentARequestHandler(BaseHTTPRequestHandler):
    logger = TelemetryLogger(agent_id="AgentA")
    tracer = get_tracer("agent-a")
    metrics_logger = MetricsLogger()

    def _set_cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors()
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Send a Server-Sent Event."""
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        self.wfile.write(message.encode("utf-8"))
        self.wfile.flush()

    # -----------------------------------------------------------------------
    # GET /agentverse/<task_id>  — retrieve a persisted run
    # -----------------------------------------------------------------------

    def _handle_get_agentverse_run(self, task_id: str) -> None:
        task_id = (task_id or "").strip()
        if not task_id:
            self._send_json(400, {"error": "Missing task_id"})
            return
        if not all(ch.isalnum() or ch in ("-", "_") for ch in task_id):
            self._send_json(400, {"error": "Invalid task_id"})
            return

        path = os.path.join("logs", "agentverse", f"{task_id}.json")
        if not os.path.exists(path):
            self._send_json(404, {"error": "Task not found", "task_id": task_id})
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                record: Dict[str, Any] = json.load(f)
        except Exception as exc:
            self._send_json(500, {"error": f"Failed to load task: {exc}"})
            return

        self._send_json(200, record)

    def _persist_agentverse_run(
        self,
        task_id: str,
        task: str,
        max_iterations: int,
        success_threshold: int,
        result: Dict[str, Any],
    ) -> None:
        """Best-effort persistence of AgentVerse runs to logs/agentverse/<task_id>.json."""
        try:
            base_dir = os.path.join("logs", "agentverse")
            os.makedirs(base_dir, exist_ok=True)
            record: Dict[str, Any] = {
                "task_id": task_id,
                "task": task,
                "max_iterations": max_iterations,
                "success_threshold": success_threshold,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "result": result,
            }
            with open(os.path.join(base_dir, f"{task_id}.json"), "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[agent-a][agentverse] Failed to persist run {task_id}: {exc}", flush=True)

    # -----------------------------------------------------------------------
    # POST /agentverse  — 4-stage AgentVerse workflow
    # -----------------------------------------------------------------------

    def _handle_agentverse(self) -> None:
        with self.tracer.start_as_current_span("agent_a.agentverse_workflow") as span:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""

            try:
                data: Dict[str, Any] = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return

            task = data.get("task")
            if not isinstance(task, str) or not task:
                self._send_json(400, {"error": "Missing 'task' field"})
                return

            max_iterations = min(max(int(data.get("max_iterations", 3)), 1), 5)
            success_threshold = min(100, max(0, int(data.get("success_threshold", 70))))
            stream = data.get("stream", False)

            # Optional topology override: "horizontal" | "vertical" | "full_mesh"
            _fs = data.get("force_structure", None)
            force_structure: Optional[str] = (
                _fs if _fs in ("horizontal", "vertical", "full_mesh") else None
            )

            # Optional agent count override (0 = solo mode, N = exactly N sub-agents)
            _fac = data.get("force_agent_count", None)
            force_agent_count: Optional[int] = None
            if _fac is not None:
                try:
                    v = int(_fac)
                    if v >= 0:
                        force_agent_count = v
                except (TypeError, ValueError):
                    pass

            # Optional full-mesh round cap override
            _fmmr = data.get("full_mesh_max_rounds", None)
            full_mesh_max_rounds: Optional[int] = None
            if _fmmr is not None:
                try:
                    v = int(_fmmr)
                    if v >= 1:
                        full_mesh_max_rounds = v
                except (TypeError, ValueError):
                    pass

            span.set_attribute("app.task", task)
            span.set_attribute("app.max_iterations", max_iterations)
            span.set_attribute("app.success_threshold", success_threshold)
            span.set_attribute("app.stream", stream)

            logger = TelemetryLogger(agent_id="AgentA-Orchestrator", scenario="agentic_verse")
            task_id = logger.new_task_id()
            span.set_attribute("app.task_id", task_id)

            logger.log(
                task_id=task_id,
                event_type="agentverse_request_received",
                message=f"Received AgentVerse request: {task[:100]}",
                extra={"max_iterations": max_iterations, "stream": stream},
            )

            try:
                if stream:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self._set_cors()
                    self.end_headers()

                    _sse_lock = threading.Lock()

                    def progress_callback(progress: Dict[str, Any]) -> None:
                        with _sse_lock:
                            self._send_sse_event(progress["event"], progress["data"])

                    orchestrator = AgentVerseOrchestrator(
                        logger=logger,
                        tracer=self.tracer,
                        progress_callback=progress_callback,
                    )
                    result = orchestrator.run_workflow(
                        task=task,
                        task_id=task_id,
                        max_iterations=max_iterations,
                        success_threshold=success_threshold,
                        force_structure=force_structure,
                        force_agent_count=force_agent_count,
                        full_mesh_max_rounds=full_mesh_max_rounds,
                    )
                    self._persist_agentverse_run(
                        task_id, task, max_iterations, success_threshold, result
                    )
                    self._send_sse_event("complete", result)

                else:
                    orchestrator = AgentVerseOrchestrator(logger=logger, tracer=self.tracer)
                    result = orchestrator.run_workflow(
                        task=task,
                        task_id=task_id,
                        max_iterations=max_iterations,
                        success_threshold=success_threshold,
                        force_structure=force_structure,
                        force_agent_count=force_agent_count,
                        full_mesh_max_rounds=full_mesh_max_rounds,
                    )
                    self._persist_agentverse_run(
                        task_id, task, max_iterations, success_threshold, result
                    )
                    self._send_json(200, result)

            except Exception as exc:
                logger.log(
                    task_id=task_id,
                    event_type="agentverse_error",
                    message=f"AgentVerse workflow failed: {exc}",
                )
                if stream:
                    self._send_sse_event("error", {"error": str(exc)})
                else:
                    self._send_json(502, {"error": f"AgentVerse workflow failed: {exc}"})

    # -----------------------------------------------------------------------
    # POST /task  — simple single-agent or parallel baseline
    # -----------------------------------------------------------------------

    def _handle_task(self, span, data: Dict[str, Any]) -> None:
        task = data.get("task")
        scenario = data.get("scenario")
        agent_a_role = (
            data.get("agent_a_role") if isinstance(data.get("agent_a_role"), str) else None
        )
        agent_a_contract = (
            data.get("agent_a_contract") if isinstance(data.get("agent_a_contract"), str) else None
        )
        agent_b_role = (
            data.get("agent_b_role") if isinstance(data.get("agent_b_role"), str) else None
        )
        agent_b_contract = (
            data.get("agent_b_contract") if isinstance(data.get("agent_b_contract"), str) else None
        )
        agent_count = data.get("agent_count")
        agent_b_workers = data.get("agent_b_workers")

        if not isinstance(task, str) or not task:
            self._send_json(400, {"error": "Missing 'task' field"})
            return

        span.set_attribute("app.task", task)
        if scenario:
            span.set_attribute("app.scenario", scenario)
        if agent_a_role:
            span.set_attribute("app.agent_role", agent_a_role)

        logger = self.logger
        logger.scenario = scenario  # type: ignore[assignment]
        task_id = logger.new_task_id()
        task_start = datetime.now(timezone.utc).isoformat()
        span.set_attribute("app.task_id", task_id)
        logger.log(
            task_id=task_id,
            event_type="task_received",
            message=task,
            extra={"agent_role": agent_a_role} if agent_a_role else None,
        )

        final_prompt: str
        agent_b_output: Optional[str] = None
        agent_b_outputs: list[Any] = []
        agent_a_progress_notes: list[str] = []
        llm_requests: list[Dict[str, Any]] = []
        max_turns = MAX_AGENT_B_TURNS
        requested_turns = data.get("max_agent_turns")
        if isinstance(requested_turns, int) and requested_turns > 0:
            max_turns = min(requested_turns, MAX_AGENT_B_TURNS)

        role_context_parts = []
        if agent_a_role:
            role_context_parts.append(f"Role: {agent_a_role}")
        if agent_a_contract:
            role_context_parts.append(f"Contract: {agent_a_contract}")
        role_context = "\n".join(role_context_parts)
        role_context_block = f"{role_context}\n" if role_context else ""

        if scenario == "agentic_parallel":
            workers = _normalize_workers(agent_count, agent_b_workers, AGENT_B_URLS)
            planning_prompt = (
                "You are Agent A, acting as the planner. Break the user task into "
                f"{len(workers)} concrete, independent subtasks. Return ONLY valid JSON "
                'as an array of strings, e.g. ["subtask 1", "subtask 2"].\n\n'
                f"{role_context_block}"
                f"User task:\n{task}"
            )
            try:
                with self.tracer.start_as_current_span(
                    "agent_a.plan_subtasks", kind=SpanKind.CLIENT
                ) as span_plan:
                    span_plan.set_attribute("app.llm.url", LLM_SERVER_URL)
                    headers: Dict[str, str] = {}
                    propagate.inject(headers)
                    _ts_plan_start = datetime.now(timezone.utc).isoformat()
                    planned_raw, _plan_meta = call_llm(planning_prompt, headers=headers)
                    _ts_plan_end = datetime.now(timezone.utc).isoformat()
                    llm_requests.append(
                        {
                            "source": "agent_a",
                            "label": "planning",
                            "prompt": planning_prompt,
                            "response": planned_raw,
                            "endpoint": LLM_SERVER_URL,
                        }
                    )
                    self.metrics_logger.log_call(
                        task_id=task_id,
                        agent_id="AgentA",
                        call_type="sub_call",
                        timestamp_start=_ts_plan_start,
                        timestamp_end=_ts_plan_end,
                        http_status=200,
                        llm_meta=_plan_meta,
                    )
            except Exception as exc:
                logger.log(
                    task_id=task_id,
                    event_type="agent_a_planning_error",
                    message=f"Planning failed: {exc}",
                )
                planned_raw = "[]"

            subtasks = _parse_subtasks(planned_raw, len(workers), task)

            request_ctx = otel_context.get_current()

            def _run_worker_call(parent_ctx, worker_index, worker, subtask):
                token = otel_context.attach(parent_ctx)
                role = worker["role"] or agent_b_role
                try:
                    with self.tracer.start_as_current_span(
                        "agent_a.call_agent_b_parallel", kind=SpanKind.CLIENT
                    ):
                        headers: Dict[str, str] = {"x-agent-index": str(worker_index)}
                        propagate.inject(headers)
                        return call_agent_b(
                            subtask,
                            scenario=scenario,
                            headers=headers,
                            agent_b_role=role,
                            agent_b_contract=worker["contract"] or agent_b_contract,
                            agent_b_url=worker["endpoint"],
                        )
                finally:
                    otel_context.detach(token)

            with ThreadPoolExecutor(max_workers=len(workers)) as executor:
                future_map = {
                    executor.submit(_run_worker_call, request_ctx, idx, worker, subtask): (
                        idx,
                        worker,
                        subtask,
                    )
                    for idx, (worker, subtask) in enumerate(zip(workers, subtasks), start=1)
                }
                for future in as_completed(future_map):
                    idx, worker, subtask = future_map[future]
                    try:
                        response = future.result()
                        output = str(response.get("output", ""))
                        agent_b_outputs.append(
                            {
                                "agent_index": idx,
                                "endpoint": worker["endpoint"],
                                "subtask": subtask,
                                "output": output,
                            }
                        )
                    except Exception as exc:
                        agent_b_outputs.append(
                            {
                                "agent_index": idx,
                                "endpoint": worker["endpoint"],
                                "subtask": subtask,
                                "output": f"Worker failed: {exc}",
                            }
                        )

            worker_summary = "\n\n".join(
                f"Worker {item['agent_index']} ({item['endpoint']}):\nSubtask: {item['subtask']}\n{item['output']}"
                for item in sorted(agent_b_outputs, key=lambda x: x["agent_index"])
            )
            final_prompt = (
                "You are Agent A acting as planner/critic. Review the worker reports, "
                "note inconsistencies or gaps, then produce the best final response.\n\n"
                f"{role_context_block}User task:\n{task}\n\nWorker reports:\n{worker_summary}"
            )
            agent_b_output = worker_summary

        elif scenario == "agentic_multi_hop":
            context_summary = ""
            for turn in range(1, max_turns + 1):
                subtask = (
                    f"[Turn {turn}] Help solve the user task. "
                    "Provide concrete steps or intermediate results.\n"
                    f"User task:\n{task}\n\nContext so far:\n{context_summary or '(none yet)'}"
                )
                try:
                    with self.tracer.start_as_current_span(
                        "agent_a.call_agent_b", kind=SpanKind.CLIENT
                    ):
                        headers = {}
                        propagate.inject(headers)
                        response = call_agent_b(
                            subtask,
                            scenario=scenario,
                            headers=headers,
                            agent_b_role=agent_b_role,
                            agent_b_contract=agent_b_contract,
                        )
                        agent_b_output = str(response.get("output", ""))
                except Exception as exc:
                    self._send_json(502, {"error": f"Agent B failed: {exc}"})
                    return

                agent_b_outputs.append(agent_b_output or "")
                context_summary = (context_summary + "\n" + (agent_b_output or "")).strip()[-2000:]

            final_prompt = (
                f"You are Agent A. The user task is:\n{role_context_block}\n{task}\n\n"
                f"Agent B provided these iterative notes:\n{context_summary}\n\n"
                "Produce the final concise answer for the user task."
            )
            agent_b_output = "\n---\n".join(str(o) for o in agent_b_outputs)

        else:
            final_prompt = task

        try:
            with self.tracer.start_as_current_span(
                "agent_a.call_llm", kind=SpanKind.CLIENT
            ) as span_llm:
                span_llm.set_attribute("app.llm.url", LLM_SERVER_URL)
                headers = {}
                propagate.inject(headers)
                _ts_final_start = datetime.now(timezone.utc).isoformat()
                output, _final_meta = call_llm(final_prompt, headers=headers)
                _ts_final_end = datetime.now(timezone.utc).isoformat()
                llm_requests.append(
                    {
                        "source": "agent_a",
                        "label": "final",
                        "prompt": final_prompt,
                        "response": output,
                        "endpoint": LLM_SERVER_URL,
                    }
                )
                self.metrics_logger.log_call(
                    task_id=task_id,
                    agent_id="AgentA",
                    call_type="root",
                    timestamp_start=_ts_final_start,
                    timestamp_end=_ts_final_end,
                    http_status=200,
                    llm_meta=_final_meta,
                )
        except Exception as exc:
            self._send_json(502, {"error": f"LLM failed: {exc}"})
            return

        task_end = datetime.now(timezone.utc).isoformat()
        total_llm_calls = len(llm_requests)
        total_prompt_tokens = sum(
            (r.get("llm_meta") or {}).get("prompt_tokens") or 0 for r in llm_requests
        )
        total_completion_tokens = sum(
            (r.get("llm_meta") or {}).get("completion_tokens") or 0 for r in llm_requests
        )
        total_tokens = sum((r.get("llm_meta") or {}).get("total_tokens") or 0 for r in llm_requests)

        self._send_json(
            200,
            {
                "task_id": task_id,
                "agent_id": "AgentA",
                "scenario": scenario,
                "task_query": task,
                "task_start": task_start,
                "task_end": task_end,
                "total_llm_calls": total_llm_calls,
                "total_prompt_tokens": total_prompt_tokens,
                "total_completion_tokens": total_completion_tokens,
                "total_tokens": total_tokens,
                "output": output,
                "agent_b_output": agent_b_output,
                "agent_b_outputs": agent_b_outputs,
                "agent_a_progress_notes": agent_a_progress_notes,
                "llm_requests": llm_requests,
            },
        )

    # -----------------------------------------------------------------------
    # HTTP method handlers
    # -----------------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # type: ignore[override]
        parsed = urlparse(self.path)
        if parsed.path in ("/task", "/agentverse") or parsed.path.startswith("/agentverse"):
            self.send_response(204)
        else:
            self.send_response(404)
        self._set_cors()
        self.end_headers()

    def do_GET(self) -> None:  # type: ignore[override]
        parsed = urlparse(self.path)

        if parsed.path.startswith("/agentverse"):
            task_id: Optional[str] = None
            if parsed.path != "/agentverse":
                suffix = (
                    parsed.path[len("/agentverse/") :]
                    if parsed.path.startswith("/agentverse/")
                    else ""
                )
                task_id = suffix.strip("/") or None
            if not task_id:
                qs = parse_qs(parsed.query or "")
                values = qs.get("task_id") or qs.get("taskId")
                if values:
                    task_id = values[0]
            if not task_id:
                self._send_json(400, {"error": "Missing task_id"})
                return
            self._handle_get_agentverse_run(task_id)
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # type: ignore[override]
        if self.path == "/agentverse":
            self._handle_agentverse()
            return

        if self.path != "/task":
            self._send_json(404, {"error": "Not found"})
            return

        carrier = {key: value for key, value in self.headers.items()}
        parent_ctx = propagate.extract(carrier)
        with self.tracer.start_as_current_span(
            "agent_a.handle_task",
            context=parent_ctx,
            kind=SpanKind.SERVER,
        ) as span:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b""
            try:
                data: Dict[str, Any] = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Invalid JSON"})
                return
            self._handle_task(span, data)

    def log_message(self, format: str, *args: Any) -> None:  # type: ignore[override]
        pass  # Suppress default access log noise; telemetry logger handles this.


def run() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AgentARequestHandler)
    print(f"[*] Agent A listening on http://{HOST}:{PORT}  (POST /agentverse, POST /task)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down Agent A.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
