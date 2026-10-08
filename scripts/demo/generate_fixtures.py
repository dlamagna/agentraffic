"""Build the static-demo fixtures for the AgentVerse UI from recorded paper runs.

Usage::

    python -m scripts.demo.generate_fixtures --source data/att-paper \
        [--out ui/data/private/fixtures] [--max-kb 500] [--no-check]

``--source`` is a (sparse) checkout of ``paper-branch`` of ``dlamagna/agentraffic``.
The script reads every ``data/agentverse/balanced_agents4_*/tasks/*/response.json.gz`` (or
``response.json``), picks one representative run per topology x task category (3 x 4 = 12),
sanitises it, and writes::

    <out>/<topology>/<task>.response.json   schema unchanged, renders with renderers.js as-is
    <out>/<topology>/<task>.events.json     SSE replay, only if scripts.demo.sse_events imports;
                                            the final ``complete`` event's data is
                                            {"$ref": "<task>.response.json"}
    <out>/index.json                        provenance manifest

Nothing is written unless every check passes. Re-running on the same source gives byte-identical
files.

Discussion-stage IATs
---------------------
Same definition as ``collect_iats()`` in the paper's
``scripts/experiment/agentverse/_compute_table2.py``. Take the run's ``llm_requests`` whose
``label`` starts with one of the topology's discussion prefixes (``DISCUSSION_PREFIXES``). Sort
their ``start_time_utc`` and take consecutive differences. All iterations of a run are pooled, so a
gap between iterations counts as one IAT. A run needs at least two such requests. The burst
fraction is the share of IATs below 50 ms. Pooled over all runs this gives exactly the paper's
Table 2 values: n = 6513 / 7355 / 14493 IATs, median 4.56 s / 0.41 ms / 236 ms, and burst
fraction 0 % / 53.3 % / 38.2 % (Sequential / Star / Full Mesh). The check step prints this
comparison.

Selection (one run per topology x category)
-------------------------------------------
1. Candidates must have ``completed == true``, no ``llm_requests[].error``, a topology that matches
   the request labels, and at least two discussion-stage requests.
2. Only runs with the group's *modal* iteration count are kept (ties go to fewer iterations). That
   mode is 1 in all 12 groups: single-iteration runs are 50-99 % of each group. A second iteration
   is a full re-run of the workflow after a low evaluation score. Mixing 1- and 3-iteration runs
   gives medians that no real run has, e.g. 18 discussion calls for Star/coding, where real runs
   have 12, 24 or 36. So the fixture is a typical single-pass run, and its medians are taken over
   that pool.
3. Each candidate gets a distance to the pool's median on three features: the number of
   discussion-stage LLM calls, ``duration_seconds`` and the discussion-stage burst fraction. Each
   deviation is divided by the pool's IQR for that feature. If the IQR is 0 (more than half the
   runs share the median value), the mean absolute deviation is used instead, so off-median values
   score as clearly atypical. A feature with no spread at all is ignored. The distance is the
   Euclidean norm of the scaled deviations.
4. Ranking key: (passes the qualitative burst check, fits under ``--max-kb`` after sanitisation,
   distance, task dir name). The burst check is: Star / Full Mesh have at least one discussion
   IAT < 50 ms, Sequential has none. So a run that fails it is replaced by the next-best one, and a
   run that would need truncation is only used if no run in the pool fits. Sizes are computed
   lazily in rank order.

Sanitisation (whole response, recursively)
------------------------------------------
* Any URL / ``host:port`` whose host is a private or loopback IPv4 address (10/8, 172.16/12,
  192.168/16, 127/8, 169.254/16) gets a service name based on the port. Scheme, port and path are
  kept: ``:8000`` -> ``llm``, ``:8101`` -> ``agent-a``, ``:8102-8109`` -> ``agent-b``, anything
  else -> ``internal-host``. A bare private IP with no scheme and no port, e.g. in LLM-generated
  example code, becomes ``<redacted-ip>``.
* Every ``otel`` key is dropped (request-level ``otel`` and ``llm_meta.otel``, i.e. trace / span
  IDs). The UI never reads them.
* The serialised output (response, events and index) is then scanned for private IPs,
  IPv6-loopback/ULA/link-local URL hosts, home-directory paths, the author's username, internal
  DNS suffixes in URLs and surviving ``otel`` / ``trace_id`` / ``span_id`` keys. Any hit aborts with
  exit code 3.

Truncation
----------
Truncation only happens if a sanitised fixture is still over ``--max-kb`` (UTF-8 bytes of the
written file). The longest ``prompt`` / ``response`` strings are capped at a common length, found
by binary search for the largest cap that fits ("water-filling"), and get the suffix
``TRUNCATION_MARKER``. No other field is touched, including timing and ``llm_meta`` fields.

Exit codes: 0 ok, 1 sanity check failed (skip with ``--no-check``), 2 bad input / impossible
truncation, 3 sensitive data detected.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "ui" / "data" / "private" / "fixtures"
CONFIG_JS = REPO_ROOT / "ui" / "playground" / "js" / "config.js"

SCHEMA_VERSION = 1
GENERATION_NOTE = "recorded runs from the paper experiments"
SOURCE_REPO = "dlamagna/agentraffic"
SOURCE_BRANCH = "paper-branch"
EXPERIMENT_GLOB = "balanced_agents4_*"
TABLE2_RELPATH = Path("data/agentverse/combined_agents4_analysis/plots/paper/table2.md")

TOPOLOGIES = ("horizontal", "vertical", "full_mesh")
TOPOLOGY_LABELS = {"horizontal": "Sequential", "vertical": "Star", "full_mesh": "Full Mesh"}
CATEGORY_TO_TASK = {
    "mathematical-problem": "math",
    "research-task": "research",
    "consulting": "consulting",
    "software-development": "coding",
}
TASKS = ("math", "research", "consulting", "coding")

# Exactly the per-structure label prefixes of _compute_table2.py (PREFIXES).
DISCUSSION_PREFIXES = {
    "horizontal": ("horizontal_discussion", "synthesize_discussion"),
    "vertical": (
        "horizontal_discussion",
        "synthesize_discussion",
        "vertical_solver",
        "vertical_reviewer",
    ),
    "full_mesh": ("full_mesh_message", "synthesize_discussion"),
}
BURST_THRESHOLD_S = 0.05
FEATURES = ("n_disc_calls", "duration_s", "burst_fraction")

# Fallback when table2.md is not in the source checkout (values as printed in the paper).
PAPER_TABLE2_FALLBACK = {
    "horizontal": {"n_runs": 500, "n_iats": 6513, "median_iat_s": 4.56, "burst_pct": 0.0},
    "vertical": {"n_runs": 481, "n_iats": 7355, "median_iat_s": 0.00041, "burst_pct": 53.3},
    "full_mesh": {"n_runs": 500, "n_iats": 14493, "median_iat_s": 0.236, "burst_pct": 38.2},
}
# Allowed deviation of the dataset-level numbers from table2.md before the check fails.
TOL_COUNT_REL = 0.005
TOL_TIME_REL = 0.05
TOL_BURST_PP = 1.0

TRUNCATION_MARKER = "… [truncated for demo]"
TRUNCATABLE_KEYS = frozenset({"prompt", "response"})
MIN_KEEP_CHARS = 200

DROP_KEYS = frozenset({"otel"})
REDACTED_IP = "<redacted-ip>"
SERVICE_BY_PORT = {8000: "llm", 8101: "agent-a"}
AGENT_B_PORTS = range(8102, 8110)
DEFAULT_SERVICE = "internal-host"

_O = r"\d{1,3}"
PRIVATE_IPV4 = (
    rf"(?:10\.{_O}\.{_O}\.{_O}"
    rf"|172\.(?:1[6-9]|2\d|3[01])\.{_O}\.{_O}"
    rf"|192\.168\.{_O}\.{_O}"
    rf"|127\.{_O}\.{_O}\.{_O}"
    rf"|169\.254\.{_O}\.{_O})"
)
_HOST_RE = re.compile(
    r"(?P<scheme>\b[A-Za-z][A-Za-z0-9+.-]*://)?"
    rf"(?<![\d.])(?P<ip>{PRIVATE_IPV4})(?!\d)"
    r"(?::(?P<port>\d{1,5})(?!\d))?"
)

LEAK_PATTERNS: dict[str, re.Pattern[str]] = {
    "private IPv4 address": re.compile(rf"(?<![\d.]){PRIVATE_IPV4}(?!\d)"),
    "IPv6 loopback/ULA/link-local host": re.compile(
        r"(?i)://\[(?:::1|fe80:[0-9a-f:]*|f[cd][0-9a-f]{2}:[0-9a-f:]*)\]"
    ),
    "home directory path": re.compile(
        r"(?:/home/|/Users/)[A-Za-z0-9_.-]+|(?<![\w.])/root/|[A-Za-z]:\\\\Users\\\\"
    ),
    # The public GitHub owner in repo slugs (provenance) is fine; anything else is not.
    "username": re.compile(r"(?i)dlamagna(?!/agentraffic\b)"),
    "internal hostname": re.compile(
        r"(?i)://[\w.-]+\.(?:local|lan|internal|localdomain|home\.arpa)(?![\w-])"
    ),
    "telemetry key": re.compile(r'(?<!\\)"(?:otel|trace_id|span_id)"\s*:'),
}

_TASK_DIR_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(?P<category>[a-z-]+)_(?P<uuid>[0-9a-f-]{36})$"
)


class LeakError(RuntimeError):
    """Sensitive data survived sanitisation."""


class TruncationError(ValueError):
    """A fixture cannot be brought under the size limit."""


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def dumps(obj: Any) -> str:
    """Serialise exactly as written to disk (compact indent, UTF-8, trailing newline)."""
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def encoded_size(obj: Any) -> int:
    return len(dumps(obj).encode("utf-8"))


# ---------------------------------------------------------------------------
# IATs
# ---------------------------------------------------------------------------


def parse_ts(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def is_discussion_label(label: Any, topology: str) -> bool:
    return isinstance(label, str) and label.startswith(DISCUSSION_PREFIXES[topology])


def discussion_iats(requests: Iterable[dict], topology: str) -> list[float]:
    """Within-run discussion-stage IATs in seconds (paper Table 2 definition)."""
    ts = sorted(
        t
        for t in (
            parse_ts(r.get("start_time_utc"))
            for r in requests
            if is_discussion_label(r.get("label"), topology)
        )
        if t is not None
    )
    return [b - a for a, b in zip(ts, ts[1:])]


def burst_fraction(iats: list[float], threshold: float = BURST_THRESHOLD_S) -> float:
    return sum(1 for x in iats if x < threshold) / len(iats) if iats else 0.0


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile, identical to numpy's default."""
    if not values:
        raise ValueError("percentile of empty sequence")
    xs = sorted(values)
    h = (len(xs) - 1) * q / 100.0
    lo = math.floor(h)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (h - lo) * (xs[hi] - xs[lo])


