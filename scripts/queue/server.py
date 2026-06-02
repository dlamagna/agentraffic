"""
agentraffic Queue MCP Server.

Exposes the experiment queue as FastMCP tools for Claude Code (or any MCP client).

Run standalone (stdio MCP):
    python -m scripts.queue.server

Or register in .mcp.json — see scripts/queue/README.md for setup.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastmcp import FastMCP  # noqa: E402
import re  # noqa: E402

from scripts.queue.duration_estimator import (  # noqa: E402
    estimate_job_duration,
    estimate_queue_duration,
    format_duration,
)


def _parse_duration_s(s: str) -> float:
    if not s:
        return 0.0
    total = 0.0
    for val, unit in re.findall(r'(\d+)(h|m|s)', s):
        v = int(val)
        if unit == 'h':   total += v * 3600
        elif unit == 'm': total += v * 60
        elif unit == 's': total += v
    return total


from scripts.queue.job_types import JOB_CONFIGS, JobType  # noqa: E402
from scripts.queue.queue_manager import (  # noqa: E402
    CURRENT_JOB_PID,
    DAEMON_LOG,
    DAEMON_PID,
    PAUSE_FILE,
    QUEUE_DIR,
    QUEUE_FILE,
    HISTORY_FILE,
    add_job as _add_job,
    append_history,
    cancel_job,
    daemon_pid,
    get_history,
    get_job,
    list_jobs,
    move_job,
    next_pending_job,
    pending_count,
    queue_summary,
    request_pause,
    remove_job,
    now_iso as _now,
    update_job,
    _daemon_alive,
)

mcp = FastMCP(
    "agentraffic-queue",
    instructions=(
        "Manages the agentraffic experiment queue. "
        "Jobs run serially by a background daemon. "
        "The queue runs AgentVerse topology experiments — use queue_add_job with "
        "job_type='agentverse' and params like {'topology': 'full_mesh', 'runs': 500}."
    ),
)


# ---------------------------------------------------------------------------
# Tool: add_job
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_add_job(
    job_type: str,
    params: dict[str, Any],
    notes: str = "",
    position: Optional[int] = None,
) -> dict[str, Any]:
    """
    Add an AgentVerse experiment job to the queue.

    job_type: "agentverse" (only supported type)

    params:
      topology                   str  — horizontal | vertical | full_mesh | all (default: all)
      runs                       int  — repetitions per topology (default: 500)
      agents                     int  — recruited sub-agents (default: 4)
      rounds                     int  — full-mesh discussion rounds (default: 3)
      host                       str  — Agent A host (default: localhost)
      port                       int  — Agent A port (default: 8101)
      reset_testbed_at_start     bool — run deploy.sh before the job starts (default: true)
      shutdown_testbed_when_done bool — run stop.sh after the job finishes (default: true)

    Optional params (all job types):
      wait_for_gpu_free        bool — wait until nvidia-smi reports no active compute processes
      gpu_wait_poll_interval_s int  — seconds between nvidia-smi checks (default 60)
      gpu_wait_timeout_s       int  — max seconds to wait; omit or 0 = indefinitely

    position: insert at this index (0=front); omit to append.
    notes: free-text annotation stored with the job and in its manifest.

    Example:
      queue_add_job("agentverse", {"topology": "full_mesh", "runs": 500, "agents": 4})
      queue_add_job("agentverse", {"topology": "all", "runs": 100}, notes="quick validation")
      queue_add_job("agentverse", {"topology": "all", "runs": 5, "shutdown_testbed_when_done": false})
    """
    try:
        jt = JobType(job_type)
    except ValueError:
        valid = [jt.value for jt in JobType]
        return {"error": f"Unknown job_type '{job_type}'. Valid: {valid}"}

    job = _add_job(job_type, params, notes=notes, position=position)

    return {
        "job_id":             job["id"],
        "type":               job["type"],
        "status":             job["status"],
        "estimated_duration": job.get("expected_duration") or "unknown",
        "queue_position":     _queue_position(job["id"]),
        "enqueued_at":        job["enqueued_at"],
        "notes":              job["notes"],
    }


# ---------------------------------------------------------------------------
# Tool: list_jobs
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_list_jobs(
    status: Optional[str] = None,
    include_history: bool = False,
) -> dict[str, Any]:
    """
    List jobs in the queue.

    status: filter by status — pending | waiting_for_gpu | running | completed | failed | cancelled
    include_history: if True, also return the last 20 completed jobs from history.jsonl
    """
    filter_list = [status] if status else None
    jobs = list_jobs(status_filter=filter_list)

    result: dict[str, Any] = {
        "summary": queue_summary(),
        "jobs":    [_format_job(j) for j in jobs],
    }
    if include_history:
        result["history"] = [_format_job(j) for j in get_history(limit=20)]
    return result


# ---------------------------------------------------------------------------
# Tool: remove / cancel
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_remove_job(job_id: str) -> dict[str, Any]:
    """Remove a PENDING job from the queue (use job_id prefix — first 8 chars is fine)."""
    try:
        removed = remove_job(job_id)
        return {"removed": True, "job": _format_job(removed)}
    except (KeyError, ValueError) as e:
        return {"removed": False, "error": str(e)}


@mcp.tool()
def queue_cancel_job(job_id: str) -> dict[str, Any]:
    """
    Mark a PENDING or waiting_for_gpu job as cancelled. Stays visible in history.
    Restarts the daemon automatically if it has self-exited.
    """
    try:
        updated = cancel_job(job_id)
    except KeyError as e:
        return {"cancelled": False, "error": str(e)}

    daemon_restarted = False
    if not _is_our_daemon_alive():
        DAEMON_PID.unlink(missing_ok=True)
        restart = queue_start_daemon()
        daemon_restarted = restart.get("started", False)

    result: dict[str, Any] = {"cancelled": True, "job": _format_job(updated)}
    if daemon_restarted:
        result["daemon_restarted"] = True
        result["daemon_restart_reason"] = "Daemon was not running; restarted to process remaining jobs."
    return result


# ---------------------------------------------------------------------------
# Tool: reorder
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_move_job(job_id: str, position: int) -> dict[str, Any]:
    """Move a job to a new position. position=0 moves it to the front."""
    try:
        move_job(job_id, position)
        job = get_job(job_id)
        return {"moved": True, "new_position": position, "job": _format_job(job) if job else None}
    except (KeyError, ValueError) as e:
        return {"moved": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Tool: status
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_status() -> dict[str, Any]:
    """Return queue counts by status, estimated remaining time, current job, and daemon state."""
    return queue_summary()


# ---------------------------------------------------------------------------
# Tool: estimate duration
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_estimate_duration(job_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Estimate the duration of a hypothetical job without adding it."""
    try:
        secs = estimate_job_duration(job_type, params)
        return {
            "job_type":          job_type,
            "params":            params,
            "estimated_seconds": secs,
            "estimated_human":   format_duration(secs),
        }
    except ValueError as e:
        return {"error": str(e)}


