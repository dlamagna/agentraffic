"""
Queue state manager.

Owns queue/state/queue.json (current queue) and queue/state/history.jsonl
(completed job log). Uses a file lock to prevent concurrent writes from the
MCP server and the runner daemon.

Queue JSON schema:
  {
    "version": "1",
    "jobs": [
      {
        "id":                   "<uuid4>",
        "type":                 "agentverse",
        "status":               "pending|waiting_for_gpu|running|completed|failed|cancelled",
        "params":               {...},
        "notes":                "optional free-text",

        "expected_duration":    "0h0m0s" | null,
        "enqueued_at":          "<ISO8601>",
        "started_at":           null | "<ISO8601>",
        "completed_at":         null | "<ISO8601>",
        "exit_code":            null | <int>,
        "output_path":          null | "<path>",
        "stdout_file":          null | "<path>",
        "experiment_log_file":  null | "<path>"
      }
    ]
  }

History JSONL: each line is one completed job dict (same schema as above).
"""

from __future__ import annotations

import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.queue.job_types import JobType
import importlib
import scripts.queue.duration_estimator as _duration_estimator_mod


QUEUE_DIR        = Path(__file__).resolve().parents[2] / "queue" / "state"
QUEUE_FILE       = QUEUE_DIR / "queue.json"
HISTORY_FILE     = QUEUE_DIR / "history.jsonl"
DAEMON_PID       = QUEUE_DIR / "daemon.pid"
CURRENT_JOB_PID  = QUEUE_DIR / "current_job.pid"
DAEMON_LOG       = QUEUE_DIR.parent / "logs" / "daemon.log"
PAUSE_FILE       = QUEUE_DIR / "pause.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

now_iso = _now


# ---------------------------------------------------------------------------
# Low-level I/O with advisory file locking
# ---------------------------------------------------------------------------

class _LockedQueueFile:
    def __init__(self, path: Path, write: bool = False) -> None:
        self._path  = path
        self._write = write
        self._fh    = None

    def __enter__(self) -> "_LockedQueueFile":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a+" if self._write else "r+")
        lock_type = fcntl.LOCK_EX if self._write else fcntl.LOCK_SH
        fcntl.flock(self._fh, lock_type)
        self._fh.seek(0)
        return self

    def read(self) -> dict:
        raw = self._fh.read()
        if not raw.strip():
            return {"version": "1", "jobs": []}
        return json.loads(raw)

    def write(self, data: dict) -> None:
        self._fh.seek(0)
        self._fh.truncate()
        json.dump(data, self._fh, indent=2)
        self._fh.flush()

    def __exit__(self, *_) -> None:
        if self._fh:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
            self._fh.close()


def _ensure_queue() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    if not QUEUE_FILE.exists():
        QUEUE_FILE.write_text(json.dumps({"version": "1", "jobs": []}, indent=2))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_job(
    job_type: str,
    params: dict[str, Any],
    notes: str = "",
    position: Optional[int] = None,
) -> dict[str, Any]:
    """
    Add a new PENDING job to the queue.
    Returns the newly created job dict.
    position=None appends to end; position=0 inserts at front.
    """
    _ensure_queue()
    jt = JobType(job_type)
    try:
        _de = importlib.reload(_duration_estimator_mod)
        expected_s = _de.estimate_job_duration(jt, params)
        expected_duration = _de.format_duration(expected_s)
    except Exception:
        expected_s = None
        expected_duration = None

    job: dict[str, Any] = {
        "id":                  str(uuid.uuid4()),
        "type":                jt.value,
        "status":              "pending",
        "params":              params,
        "notes":               notes,
        "expected_duration":   expected_duration,
        "enqueued_at":         _now(),
        "started_at":          None,
        "completed_at":        None,
        "exit_code":           None,
        "output_path":         None,
        "stdout_file":         None,
        "experiment_log_file": None,
    }

    with _LockedQueueFile(QUEUE_FILE, write=True) as lf:
        data = lf.read()
        if position is None:
            data["jobs"].append(job)
        else:
            data["jobs"].insert(position, job)
        lf.write(data)

    return job