def iat_summary(iats: list[float]) -> dict:
    if not iats:
        return {"n": 0, "median_s": None, "p95_s": None, "burst_fraction": 0.0}
    return {
        "n": len(iats),
        "median_s": round(statistics.median(iats), 6),
        "p95_s": round(percentile(iats, 95), 6),
        "burst_fraction": round(burst_fraction(iats), 4),
    }


def shows_expected_burst(topology: str, iats: list[float]) -> bool:
    """Qualitative paper finding: Star / Full Mesh fan out (< 50 ms IATs), Sequential never."""
    has_burst = any(x < BURST_THRESHOLD_S for x in iats)
    return not has_burst if topology == "horizontal" else has_burst


def label_topology(requests: Iterable[dict]) -> str | None:
    """Topology implied by request labels (same rules as _compute_table2.collect_iats)."""
    labels = [str(r.get("label", "")) for r in requests]
    if any(lb.startswith("full_mesh_message") for lb in labels):
        return "full_mesh"
    if any(lb.startswith(("vertical_solver", "vertical_reviewer")) for lb in labels):
        return "vertical"
    if any(lb.startswith("horizontal_discussion") for lb in labels):
        return "horizontal"
    return None


# ---------------------------------------------------------------------------
# Run summaries
# ---------------------------------------------------------------------------


