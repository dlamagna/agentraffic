"""
Queue runner daemon.

Polls the queue for PENDING jobs and executes them one at a time.
After each job the per-results queue_manifest.json is written.

Run directly:
    python -m scripts.queue.job_runner [--poll-interval N]

Or via the MCP tool: queue_start_daemon / queue_stop_daemon.
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.queue.job_types import (  # noqa: E402
    JobType,
    JOB_CONFIGS,
    build_command,
    testbed_lifecycle_flags,
    will_reset_testbed,
    will_shutdown_testbed_when_done,
)
from scripts.queue.queue_manager import (                                   # noqa: E402
    CURRENT_JOB_PID,
    DAEMON_PID,
    DAEMON_LOG,
    QUEUE_DIR,
    append_history,
    clear_pause_request,
    get_job,
    next_pending_job,
    pending_count,
    read_pause_request,
    update_job,
    write_job_manifest,
)

DEFAULT_POLL_INTERVAL = 5  # seconds
DEFAULT_GPU_WAIT_POLL_INTERVAL = 60
DEFAULT_GPU_WAIT_TIMEOUT = None


def _existing_job_runner_pid() -> Optional[int]:
    if not DAEMON_PID.exists():
        return None
    try:
        old = int(DAEMON_PID.read_text().strip())
    except ValueError:
        return None
    if old == os.getpid():
        return None
    try:
        Path(f"/proc/{old}").stat()
    except OSError:
        return None
    try:
        cmd = (Path(f"/proc/{old}/cmdline").read_bytes().replace(b"\x00", b" ")).decode(
            "utf-8", errors="replace"
        )
    except OSError:
        return None
    if "job_runner" in cmd:
        return old
    return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _setup_logging() -> logging.Logger:
    DAEMON_LOG.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("queue_runner")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%dT%H:%M:%S")
    fh = logging.FileHandler(DAEMON_LOG)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _append_experiment_log(experiment_log_file: str, event: dict[str, Any]) -> None:
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    path = Path(experiment_log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def _prepare_run_log_paths(job: dict) -> tuple[str, str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    short_id = job["id"][:8]
    run_dir = REPO_ROOT / "queue" / "logs" / "experiments" / f"{ts}_{job['type']}_{short_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    latest_link = REPO_ROOT / "queue" / "logs" / "latest"
    try:
        if latest_link.is_symlink() or latest_link.exists():
            latest_link.unlink()
        latest_link.symlink_to(run_dir, target_is_directory=True)
    except OSError:
        pass

    stdout_file = str(run_dir / "stdout.log")
    experiment_log_file = str(run_dir / "experiment_log.jsonl")
    return str(run_dir), stdout_file, experiment_log_file


def _write_run_config(run_dir: str, payload: dict[str, Any]) -> None:
    cfg_path = Path(run_dir) / "config.json"
    cfg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _sync_experiment_log_into_output(output_path: str, experiment_log_file: str) -> str | None:
    out = Path(output_path)
    target_dir = out.parent if out.suffix else out
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / "experiment_log.jsonl"
        shutil.copy2(experiment_log_file, target)
        return str(target)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# GPU availability wait
# ---------------------------------------------------------------------------

def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _gpu_wait_requested(params: dict[str, Any]) -> bool:
    return _truthy(params.get("wait_for_gpu_free"))


def _gpu_compute_processes() -> tuple[list[dict[str, str]], str | None]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader,nounits"],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return [], "nvidia-smi not found"
    except subprocess.TimeoutExpired:
        return [], "nvidia-smi timed out"
    except Exception as exc:
        return [], f"nvidia-smi failed: {exc}"

    if result.returncode != 0:
        return [], f"nvidia-smi exited {result.returncode}: {result.stderr.strip()}"

    processes: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(",", maxsplit=2)]
        while len(parts) < 3:
            parts.append("")
        processes.append({
            "pid": parts[0], "process_name": parts[1], "used_memory_mib": parts[2],
        })
    return processes, None


def _wait_for_gpu_free(
    job_id: str,
    params: dict[str, Any],
    logger: logging.Logger,
    experiment_log_file: str,
) -> Optional[bool]:
    if not _gpu_wait_requested(params):
        return True

    try:
        poll_interval = int(params.get("gpu_wait_poll_interval_s", DEFAULT_GPU_WAIT_POLL_INTERVAL))
    except (TypeError, ValueError):
        poll_interval = DEFAULT_GPU_WAIT_POLL_INTERVAL
    poll_interval = max(1, poll_interval)

    timeout_raw = params.get("gpu_wait_timeout_s", DEFAULT_GPU_WAIT_TIMEOUT)
    try:
        timeout_s = None if timeout_raw in (None, "", 0, "0") else float(timeout_raw)
    except (TypeError, ValueError):
        timeout_s = None

    wait_started = time.time()
    wait_started_iso = datetime.fromtimestamp(wait_started, timezone.utc).isoformat()
    logger.info("Job %s waiting for GPU (poll=%ss timeout=%s)",
                job_id[:8], poll_interval, "none" if timeout_s is None else f"{timeout_s:g}s")
    update_job(job_id, status="waiting_for_gpu", gpu_wait_started_at=wait_started_iso,
               gpu_wait_poll_interval_s=poll_interval, gpu_wait_timeout_s=timeout_s)
    _append_experiment_log(experiment_log_file, {
        "event": "gpu_wait_started", "job_id": job_id,
        "poll_interval_s": poll_interval, "timeout_s": timeout_s,
    })

    last_log = 0.0
    while True:
        current_job = get_job(job_id)
        if current_job is None or current_job.get("status") == "cancelled":
            logger.info("GPU wait cancelled for job %s", job_id[:8])
            return None

        processes, error = _gpu_compute_processes()
        now = time.time()
        waited_s = now - wait_started

        if error is not None:
            logger.error("GPU wait cannot continue: %s", error)
            return False

        if not processes:
            logger.info("GPU free; launching job %s after %.1fs wait", job_id[:8], waited_s)
            update_job(job_id, gpu_wait_completed_at=datetime.now(timezone.utc).isoformat(),
                       gpu_wait_seconds=round(waited_s, 1))
            return True

        if timeout_s is not None and waited_s >= timeout_s:
            logger.error("Timed out waiting for GPU after %.1fs; processes=%s", waited_s, processes)
            return False

        if now - last_log >= max(30, poll_interval):
            logger.info("GPU busy for job %s; processes=%s", job_id[:8], processes)
            update_job(job_id, gpu_wait_last_check_at=datetime.now(timezone.utc).isoformat(),
                       gpu_wait_active_processes=processes, gpu_wait_seconds=round(waited_s, 1))
            last_log = now

        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Output path generation
# ---------------------------------------------------------------------------

def _generate_output_path(job: dict) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    short_id = job["id"][:8]
    # The run_agentverse.sh script writes JSONL files inside this directory
    rel = f"data/agentverse/experiment_{ts}_{short_id}"
    return str(REPO_ROOT / rel)


def _find_actual_output(job: dict, output_path: str, started_at_ts: float) -> str:
    jt = JobType(job["type"])
    cfg = JOB_CONFIGS[jt]

    if cfg.output_flag is not None:
        return output_path

    pattern = str(REPO_ROOT / cfg.output_glob)
    matches = glob.glob(pattern)
    fresh = [m for m in matches if os.path.getmtime(m) >= started_at_ts - 5]
    if not fresh:
        return output_path
    return max(fresh, key=os.path.getmtime)


# ---------------------------------------------------------------------------
# Testbed lifecycle helpers
# ---------------------------------------------------------------------------

def _run_lifecycle_script(script: str, logger: logging.Logger, label: str) -> bool:
    """Run a deploy script; return True on success."""
    path = REPO_ROOT / script
    if not path.exists():
        logger.warning(f"Lifecycle script not found, skipping {label}: {path}")
        return False
    logger.info(f"Lifecycle: {label} ({path})")
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / ".local" / "bin") + ":" + env.get("PATH", "")
    try:
        result = subprocess.run(
            [str(path)], cwd=str(REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            logger.warning(f"  {label} exited {result.returncode}: {result.stderr.strip()[:200]}")
            return False
        logger.info(f"  {label} completed OK")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"  {label} timed out after 300s")
        return False
    except Exception as e:
        logger.error(f"  {label} failed: {e}")
        return False


def _generate_plots(output_path: str, logger: logging.Logger) -> None:
    script = REPO_ROOT / "scripts" / "analysis" / "plot_paper_figures.py"
    venv_python = REPO_ROOT / ".venv" / "bin" / "python3"
    python = str(venv_python) if venv_python.exists() else sys.executable
    logger.info(f"Generating paper figures for {output_path}")
    env = os.environ.copy()
    env["PATH"] = str(Path.home() / ".local" / "bin") + ":" + env.get("PATH", "")
    try:
        result = subprocess.run(
            [python, str(script), output_path],
            cwd=str(REPO_ROOT), env=env,
            capture_output=True, text=True, timeout=600,
        )
        for line in result.stdout.splitlines():
            logger.info(f"  [plots] {line}")
        if result.returncode != 0:
            logger.warning(f"  plot script exited {result.returncode}: {result.stderr.strip()[:300]}")
        else:
            logger.info("  Paper figures generated OK")
    except Exception as e:
        logger.error(f"  Plot generation failed: {e}")


# ---------------------------------------------------------------------------
# Job execution
# ---------------------------------------------------------------------------

def _run_job(job: dict, logger: logging.Logger) -> None:
    job_id   = job["id"]
    job_type = job["type"]
    params   = job.get("params", {})
    notes    = job.get("notes", "")

    output_path = _generate_output_path(job)
    run_log_dir, stdout_file, experiment_log_file = _prepare_run_log_paths(job)

    logger.info(f"Starting job {job_id[:8]} type={job_type}  notes={notes!r}")
    logger.info(f"  output_path={output_path}")

    claimed_at_ts = time.time()
    update_job(job_id,
               status="waiting_for_gpu" if _gpu_wait_requested(params) else "running",
               started_at=(
                   None if _gpu_wait_requested(params)
                   else datetime.fromtimestamp(claimed_at_ts, timezone.utc).isoformat()
               ),
               output_path=output_path,
               stdout_file=stdout_file,
               experiment_log_file=experiment_log_file)
    _write_run_config(run_log_dir, {
        "queue_job_id":    job_id,
        "job_type":        job_type,
        "notes":           notes,
        "params":          params,
        "output_path_planned": output_path,
        "stdout_file":     stdout_file,
        "experiment_log_file": experiment_log_file,
        "host":            os.uname().nodename,
        "runner_claimed_at": datetime.fromtimestamp(claimed_at_ts, timezone.utc).isoformat(),
        "expected_duration": job.get("expected_duration"),
    })

    # Tear down our own stack first so our vLLM doesn't show up in the GPU wait
    if will_reset_testbed(JobType(job_type), params):
        _run_lifecycle_script("scripts/deploy/stop.sh", logger, "reset_testbed_at_start (stop)")

    # GPU wait now sees only truly external processes
    gpu_wait_result = _wait_for_gpu_free(job_id, params, logger, experiment_log_file)
    if gpu_wait_result is None:
        return
    if not gpu_wait_result:
        _finish_job(job_id, 1, output_path, stdout_file, experiment_log_file, logger)
        return

    if will_reset_testbed(JobType(job_type), params):
        _run_lifecycle_script("scripts/deploy/deploy.sh", logger, "reset_testbed_at_start (deploy)")

    started_at_ts = time.time()
    update_job(job_id, status="running",
               started_at=datetime.fromtimestamp(started_at_ts, timezone.utc).isoformat())

    try:
        cmd = build_command(JobType(job_type), params, output_path, str(REPO_ROOT))
    except Exception as e:
        logger.error(f"Failed to build command for job {job_id[:8]}: {e}")
        _finish_job(job_id, 1, output_path, stdout_file, experiment_log_file, logger)
        return

    logger.info(f"  cmd={' '.join(cmd)}")
    _append_experiment_log(experiment_log_file, {
        "event": "job_started", "job_id": job_id, "job_type": job_type,
        "notes": notes, "output_path": output_path, "cmd": cmd,
        "params": params, "expected_duration": job.get("expected_duration"),
    })

    env = os.environ.copy()
    venv_bin = REPO_ROOT / ".venv" / "bin"
    if venv_bin.is_dir():
        env["PATH"] = str(venv_bin) + ":" + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(REPO_ROOT / ".venv")
    env["EXPERIMENT_LOG_FILE"] = experiment_log_file

    exit_code = -1
    try:
        with open(stdout_file, "w") as lf:
            proc = subprocess.Popen(cmd, cwd=str(REPO_ROOT), env=env,
                                    stdout=lf, stderr=subprocess.STDOUT)
            CURRENT_JOB_PID.write_text(str(proc.pid))
            try:
                exit_code = proc.wait()
            finally:
                CURRENT_JOB_PID.unlink(missing_ok=True)
    except FileNotFoundError as e:
        logger.error(f"Command not found: {e}")
        exit_code = 127
    except Exception as e:
        logger.error(f"Unexpected error running job {job_id[:8]}: {e}")
        exit_code = -1

    actual_output = _find_actual_output(job, output_path, started_at_ts)
    _finish_job(job_id, exit_code, actual_output, stdout_file, experiment_log_file, logger)

    if will_shutdown_testbed_when_done(JobType(job_type), params):
        _run_lifecycle_script("scripts/deploy/stop.sh", logger, "shutdown_testbed_when_done")

    if _truthy(params.get("generate_plots")):
        _generate_plots(actual_output, logger)


def _finish_job(
    job_id: str,
    exit_code: int,
    output_path: str,
    stdout_file: str,
    experiment_log_file: str,
    logger: logging.Logger,
) -> None:
    status = "completed" if exit_code == 0 else "failed"
    completed_at = datetime.now(timezone.utc).isoformat()

    logger.info(f"Job {job_id[:8]} finished  status={status}  exit={exit_code}")

    updated = update_job(job_id, status=status, completed_at=completed_at,
                         exit_code=exit_code, output_path=output_path,
                         stdout_file=stdout_file, experiment_log_file=experiment_log_file)
    copied_log = _sync_experiment_log_into_output(output_path, experiment_log_file)
    _append_experiment_log(experiment_log_file, {
        "event": "job_finished", "job_id": job_id, "job_type": updated.get("type"),
        "status": status, "exit_code": exit_code, "output_path": output_path,
        "started_at": updated.get("started_at"), "completed_at": completed_at,
        "expected_duration": updated.get("expected_duration"),
        "actual_duration_s": (
            (datetime.fromisoformat(completed_at) -
             datetime.fromisoformat(updated.get("started_at"))).total_seconds()
            if updated.get("started_at") else None
        ),
        "output_experiment_log_file": copied_log,
    })

    try:
        manifest_path = write_job_manifest(updated, output_path)
        logger.info(f"  manifest={manifest_path}")
    except Exception as e:
        logger.warning(f"Failed to write job manifest: {e}")

    append_history(updated)
    logger.info("  appended to history")


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------

class QueueRunner:
    def __init__(self, poll_interval: int = DEFAULT_POLL_INTERVAL) -> None:
        self.poll_interval = poll_interval
        self._stop = False
        self.logger = _setup_logging()

    def start(self) -> None:
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        other = _existing_job_runner_pid()
        if other is not None:
            self.logger.error(
                "Refusing to start: another queue runner is already running (PID %s). "
                "Stop it first (queue_stop_daemon).",
                other,
            )
            sys.exit(1)
        DAEMON_PID.write_text(str(os.getpid()))
        clear_pause_request()
        self.logger.info(f"Queue runner daemon started (PID={os.getpid()})")
        self.logger.info(f"  poll_interval={self.poll_interval}s")

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT,  self._handle_signal)

        try:
            self._loop()
        finally:
            self._cleanup()

    def _handle_signal(self, signum: int, _frame) -> None:
        self.logger.info(f"Received signal {signum}, stopping after current job…")
        self._stop = True

    def _loop(self) -> None:
        idle_logged = False

        while not self._stop:
            pause_req = read_pause_request()
            if pause_req is not None:
                self.logger.info("Pause requested; stopping daemon.")
                clear_pause_request()
                self._stop = True
                break

            job = next_pending_job()
            if job is None:
                if not idle_logged:
                    self.logger.info("Queue is empty — daemon idle, waiting for new jobs.")
                    idle_logged = True
                time.sleep(self.poll_interval)
                continue

            idle_logged = False
            _run_job(job, self.logger)

        self.logger.info("Runner stopping.")

    def _cleanup(self) -> None:
        if DAEMON_PID.exists():
            try:
                DAEMON_PID.unlink()
            except OSError:
                pass
        self.logger.info("Queue runner daemon exited.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="agentraffic queue runner daemon")
    p.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL,
                   help=f"Seconds between queue polls (default: {DEFAULT_POLL_INTERVAL})")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    runner = QueueRunner(poll_interval=args.poll_interval)
    runner.start()