@mcp.tool()
def queue_estimate_total() -> dict[str, Any]:
    """Estimate total remaining time for all pending and running jobs."""
    jobs = list_jobs(status_filter=["pending", "waiting_for_gpu", "running"])
    total_s = estimate_queue_duration(jobs)

    per_job = []
    for j in jobs:
        try:
            secs = estimate_job_duration(j["type"], j.get("params", {}))
        except Exception:
            secs = None
        per_job.append({
            "id":       j["id"][:8],
            "type":     j["type"],
            "status":   j["status"],
            "notes":    j.get("notes", ""),
            "estimate": format_duration(secs) if secs else "unknown",
        })

    return {
        "total_seconds":     total_s,
        "total_human":       format_duration(total_s),
        "pending_job_count": len(jobs),
        "jobs":              per_job,
    }


# ---------------------------------------------------------------------------
# Tool: history
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_get_history(limit: int = 20) -> dict[str, Any]:
    """Return the most recent completed/failed jobs from history.jsonl."""
    records = get_history(limit=limit)
    return {"count": len(records), "history": [_format_job(j) for j in reversed(records)]}


# ---------------------------------------------------------------------------
# Tool: job detail
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_get_job(job_id: str) -> dict[str, Any]:
    """Return full details for a specific job (by id or 8-char prefix)."""
    job = get_job(job_id)
    if job is None:
        for h in get_history(limit=200):
            if h["id"].startswith(job_id) or h["id"] == job_id:
                job = h
                break
    if job is None:
        return {"error": f"Job not found: {job_id}"}

    result = _format_job(job)
    if job.get("output_path"):
        out = Path(job["output_path"])
        mdir = out.parent if out.suffix else out
        manifest = mdir / "queue_manifest.json"
        result["manifest_path"] = str(manifest)
        result["manifest_exists"] = manifest.exists()
    return result