@dataclass
class RunSummary:
    experiment: str
    task_dir: str
    path: Path
    category: str
    topology: str
    task_id: str = ""
    completed: bool = True
    n_errors: int = 0
    iterations: int = 1
    duration_s: float = 0.0
    n_llm_calls: int = 0
    n_disc_calls: int = 0
    disc_iats: list[float] = field(default_factory=list)
    total_tokens: int = 0
    score: Any = None
    start_utc: str | None = None
    original_task: str = ""
    labels_topology: str | None = None

    @property
    def task(self) -> str:
        return CATEGORY_TO_TASK[self.category]

    @property
    def burst_fraction(self) -> float:
        return burst_fraction(self.disc_iats)

    @property
    def valid(self) -> bool:
        return (
            self.completed is True
            and self.n_errors == 0
            and self.labels_topology == self.topology
            and len(self.disc_iats) >= 1
        )

    def feature(self, name: str) -> float:
        return float(getattr(self, name))


def summarise_run(doc: dict, experiment: str, task_dir: str, path: Path) -> RunSummary | None:
    m = _TASK_DIR_RE.match(task_dir)
    if not m or m.group("category") not in CATEGORY_TO_TASK:
        return None
    topology = (doc.get("stages", {}).get("decision", {}) or {}).get("structure_used")
    if topology not in TOPOLOGIES:
        return None
    requests = doc.get("llm_requests") or []
    starts = sorted(
        (r["start_time_utc"] for r in requests if parse_ts(r.get("start_time_utc")) is not None),
        key=parse_ts,
    )
    return RunSummary(
        experiment=experiment,
        task_dir=task_dir,
        path=path,
        category=m.group("category"),
        topology=topology,
        task_id=str(doc.get("task_id", "")),
        completed=doc.get("completed") is True,
        n_errors=sum(1 for r in requests if r.get("error")),
        iterations=int(doc.get("iterations") or 1),
        duration_s=float(doc.get("duration_seconds") or 0.0),
        n_llm_calls=len(requests),
        n_disc_calls=sum(1 for r in requests if is_discussion_label(r.get("label"), topology)),
        disc_iats=discussion_iats(requests, topology),
        total_tokens=sum(int((r.get("llm_meta") or {}).get("total_tokens") or 0) for r in requests),
        score=(doc.get("stages", {}).get("evaluation", {}) or {}).get("score"),
        start_utc=starts[0] if starts else None,
        original_task=str(doc.get("original_task", "")),
        labels_topology=label_topology(requests),
    )