def list_jobs(
    status_filter: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Return all jobs, optionally filtered by status."""
    _ensure_queue()
    with _LockedQueueFile(QUEUE_FILE) as lf:
        data = lf.read()
    jobs = data.get("jobs", [])
    for job in jobs:
        if "stdout_file" not in job:
            job["stdout_file"] = None
        if "experiment_log_file" not in job:
            job["experiment_log_file"] = None
    if status_filter:
        jobs = [j for j in jobs if j.get("status") in status_filter]
    return jobs


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    for j in list_jobs():
        if j["id"] == job_id or j["id"].startswith(job_id):
            return j
    return None


def update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    _ensure_queue()
    with _LockedQueueFile(QUEUE_FILE, write=True) as lf:
        data = lf.read()
        for job in data["jobs"]:
            if job["id"] == job_id or job["id"].startswith(job_id):
                job.update(fields)
                lf.write(data)
                return job
    raise KeyError(f"Job not found: {job_id}")


def remove_job(job_id: str) -> dict[str, Any]:
    _ensure_queue()
    with _LockedQueueFile(QUEUE_FILE, write=True) as lf:
        data = lf.read()
        for i, job in enumerate(data["jobs"]):
            if job["id"] == job_id or job["id"].startswith(job_id):
                if job["status"] == "running":
                    raise ValueError(f"Cannot remove job {job_id}: currently running")
                removed = data["jobs"].pop(i)
                lf.write(data)
                return removed
    raise KeyError(f"Job not found: {job_id}")


def move_job(job_id: str, new_position: int) -> None:
    _ensure_queue()
    with _LockedQueueFile(QUEUE_FILE, write=True) as lf:
        data = lf.read()
        jobs = data["jobs"]
        idx = next(
            (i for i, j in enumerate(jobs)
             if j["id"] == job_id or j["id"].startswith(job_id)),
            None,
        )
        if idx is None:
            raise KeyError(f"Job not found: {job_id}")
        job = jobs.pop(idx)
        jobs.insert(new_position, job)
        lf.write(data)


def cancel_job(job_id: str) -> dict[str, Any]:
    return update_job(job_id, status="cancelled", completed_at=_now())


def next_pending_job() -> Optional[dict[str, Any]]:
    for j in list_jobs():
        if j["status"] in ("pending", "waiting_for_gpu"):
            return j
    return None


def pending_count() -> int:
    return sum(1 for j in list_jobs() if j["status"] in ("pending", "waiting_for_gpu"))


def queue_summary() -> dict[str, Any]:
    from scripts.queue.duration_estimator import estimate_queue_duration, format_duration

    jobs = list_jobs()
    by_status: dict[str, int] = {}
    for j in jobs:
        by_status[j["status"]] = by_status.get(j["status"], 0) + 1

    pending_jobs = [j for j in jobs if j["status"] in ("pending", "waiting_for_gpu", "running")]
    total_s = estimate_queue_duration(pending_jobs)
    running = next((j for j in jobs if j["status"] in ("running", "waiting_for_gpu")), None)

    return {
        "total_jobs":            len(jobs),
        "by_status":             by_status,
        "estimated_remaining":   format_duration(total_s),
        "estimated_remaining_s": total_s,
        "current_job":           running,
        "daemon_running":        _daemon_alive(),
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def append_history(job: dict[str, Any]) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a") as f:
        f.write(json.dumps(job) + "\n")


def get_history(limit: int = 50) -> list[dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text().strip().splitlines()
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return records[-limit:]


# ---------------------------------------------------------------------------
# Daemon PID helpers
# ---------------------------------------------------------------------------

def _daemon_alive() -> bool:
    if not DAEMON_PID.exists():
        return False
    try:
        pid = int(DAEMON_PID.read_text().strip())
        Path(f"/proc/{pid}").stat()
        return True
    except (ValueError, OSError):
        return False


def daemon_pid() -> Optional[int]:
    if not DAEMON_PID.exists():
        return None
    try:
        return int(DAEMON_PID.read_text().strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Pause request helpers
# ---------------------------------------------------------------------------

def request_pause(uninstall: bool = False, requested_by: str = "mcp") -> dict[str, Any]:
    payload = {
        "requested_at": _now(),
        "requested_by": requested_by,
        "uninstall": bool(uninstall),
    }
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.write_text(json.dumps(payload, indent=2))
    return payload


def read_pause_request() -> Optional[dict[str, Any]]:
    if not PAUSE_FILE.exists():
        return None
    try:
        return json.loads(PAUSE_FILE.read_text())
    except Exception:
        return None


def clear_pause_request() -> None:
    if PAUSE_FILE.exists():
        try:
            PAUSE_FILE.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Per-results manifest
# ---------------------------------------------------------------------------

def write_job_manifest(job: dict[str, Any], output_path: str) -> str:
    out = Path(output_path)
    manifest_dir = out.parent if out.suffix else out
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "queue_manifest.json"

    manifest = {
        "queue_schema_version": "1",
        "queue_job_id":         job["id"],
        "job_type":             job["type"],
        "notes":                job.get("notes", ""),
        "params":               job.get("params", {}),
        "expected_duration":    job.get("expected_duration"),
        "enqueued_at":          job.get("enqueued_at"),
        "started_at":           job.get("started_at"),
        "completed_at":         job.get("completed_at"),
        "exit_code":            job.get("exit_code"),
        "output_path":          str(output_path),
        "stdout_file":          job.get("stdout_file"),
        "experiment_log_file":  job.get("experiment_log_file"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return str(manifest_path)
