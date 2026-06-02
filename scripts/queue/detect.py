"""
Experiment detection helpers.

Two capabilities:
  1. detect_running_experiments() — reads the agentverse state file and
     checks whether the recorded PID is still alive.

  2. scan_historical_runs() — walks known output directory patterns for
     result dirs that exist on disk but have no queue_manifest.json.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# State file locations
# Written by run_agentverse.sh when it starts (if supported).
# Format: KEY=VALUE (sourceable shell)
#   PID=<int>
#   EXPERIMENT_DIR=<path>
# ---------------------------------------------------------------------------

STATE_FILES: dict[str, dict] = {
    "agentverse": {
        "path": REPO_ROOT / "scripts/experiment/.experiment_state",
        "job_type": "agentverse",
    },
}

# ---------------------------------------------------------------------------
# Known result directory patterns
# ---------------------------------------------------------------------------

HISTORY_PATTERNS: list[dict] = [
    {
        "glob":     "data/agentverse/experiment_*",
        "job_type": "agentverse",
        "name_re":  r"experiment_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pid_alive(pid: int) -> bool:
    try:
        Path(f"/proc/{pid}").stat()
        return True
    except OSError:
        return False


def _parse_state_file(path: Path) -> Optional[dict[str, str]]:
    if not path.exists():
        return None
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result if "PID" in result else None


def _ts_from_dir(name: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, name)
    if not m:
        return None
    raw = m.group(1)
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_running_experiments(queued_ids: set[str]) -> list[dict]:
    """
    Check the agentverse state file. If the PID is alive and the result dir
    is not already tracked, return a descriptor dict.
    """
    found = []
    for name, cfg in STATE_FILES.items():
        state = _parse_state_file(cfg["path"])
        if state is None:
            continue
        try:
            pid = int(state["PID"])
        except (ValueError, KeyError):
            continue
        exp_dir = state.get("EXPERIMENT_DIR", "")
        if not _pid_alive(pid):
            continue
        if exp_dir in queued_ids:
            continue
        found.append({
            "job_type":       cfg["job_type"],
            "pid":            pid,
            "experiment_dir": exp_dir,
            "state_file":     str(cfg["path"]),
        })
    return found


def scan_historical_runs(known_output_paths: set[str]) -> list[dict]:
    """
    Walk HISTORY_PATTERNS. For each result directory that exists but has no
    queue_manifest.json, return a metadata dict ready for history.jsonl.
    """
    import uuid
    import glob as _glob

    records = []
    seen_paths: set[str] = set()

    for spec in HISTORY_PATTERNS:
        pattern = str(REPO_ROOT / spec["glob"])
        for match in sorted(_glob.glob(pattern)):
            abs_path = str(Path(match).resolve())
            if abs_path in known_output_paths or abs_path in seen_paths:
                continue
            seen_paths.add(abs_path)

            ts = _ts_from_dir(Path(match).name, spec["name_re"])
            mtime = os.path.getmtime(match)
            mtime_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()

            records.append({
                "id":                  str(uuid.uuid4()),
                "type":                spec["job_type"],
                "status":              "completed",
                "params":              spec.get("params", {}),
                "notes":               "(imported from pre-queue run)",
                "expected_duration":   None,
                "enqueued_at":         ts or mtime_iso,
                "started_at":          ts or mtime_iso,
                "completed_at":        mtime_iso,
                "exit_code":           0,
                "output_path":         abs_path,
                "stdout_file":         None,
                "experiment_log_file": None,
                "_imported":           True,
            })

    records.sort(key=lambda r: r["enqueued_at"] or "")
    return records