def find_response_files(source: Path) -> list[tuple[str, str, Path]]:
    """(experiment, task_dir, path) for every recorded response, sorted."""
    found = []
    for exp_dir in sorted((source / "data" / "agentverse").glob(EXPERIMENT_GLOB)):
        tasks = exp_dir / "tasks"
        if not tasks.is_dir():
            continue
        for task_dir in sorted(p for p in tasks.iterdir() if p.is_dir()):
            for name in ("response.json.gz", "response.json"):
                if (task_dir / name).is_file():
                    found.append((exp_dir.name, task_dir.name, task_dir / name))
                    break
    return found


def load_response(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text(encoding="utf-8"))


def scan_source(source: Path) -> tuple[list[RunSummary], list[str]]:
    runs: list[RunSummary] = []
    warnings: list[str] = []
    for experiment, task_dir, path in find_response_files(source):
        try:
            doc = load_response(path)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"unreadable {experiment}/{task_dir}: {exc}")
            continue
        run = summarise_run(doc, experiment, task_dir, path)
        if run is None:
            warnings.append(f"skipped {experiment}/{task_dir}: unknown category/topology")
            continue
        if run.labels_topology != run.topology:
            warnings.append(
                f"{experiment}/{task_dir}: structure_used={run.topology} but labels say "
                f"{run.labels_topology}; excluded from selection"
            )
        runs.append(run)
    return runs, warnings


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


@dataclass
class Selection:
    run: RunSummary
    distance: float
    fits: bool
    size_bytes: int
    n_runs: int
    n_valid: int
    n_pool: int
    modal_iterations: int
    targets: dict[str, float]


def modal_iterations(runs: list[RunSummary]) -> int:
    counts: dict[int, int] = {}
    for r in runs:
        counts[r.iterations] = counts.get(r.iterations, 0) + 1
    return min(counts, key=lambda k: (-counts[k], k))


def _robust_scale(values: list[float], median: float) -> float:
    iqr = percentile(values, 75) - percentile(values, 25)
    if iqr > 0:
        return iqr
    return sum(abs(v - median) for v in values) / len(values)


def rank_candidates(pool: list[RunSummary]) -> tuple[list[tuple[float, RunSummary]], dict]:
    """Return [(distance, run)] sorted by (distance, task_dir) and the per-feature targets."""
    targets: dict[str, float] = {}
    scales: dict[str, float] = {}
    for f in FEATURES:
        vals = [r.feature(f) for r in pool]
        targets[f] = statistics.median(vals)
        scales[f] = _robust_scale(vals, targets[f])
    ranked = []
    for r in pool:
        d2 = sum(((r.feature(f) - targets[f]) / scales[f]) ** 2 for f in FEATURES if scales[f] > 0)
        ranked.append((round(math.sqrt(d2), 9), r))
    ranked.sort(key=lambda dr: (dr[0], dr[1].task_dir, dr[1].experiment))
    return ranked, targets


def select_representative(
    runs: list[RunSummary], size_fn: Callable[[RunSummary], int], max_bytes: int
) -> Selection:
    """Pick the representative run of one topology x category group (see module docstring)."""
    valid = [r for r in runs if r.valid]
    if not valid:
        raise ValueError("no valid candidate runs")
    mode = modal_iterations(valid)
    pool = [r for r in valid if r.iterations == mode]
    ranked, targets = rank_candidates(pool)
    # Never trade the qualitative burst check for size: only fall back to failing runs if no
    # run in the pool passes (the sanity check then reports it).
    tier = [dr for dr in ranked if shows_expected_burst(dr[1].topology, dr[1].disc_iats)]
    tier = tier or ranked
    chosen: tuple[float, RunSummary, int] | None = None
    for dist, run in tier:
        size = size_fn(run)
        if size <= max_bytes:
            chosen = (dist, run, size)
            break
    if chosen is None:  # nothing fits: take the closest run and truncate it
        dist, run = tier[0]
        chosen = (dist, run, size_fn(run))
    dist, run, size = chosen
    return Selection(
        run=run,
        distance=dist,
        fits=size <= max_bytes,
        size_bytes=size,
        n_runs=len(runs),
        n_valid=len(valid),
        n_pool=len(pool),
        modal_iterations=mode,
        targets={k: round(v, 6) for k, v in targets.items()},
    )


