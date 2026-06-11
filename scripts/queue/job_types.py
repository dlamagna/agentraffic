"""
Job type definitions and command builders for the agentraffic experiment queue.

Only one job type is supported: agentverse.
The command builder receives the job's params dict and a pre-determined
output_dir string and returns a list[str] ready for subprocess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Job type registry
# ---------------------------------------------------------------------------

class JobType(str, Enum):
    AGENTVERSE = "agentverse"


@dataclass
class JobTypeConfig:
    description: str
    script: Optional[str]
    python_module: Optional[str]
    output_glob: str
    output_flag: Optional[str]
    duration_config: dict[str, Any]
    param_docs: dict[str, str] = field(default_factory=dict)


JOB_CONFIGS: dict[JobType, JobTypeConfig] = {

    JobType.AGENTVERSE: JobTypeConfig(
        description="AgentVerse multi-agent workflow experiment",
        script="scripts/experiment/run_agentverse.sh",
        python_module=None,
        output_glob="data/agentverse/experiment_*",
        output_flag="-o",
        duration_config={
            # Empirical per-run times from observed queue jobs (5-run and 100-run samples).
            # For topology="all" the estimator sums all three values (not averages),
            # because N runs with topology=all executes N runs × 3 topologies.
            "setup_seconds": 30,
            "per_run_seconds": {
                "horizontal": 101,
                "vertical":   129,
                "full_mesh":  39,
            },
        },
        param_docs={
            "topology":                  "str  — horizontal | vertical | full_mesh | all (default: all)",
            "runs":                      "int  — repetitions per topology (default: 500)",
            "agents":                    "int  — recruited sub-agents (default: 4)",
            "rounds":                    "int  — full-mesh discussion rounds (default: 3)",
            "host":                      "str  — Agent A host (default: localhost)",
            "port":                      "int  — Agent A port (default: 8101)",
            "reset_testbed_at_start":    "bool — run deploy.sh before the job starts (default: true)",
            "shutdown_testbed_when_done": "bool — run stop.sh after the job finishes (default: true)",
            "generate_plots":            "bool — run scripts/analysis/plot_paper_figures.py on the output dir after the experiment (default: false)",
        },
    ),
}


# ---------------------------------------------------------------------------
# Lifecycle flags
# ---------------------------------------------------------------------------

def _lifecycle_flag(params: dict[str, Any], key: str) -> bool:
    """Read a lifecycle bool param; defaults to True if absent."""
    v = params.get(key, True)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() not in ("0", "false", "no", "off")
    return bool(v)


def testbed_lifecycle_flags(job_type: JobType, params: dict[str, Any]) -> tuple[bool, bool]:
    """Return (reset_testbed_at_start, shutdown_testbed_when_done). Both default to True."""
    return (_lifecycle_flag(params, "reset_testbed_at_start"),
            _lifecycle_flag(params, "shutdown_testbed_when_done"))


def will_reset_testbed(job_type: JobType, params: dict[str, Any]) -> bool:
    return _lifecycle_flag(params, "reset_testbed_at_start")


def will_shutdown_testbed_when_done(job_type: JobType, params: dict[str, Any]) -> bool:
    return _lifecycle_flag(params, "shutdown_testbed_when_done")


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def build_command(
    job_type: JobType,
    params: dict[str, Any],
    output_path: str,
    repo_root: str,
) -> list[str]:
    cfg = JOB_CONFIGS[job_type]
    if job_type == JobType.AGENTVERSE:
        return _build_agentverse(params, output_path, repo_root, cfg)
    raise ValueError(f"Unknown job type: {job_type}")


def _script(cfg: JobTypeConfig, repo_root: str) -> str:
    assert cfg.script is not None
    return os.path.join(repo_root, cfg.script)


def _build_agentverse(
    params: dict, output_path: str, repo_root: str, cfg: JobTypeConfig
) -> list[str]:
    cmd = [_script(cfg, repo_root)]
    if params.get("topology"):
        cmd.extend(["-t", str(params["topology"])])
    if params.get("runs") is not None:
        cmd.extend(["-n", str(params["runs"])])
    if params.get("agents") is not None:
        cmd.extend(["-a", str(params["agents"])])
    if params.get("rounds") is not None:
        cmd.extend(["-r", str(params["rounds"])])
    if params.get("host"):
        cmd.extend(["-H", str(params["host"])])
    if params.get("port") is not None:
        cmd.extend(["-p", str(params["port"])])
    # Pass output directory so results land in the job-tracked path
    cmd.extend(["-o", output_path])
    return cmd
