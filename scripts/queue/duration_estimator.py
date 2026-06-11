"""
Duration estimator for agentraffic queue jobs.

Provides estimate_job_duration(job_type, params) -> float (seconds) based on
empirical timing constants from the paper (Table 2).

Can also be run as a CLI:

    python -m scripts.queue.duration_estimator --type agentverse --runs 500
    python -m scripts.queue.duration_estimator --queue queue/state/queue.json
    python -m scripts.queue.duration_estimator --list-types
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.queue.job_types import JobType, JOB_CONFIGS  # noqa: E402


def estimate_job_duration(job_type: str | JobType, params: dict[str, Any]) -> float:
    """
    Return the estimated duration of a single job in seconds.
    Based on empirical per-run medians from the paper (Table 2).
    """
    jt = JobType(job_type)
    dc = JOB_CONFIGS[jt].duration_config

    if jt == JobType.AGENTVERSE:
        return _estimate_agentverse(params, dc)

    raise ValueError(f"Unknown job type: {jt}")


def estimate_queue_duration(jobs: list[dict[str, Any]]) -> float:
    """Return total estimated seconds for all pending/running jobs."""
    total = 0.0
    for job in jobs:
        if job.get("status", "pending") not in ("pending", "waiting_for_gpu", "running"):
            continue
        try:
            total += estimate_job_duration(job["type"], job.get("params", {}))
        except Exception:
            pass
    return total


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


# ---------------------------------------------------------------------------
# Per-type helpers
# ---------------------------------------------------------------------------

def _estimate_agentverse(params: dict, dc: dict) -> float:
    runs     = int(params.get("runs", 500))
    topology = params.get("topology", "all")
    prs = dc["per_run_seconds"]
    if topology == "all":
        per_run = sum(prs[t] for t in ("horizontal", "vertical", "full_mesh"))
    else:
        per_run = prs.get(topology, sum(prs.values()))
    return dc["setup_seconds"] + runs * per_run


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Estimate AgentVerse experiment duration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m scripts.queue.duration_estimator --type agentverse --runs 500 --topology horizontal
  python -m scripts.queue.duration_estimator --queue queue/state/queue.json
  python -m scripts.queue.duration_estimator --list-types
""",
    )
    p.add_argument("--type", dest="job_type", choices=["agentverse"],
                   help="Job type to estimate")
    p.add_argument("--queue", metavar="FILE",
                   help="Path to queue.json — estimate total pending duration")
    p.add_argument("--list-types", action="store_true",
                   help="List all supported job types and their parameters")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    # AgentVerse params
    p.add_argument("--runs",     type=int, help="Number of runs per topology (default: 500)")
    p.add_argument("--topology", type=str, help="horizontal | vertical | full_mesh | all")
    p.add_argument("--agents",   type=int)
    p.add_argument("--rounds",   type=int)

    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.list_types:
        for jt, cfg in JOB_CONFIGS.items():
            print(f"\n{jt.value}  —  {cfg.description}")
            for param, doc in cfg.param_docs.items():
                print(f"  {param:<20} {doc}")
        return

    if args.queue:
        queue_path = Path(args.queue)
        if not queue_path.exists():
            print(f"ERROR: queue file not found: {queue_path}", file=sys.stderr)
            sys.exit(1)
        with queue_path.open() as f:
            data = json.load(f)
        jobs = data.get("jobs", [])
        pending = [j for j in jobs if j.get("status") in ("pending", "waiting_for_gpu", "running")]
        total = estimate_queue_duration(pending)

        if args.json:
            per_job = []
            for j in pending:
                try:
                    secs = estimate_job_duration(j["type"], j.get("params", {}))
                except Exception:
                    secs = None
                per_job.append({
                    "id":               j["id"],
                    "type":             j["type"],
                    "estimated_seconds": secs,
                    "estimated_human":  format_duration(secs) if secs else "unknown",
                    "notes":            j.get("notes", ""),
                })
            print(json.dumps({
                "total_seconds": total,
                "total_human":   format_duration(total),
                "job_count":     len(pending),
                "jobs":          per_job,
            }, indent=2))
        else:
            print(f"Queue: {len(pending)} pending job(s)")
            print(f"Total estimated duration: {format_duration(total)}")
            print()
            for j in pending:
                try:
                    dur = format_duration(estimate_job_duration(j["type"], j.get("params", {})))
                except Exception:
                    dur = "unknown"
                notes = f" — {j['notes']}" if j.get("notes") else ""
                print(f"  [{j['id'][:8]}] {j['type']:<20} ~{dur}{notes}")
        return

    if not args.job_type:
        print("ERROR: --type or --queue is required", file=sys.stderr)
        sys.exit(1)

    params: dict[str, Any] = {}
    if args.runs:     params["runs"]     = args.runs
    if args.topology: params["topology"] = args.topology
    if args.agents:   params["agents"]   = args.agents
    if args.rounds:   params["rounds"]   = args.rounds

    secs = estimate_job_duration(args.job_type, params)

    if args.json:
        print(json.dumps({
            "type":              args.job_type,
            "params":            params,
            "estimated_seconds": secs,
            "estimated_human":   format_duration(secs),
        }, indent=2))
    else:
        print(f"Job type  : {args.job_type}")
        print(f"Params    : {params}")
        print(f"Estimated : ~{format_duration(secs)}")


if __name__ == "__main__":
    main()