# ---------------------------------------------------------------------------
# Sanitisation and leak check
# ---------------------------------------------------------------------------


def _service_for_port(port: int | None) -> str:
    if port is None:
        return DEFAULT_SERVICE
    if port in AGENT_B_PORTS:
        return "agent-b"
    return SERVICE_BY_PORT.get(port, DEFAULT_SERVICE)


def _replace_host(m: re.Match[str]) -> str:
    scheme, port = m.group("scheme"), m.group("port")
    if not scheme and not port:
        return REDACTED_IP
    host = _service_for_port(int(port) if port else None)
    return f"{scheme or ''}{host}{':' + port if port else ''}"


def sanitise_text(text: str) -> str:
    return _HOST_RE.sub(_replace_host, text)


def sanitise(obj: Any) -> Any:
    """Return a sanitised deep copy: private-IP hosts replaced, ``otel`` keys dropped."""
    if isinstance(obj, dict):
        return {
            sanitise_text(k) if isinstance(k, str) else k: sanitise(v)
            for k, v in obj.items()
            if k not in DROP_KEYS
        }
    if isinstance(obj, list):
        return [sanitise(v) for v in obj]
    if isinstance(obj, str):
        return sanitise_text(obj)
    return obj


def find_leaks(text: str) -> list[str]:
    hits = []
    for name, pattern in LEAK_PATTERNS.items():
        for m in pattern.finditer(text):
            ctx = text[max(0, m.start() - 40) : m.end() + 40].replace("\n", " ")
            hits.append(f"{name}: {m.group(0)!r} in ...{ctx}...")
            if len(hits) >= 20:
                return hits
    return hits