# ---------------------------------------------------------------------------
# Tool: list job types
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_list_job_types() -> dict[str, Any]:
    """Return all supported job types with their descriptions and available parameters."""
    job_types = {
        jt.value: {"description": cfg.description, "params": cfg.param_docs}
        for jt, cfg in JOB_CONFIGS.items()
    }
    job_types["_common_params"] = {
        "reset_testbed_at_start":    "bool — run deploy.sh before the job starts (default: true)",
        "shutdown_testbed_when_done": "bool — run stop.sh after the job finishes (default: true)",
        "wait_for_gpu_free":          "bool — wait until nvidia-smi reports no active compute processes",
        "gpu_wait_poll_interval_s":   "int  — seconds between nvidia-smi checks (default 60)",
        "gpu_wait_timeout_s":         "int  — max seconds to wait; omit or 0 to wait indefinitely",
    }
    return job_types


# ---------------------------------------------------------------------------
# Tool: daemon control
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_start_daemon(poll_interval: int = 5) -> dict[str, Any]:
    """
    Start the queue runner daemon as a background process.
    The daemon runs jobs serially and stays alive when the queue empties,
    ready for new jobs to be added.
    """
    if _daemon_alive():
        pid = daemon_pid()
        return {"started": False, "reason": f"Daemon already running (PID {pid})", "pid": pid, "log": str(DAEMON_LOG)}

    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable

    cmd = [python, "-m", "scripts.queue.job_runner", f"--poll-interval={poll_interval}"]

    env = os.environ.copy()
    venv_bin = REPO_ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = str(venv_bin) + ":" + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(REPO_ROOT / ".venv")
    env["PYTHONPATH"] = str(REPO_ROOT)

    DAEMON_LOG.parent.mkdir(parents=True, exist_ok=True)
    with DAEMON_LOG.open("a") as log_fh:
        proc = subprocess.Popen(
            cmd, cwd=str(REPO_ROOT), env=env,
            stdout=log_fh, stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    return {"started": True, "pid": proc.pid, "log": str(DAEMON_LOG), "cmd": " ".join(cmd)}


@mcp.tool()
def queue_stop_daemon(force: bool = False) -> dict[str, Any]:
    """
    Stop the queue runner daemon.
    Default: SIGTERM (graceful, waits for current job to finish).
    force=True: SIGKILL immediately.
    """
    pid = daemon_pid()
    if pid is None or not _daemon_alive():
        return {"stopped": False, "reason": "Daemon not running"}
    try:
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)
        return {"stopped": True, "pid": pid, "signal": "SIGKILL" if force else "SIGTERM (graceful)"}
    except ProcessLookupError:
        return {"stopped": False, "reason": "Process not found (already exited?)"}
    except PermissionError:
        return {"stopped": False, "reason": f"Permission denied to signal PID {pid}"}


@mcp.tool()
def queue_cancel_running(force: bool = False) -> dict[str, Any]:
    """
    Kill the currently running job subprocess and mark it as failed.
    Use force=True for SIGKILL if SIGTERM doesn't work.
    """
    jobs = list_jobs()
    running_job = next((j for j in jobs if j.get("status") == "running"), None)

    pid: Optional[int] = None
    if CURRENT_JOB_PID.exists():
        try:
            pid = int(CURRENT_JOB_PID.read_text().strip())
        except (ValueError, OSError):
            pid = None

    killed = False
    kill_error: Optional[str] = None

    if pid is not None:
        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError):
                os.kill(pid, sig)
            killed = True
            CURRENT_JOB_PID.unlink(missing_ok=True)
        except ProcessLookupError:
            CURRENT_JOB_PID.unlink(missing_ok=True)
            kill_error = f"PID {pid} not found — process already exited"
        except PermissionError as e:
            kill_error = f"Permission denied: {e}"
    else:
        kill_error = "No current_job.pid file — job may have already finished"

    updated_job = None
    if running_job:
        try:
            updated_job = update_job(running_job["id"], status="failed", exit_code=-15,
                                     completed_at=_now())
            append_history(updated_job)
        except Exception as e:
            kill_error = (kill_error or "") + f"; queue update failed: {e}"

    return {
        "killed":     killed,
        "pid":        pid,
        "signal":     ("SIGKILL" if force else "SIGTERM") if killed else None,
        "kill_error": kill_error,
        "job_id":     running_job["id"] if running_job else None,
        "job_status": "failed" if running_job else None,
        "note":       "Queue entry marked failed. Restart daemon to process next job." if running_job else "No running job.",
    }


@mcp.tool()
def queue_pause() -> dict[str, Any]:
    """
    Pause queue processing after the current job finishes.
    The daemon exits, leaving remaining jobs in pending state.
    Restart the daemon to resume.
    """
    req = request_pause(uninstall=False, requested_by="mcp")
    return {
        "pause_requested": True,
        "daemon_running":  _daemon_alive(),
        "effective_after_current_job": True,
        "requested_at": req.get("requested_at"),
        "resume": "call queue_start_daemon() to resume",
    }


# ---------------------------------------------------------------------------
# Tool: view log
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_tail_log(lines: int = 50, job_id: Optional[str] = None) -> str:
    """
    Return the last N lines of the daemon log (default 50),
    or the job-specific log if job_id is given.
    """
    if job_id:
        job = get_job(job_id)
        if job is None:
            return f"Job not found: {job_id}"
        log_path = Path(job.get("stdout_file", ""))
    else:
        log_path = DAEMON_LOG

    if not log_path or not log_path.exists():
        return f"Log not found: {log_path}"

    all_lines = log_path.read_text().splitlines()
    return "\n".join(all_lines[-lines:])


# ---------------------------------------------------------------------------
# Tool: adopt current running experiment
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_adopt_running() -> dict[str, Any]:
    """
    Detect any AgentVerse experiment already running outside the queue
    (started manually via run_agentverse.sh) and register it as a live
    RUNNING job so it shows up in queue_status and will be tracked in
    history when it finishes.

    Reads: scripts/experiment/.experiment_state (PID + EXPERIMENT_DIR).
    """
    from scripts.queue.detect import detect_running_experiments

    current = list_jobs()
    known_paths = {j.get("output_path", "") for j in current}

    found = detect_running_experiments(known_paths)
    if not found:
        return {"adopted": [], "message": "No externally-running experiments detected."}

    adopted = []
    for exp in found:
        job = _add_job(job_type=exp["job_type"], params={},
                       notes=f"(adopted from running process PID {exp['pid']})")
        updated = update_job(job["id"], status="running", started_at=_now(),
                             output_path=exp["experiment_dir"])
        adopted.append({
            "job_id":         updated["id"][:8] + "…",
            "full_id":        updated["id"],
            "type":           updated["type"],
            "pid":            exp["pid"],
            "experiment_dir": exp["experiment_dir"],
        })

    return {"adopted": adopted, "message": f"Adopted {len(adopted)} running experiment(s)."}