def assert_no_leaks(text: str, where: str) -> None:
    hits = find_leaks(text)
    if hits:
        raise LeakError(f"sensitive data in {where}:\n  " + "\n  ".join(hits))


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def _truncatable_lengths(obj: Any, out: list[int]) -> list[int]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in TRUNCATABLE_KEYS and isinstance(v, str):
                out.append(len(v))
            else:
                _truncatable_lengths(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _truncatable_lengths(v, out)
    return out


def _cap(obj: Any, cap: int, counter: list[int]) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in TRUNCATABLE_KEYS and isinstance(v, str):
                if len(v) > cap + len(TRUNCATION_MARKER):
                    v = v[:cap] + TRUNCATION_MARKER
                    counter[0] += 1
                out[k] = v
            else:
                out[k] = _cap(v, cap, counter)
        return out
    if isinstance(obj, list):
        return [_cap(v, cap, counter) for v in obj]
    return obj


def truncate_to_fit(doc: dict, max_bytes: int) -> tuple[dict, dict]:
    """Cap the longest prompt/response strings so ``dumps(doc)`` fits in ``max_bytes``."""
    size = encoded_size(doc)
    if size <= max_bytes:
        return doc, {"truncated": False, "truncated_strings": 0, "cap_chars": None}
    lengths = _truncatable_lengths(doc, [])
    hi = max(lengths, default=0)
    lo = MIN_KEEP_CHARS
    floor_doc = _cap(doc, lo, [0])
    if hi <= lo or encoded_size(floor_doc) > max_bytes:
        raise TruncationError(
            f"cannot fit under {max_bytes} bytes even with prompt/response capped at "
            f"{MIN_KEEP_CHARS} chars (now {size} bytes); raise --max-kb"
        )
    # Largest cap in [lo, hi) that fits; size is monotone non-decreasing in cap.
    best = lo
    left, right = lo + 1, hi - 1
    while left <= right:
        mid = (left + right) // 2
        if encoded_size(_cap(doc, mid, [0])) <= max_bytes:
            best, left = mid, mid + 1
        else:
            right = mid - 1
    counter = [0]
    capped = _cap(doc, best, counter)
    return capped, {"truncated": True, "truncated_strings": counter[0], "cap_chars": best}


# ---------------------------------------------------------------------------
# EXAMPLE_TASKS comparison
# ---------------------------------------------------------------------------


def parse_example_tasks(config_js: str) -> dict[str, str]:
    block = re.search(r"EXAMPLE_TASKS\s*=\s*\{(.*?)\n\};", config_js, re.S)
    if not block:
        return {}
    return {k: v for k, v in re.findall(r"(\w+)\s*:\s*`([^`]*)`", block.group(1))}


def normalise_task_text(text: str) -> str:
    """Collapse whitespace and drop the ``||`` prefix left by run_experiment.sh's IFS split."""
    return " ".join(text.lstrip("| \t\n").split())


# ---------------------------------------------------------------------------
# Paper Table 2
# ---------------------------------------------------------------------------


def _parse_duration(s: str) -> float:
    m = re.match(r"\s*([\d.]+)\s*(ms|s)\b", s)
    if not m:
        raise ValueError(f"unparseable duration {s!r}")
    return float(m.group(1)) / (1000.0 if m.group(2) == "ms" else 1.0)


def parse_table2(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {t: {} for t in TOPOLOGIES}
    names = {"Sequential": "horizontal", "Star": "vertical", "Full Mesh": "full_mesh"}
    for prefix, key in (("Runs:", "n_runs"), ("Pooled IATs", "n_iats")):
        line = next((ln for ln in text.splitlines() if ln.startswith(prefix)), "")
        for label, n in re.findall(r"(Sequential|Star|Full Mesh) n=(\d+)", line):
            out[names[label]][key] = int(n)
    for ln in text.splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] == "**Median IAT**":
            for topo, cell in zip(TOPOLOGIES, cells[1:4]):
                out[topo]["median_iat_s"] = _parse_duration(cell)
        elif cells[0].startswith("**Burst fraction"):
            for topo, cell in zip(TOPOLOGIES, cells[1:4]):
                out[topo]["burst_pct"] = float(cell.rstrip("%"))
    if not all(len(v) == 4 for v in out.values()):
        raise ValueError("table2.md is missing expected rows")
    return out


def load_paper_table2(source: Path) -> tuple[dict[str, dict], str]:
    path = source / TABLE2_RELPATH
    if path.is_file():
        try:
            return parse_table2(path.read_text(encoding="utf-8")), str(TABLE2_RELPATH)
        except ValueError as exc:
            print(f"warning: {exc}; using built-in Table 2 values", file=sys.stderr)
    return PAPER_TABLE2_FALLBACK, "built-in copy of table2.md"


def dataset_stats(runs: list[RunSummary]) -> dict[str, dict]:
    stats = {}
    for topo in TOPOLOGIES:
        group = [r for r in runs if r.topology == topo]
        pooled = [x for r in group for x in r.disc_iats]
        summary = iat_summary(pooled)
        stats[topo] = {
            "n_runs": len(group),
            "n_iats": summary["n"],
            "median_iat_s": summary["median_s"],
            "p95_iat_s": summary["p95_s"],
            "burst_pct": round(summary["burst_fraction"] * 100, 2),
        }
    return stats


# (row label, stats key, relative deviation?, tolerance)
_PAPER_CHECKS = (
    ("pooled IATs", "n_iats", True, TOL_COUNT_REL),
    ("median IAT (s)", "median_iat_s", True, TOL_TIME_REL),
    ("burst <50ms (%)", "burst_pct", False, TOL_BURST_PP),
)


def compare_with_paper(stats: dict, paper: dict) -> list[dict]:
    rows = []
    for topo in TOPOLOGIES:
        for metric, key, relative, tol in _PAPER_CHECKS:
            dv, pv = stats[topo][key], paper[topo][key]
            dev = abs((dv or 0) - pv)
            if relative:
                dev = dev / abs(pv) if pv else dev
            rows.append(
                {"topology": topo, "metric": metric, "dataset": dv, "paper": pv, "ok": dev <= tol}
            )
    return rows


# ---------------------------------------------------------------------------
# Fixture rendering and writing
# ---------------------------------------------------------------------------


def load_events_builder() -> Callable[[dict], list[dict]] | None:
    try:
        from scripts.demo.sse_events import build_events
    except ImportError as exc:
        print(f"warning: scripts.demo.sse_events not importable ({exc}); no events.json")
        return None
    return build_events


def dedupe_complete_event(events: list[dict], response: dict, response_name: str) -> list[dict]:
    """Replace the final ``complete`` event's payload with ``{"$ref": <response file>}``.

    ``complete`` carries the whole response, which would roughly double every events file. The
    mock backend resolves the ref (relative to the events file) back to ``<task>.response.json``.
    """
    if events and events[-1]["event"] == "complete" and events[-1]["data"] == response:
        events = events[:-1] + [{**events[-1], "data": {"$ref": response_name}}]
    return events


def render_fixture(
    topology: str,
    task: str,
    response: dict,
    events_builder: Callable[[dict], list[dict]] | None,
) -> dict[str, str]:
    """The per-fixture output: relative path -> file text. Every file is leak-checked."""
    files = {f"{topology}/{task}.response.json": dumps(response)}
    if events_builder is not None:
        events = events_builder(copy.deepcopy(response))
        events = dedupe_complete_event(events, response, f"{task}.response.json")
        files[f"{topology}/{task}.events.json"] = dumps(events)
    for rel, text in files.items():
        assert_no_leaks(text, rel)
    return files


def write_files(out_dir: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def build_fixture(sel: Selection, max_bytes: int, events_builder) -> tuple[dict, dict, dict]:
    response = sanitise(load_response(sel.run.path))
    response, trunc = truncate_to_fit(response, max_bytes)
    files = render_fixture(sel.run.topology, sel.run.task, response, events_builder)
    return response, trunc, files


def manifest_entry(
    sel: Selection, trunc: dict, files: dict[str, str], example_tasks: dict[str, str]
) -> dict:
    r = sel.run
    rel_resp = f"{r.topology}/{r.task}.response.json"
    rel_ev = f"{r.topology}/{r.task}.events.json"
    recorded = normalise_task_text(sanitise_text(r.original_task))
    example = example_tasks.get(r.task)
    return {
        "topology": r.topology,
        "topology_label": TOPOLOGY_LABELS[r.topology],
        "task": r.task,
        "category": r.category,
        "task_id": r.task_id,
        "experiment": r.experiment,
        "task_dir": r.task_dir,
        "recorded_start_utc": r.start_utc,
        "duration_s": r.duration_s,
        "iterations": r.iterations,
        "n_llm_calls": r.n_llm_calls,
        "n_discussion_calls": r.n_disc_calls,
        "total_tokens": r.total_tokens,
        "evaluation_score": r.score,
        "discussion_iat": iat_summary(r.disc_iats),
        "original_task": recorded,
        "matches_example_task": example is not None and normalise_task_text(example) == recorded,
        "truncated": trunc["truncated"],
        "truncated_strings": trunc["truncated_strings"],
        "selection": {
            "distance": sel.distance,
            "group_runs": sel.n_runs,
            "valid_runs": sel.n_valid,
            "pool_runs": sel.n_pool,
            "pool_iterations": sel.modal_iterations,
            "pool_medians": sel.targets,
        },
        "files": {
            "response": rel_resp,
            "response_bytes": len(files[rel_resp].encode("utf-8")),
            "events": rel_ev if rel_ev in files else None,
            "events_bytes": len(files[rel_ev].encode("utf-8")) if rel_ev in files else None,
        },
    }


def build_manifest(
    entries: list[dict], stats: dict, paper: dict, paper_src: str, max_kb: int
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "note": GENERATION_NOTE,
        "source": {
            "repository": SOURCE_REPO,
            "branch": SOURCE_BRANCH,
            "experiments": sorted({e["experiment"] for e in entries}),
            "table2": paper_src,
        },
        "generator": "scripts/demo/generate_fixtures.py",
        "max_kb": max_kb,
        "selection": (
            "per topology x category: completed runs without request errors and with the modal "
            "iteration count; closest to the group median of (discussion-stage LLM calls, "
            "duration_seconds, discussion-stage burst fraction), IQR-normalised; prefer runs "
            "passing the burst check and fitting under max_kb; tie-break by task dir name"
        ),
        "iat_definition": (
            "within-run diffs of sorted start_time_utc of discussion-stage llm_requests "
            "(label prefixes per topology, as in _compute_table2.py); burst = IAT < 50 ms"
        ),
        "dataset": {
            topo: {**stats[topo], "paper": paper[topo], "label": TOPOLOGY_LABELS[topo]}
            for topo in TOPOLOGIES
        },
        "fixtures": entries,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _fmt_s(x: float | None) -> str:
    if x is None:
        return "-"
    if abs(x) < 1.0:
        return f"{x * 1000:.2f} ms"
    return f"{x:.2f} s"


def print_table(headers: list[str], rows: list[list[Any]]) -> None:
    cells = [[str(c) for c in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)))


def _dataset_value(metric: str, v: float) -> str:
    if metric.startswith("median"):
        return _fmt_s(v)
    if metric.startswith("burst"):
        return f"{v:.1f}%"
    return str(v)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", type=Path, required=True, help="paper-branch checkout")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="fixtures output directory")
    ap.add_argument("--max-kb", type=int, default=500, help="max uncompressed fixture size (KB)")
    ap.add_argument("--no-check", action="store_true", help="do not fail on the sanity check")
    args = ap.parse_args(argv)
    max_bytes = args.max_kb * 1024

    runs, warnings = scan_source(args.source)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not runs:
        print(f"error: no runs under {args.source}/data/agentverse/{EXPERIMENT_GLOB}/tasks")
        return 2
    print(f"scanned {len(runs)} runs from {len({r.experiment for r in runs})} experiments")

    example_tasks = parse_example_tasks(CONFIG_JS.read_text(encoding="utf-8"))
    events_builder = load_events_builder()

    size_cache: dict[Path, int] = {}

    def size_fn(run: RunSummary) -> int:
        if run.path not in size_cache:
            size_cache[run.path] = encoded_size(sanitise(load_response(run.path)))
        return size_cache[run.path]

    selections: list[Selection] = []
    for topo in TOPOLOGIES:
        for task in TASKS:
            group = [r for r in runs if r.topology == topo and r.task == task]
            if not group:
                print(f"error: no runs for {topo} x {task}")
                return 2
            selections.append(select_representative(group, size_fn, max_bytes))

    all_files: dict[str, str] = {}
    entries = []
    try:
        for sel in selections:
            _, trunc, files = build_fixture(sel, max_bytes, events_builder)
            all_files.update(files)
            entries.append(manifest_entry(sel, trunc, files, example_tasks))
    except TruncationError as exc:
        print(f"error: {exc}")
        return 2
    except LeakError as exc:
        print(f"error: {exc}")
        return 3

    print("\nSelected runs")
    print_table(
        ["topology", "task", "disc calls", "duration", "burst", "KB", "trunc", "dist", "pool"],
        [
            [
                e["topology"],
                e["task"],
                e["n_discussion_calls"],
                f"{e['duration_s']:.1f} s",
                f"{e['discussion_iat']['burst_fraction'] * 100:.1f}%",
                f"{e['files']['response_bytes'] / 1024:.0f}",
                "yes" if e["truncated"] else "no",
                f"{e['selection']['distance']:.3f}",
                f"{e['selection']['pool_runs']}/{e['selection']['group_runs']}",
            ]
            for e in entries
        ],
    )

    print("\nRecorded task text vs ui/playground/js/config.js EXAMPLE_TASKS")
    for task in TASKS:
        e = next(x for x in entries if x["task"] == task)
        status = "match" if e["matches_example_task"] else "MISMATCH"
        print(f"  {task:<10} {status:<8} recorded: {e['original_task'][:90]}")

    failures = 0
    print("\nSanity check: fixture discussion-stage IATs")
    rows = []
    for sel, e in zip(selections, entries):
        r = sel.run
        n_burst = sum(1 for x in r.disc_iats if x < BURST_THRESHOLD_S)
        ok = shows_expected_burst(r.topology, r.disc_iats)
        failures += not ok
        expected = "none < 50 ms" if r.topology == "horizontal" else "some < 50 ms"
        rows.append(
            [r.topology, r.task, len(r.disc_iats), n_burst, expected, "ok" if ok else "FAIL"]
        )
    print_table(["topology", "task", "IATs", "< 50 ms", "expected", "result"], rows)

    stats = dataset_stats(runs)
    paper, paper_src = load_paper_table2(args.source)
    print(f"\nSanity check: dataset-level discussion IATs vs paper ({paper_src})")
    rows = []
    for c in compare_with_paper(stats, paper):
        failures += not c["ok"]
        rows.append(
            [
                TOPOLOGY_LABELS[c["topology"]],
                c["metric"],
                _dataset_value(c["metric"], c["dataset"]),
                _dataset_value(c["metric"], c["paper"]),
                "ok" if c["ok"] else "DEVIATES",
            ]
        )
    print_table(["topology", "metric", "dataset", "paper", "result"], rows)

    manifest = build_manifest(entries, stats, paper, paper_src, args.max_kb)
    manifest_text = dumps(manifest)
    try:
        assert_no_leaks(manifest_text, "index.json")
    except LeakError as exc:
        print(f"error: {exc}")
        return 3

    if failures and not args.no_check:
        print(f"\nerror: {failures} sanity check(s) failed; nothing written (use --no-check)")
        return 1

    if events_builder is None:
        for e in entries:
            stale = args.out / f"{e['topology']}/{e['task']}.events.json"
            if stale.exists():
                stale.unlink()
    write_files(args.out, all_files)
    write_files(args.out, {"index.json": manifest_text})
    print(f"\nwrote {len(all_files)} fixture files + index.json to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