# ---------------------------------------------------------------------------
# Tool: annotate job
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_annotate_job(job_id: str, note: str, append: bool = True) -> dict[str, Any]:
    """
    Add or replace the notes on any job (pending, running, completed, or failed).
    append=True (default): appends to existing notes separated by ' | '.
    append=False: replaces notes entirely.
    """
    def _build_notes(existing: str, new: str, append: bool) -> str:
        if not append or not existing:
            return new
        return f"{existing.rstrip()} | {new}"

    job = get_job(job_id)
    if job is not None:
        new_notes = _build_notes(job.get("notes", ""), note, append)
        updated = update_job(job["id"], notes=new_notes)
        return {"annotated": True, "source": "queue", "job": _format_job(updated)}

    if not HISTORY_FILE.exists():
        return {"annotated": False, "error": f"Job not found: {job_id}"}

    import json as _json
    lines = HISTORY_FILE.read_text().splitlines()
    matched = False
    new_lines = []
    updated_job = None
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = _json.loads(line)
        except _json.JSONDecodeError:
            new_lines.append(line)
            continue
        if rec.get("id", "").startswith(job_id) or rec.get("id") == job_id:
            rec["notes"] = _build_notes(rec.get("notes", ""), note, append)
            matched = True
            updated_job = rec
            new_lines.append(_json.dumps(rec))
        else:
            new_lines.append(line)

    if not matched:
        return {"annotated": False, "error": f"Job not found: {job_id}"}

    HISTORY_FILE.write_text("\n".join(new_lines) + "\n")
    return {"annotated": True, "source": "history", "job": _format_job(updated_job)}


# ---------------------------------------------------------------------------
# Tool: import pre-queue history
# ---------------------------------------------------------------------------

@mcp.tool()
def queue_import_history(dry_run: bool = False) -> dict[str, Any]:
    """
    Scan data/agentverse/experiment_* for runs that pre-date the queue
    (no queue_manifest.json) and import them into history.jsonl.

    dry_run=True: report what would be imported without writing.
    """
    from scripts.queue.detect import scan_historical_runs
    from scripts.queue.queue_manager import append_history, write_job_manifest

    current_jobs = list_jobs()
    history_jobs = get_history(limit=10000)
    known_paths = {j.get("output_path", "") for j in current_jobs + history_jobs if j.get("output_path")}

    records = scan_historical_runs(known_paths)

    if not records:
        return {"imported": 0, "dry_run": dry_run, "entries": [],
                "message": "No untracked historical runs found."}

    if not dry_run:
        for rec in records:
            append_history(rec)
            try:
                write_job_manifest(rec, rec["output_path"])
            except Exception:
                pass

    return {
        "imported":      len(records) if not dry_run else 0,
        "would_import":  len(records) if dry_run else None,
        "dry_run":       dry_run,
        "entries": [
            {"type": r["type"], "output_path": r["output_path"],
             "started_at": r["started_at"], "notes": r["notes"]}
            for r in records
        ],
        "message": f"{'Would import' if dry_run else 'Imported'} {len(records)} pre-queue run(s).",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_our_daemon_alive() -> bool:
    if not _daemon_alive():
        return False
    pid = daemon_pid()
    if pid is None:
        return False
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode()
        return "job_runner" in cmdline
    except OSError:
        return False


def _queue_position(job_id: str) -> Optional[int]:
    for i, j in enumerate(list_jobs(status_filter=["pending", "waiting_for_gpu"])):
        if j["id"] == job_id:
            return i
    return None


def _format_job(job: dict) -> dict:
    return {
        "id":               job["id"][:8] + "…",
        "full_id":          job["id"],
        "type":             job["type"],
        "status":           job["status"],
        "notes":            job.get("notes", ""),
        "params":           job.get("params", {}),
        "estimated":        job.get("expected_duration") or "unknown",
        "enqueued_at":      job.get("enqueued_at"),
        "started_at":       job.get("started_at"),
        "completed_at":     job.get("completed_at"),
        "exit_code":        job.get("exit_code"),
        "output_path":      job.get("output_path"),
        "stdout_file":      job.get("stdout_file"),
        "experiment_log_file": job.get("experiment_log_file"),
        "gpu_wait_started_at":      job.get("gpu_wait_started_at"),
        "gpu_wait_completed_at":    job.get("gpu_wait_completed_at"),
        "gpu_wait_seconds":         job.get("gpu_wait_seconds"),
        "gpu_wait_active_processes": job.get("gpu_wait_active_processes"),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
