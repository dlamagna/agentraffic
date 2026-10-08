"""Write the public data set (``ui/data/public/``) from the private one (``ui/data/private/``).

Usage::

    python -m scripts.demo.export_public [--src ui/data/private] [--out ui/data/public]

Reads ``summary.json``, ``traffic.json``, ``load.json`` and ``workflow.json`` from ``--src`` (stdlib
only) and writes, deterministically:

``summary.json``   the private summary filtered through an **allow-list** of top-level and nested
                   keys (``SUMMARY_ALLOW``): a key that is not listed is dropped, so a field a later
                   export adds never reaches the public site by accident. ``fixtures`` (the
                   task-id mapping of the recorded runs), ``source.files`` and everything per run
                   are not on the list. What stays are aggregates: Table 2, IAT histograms and
                   fits, the metric catalogue, Spearman matrices, per-topology / per-task
                   statistics, per-topology quantile tables, the scaling histograms.
``traffic.json``, ``load.json``, ``workflow.json``
                   aggregates already; copied byte for byte once the leak check passes.
``manifest.json``  ``{"mode": "public", "synthetic": true}``

Nothing else in ``--out`` is touched: ``runs.json`` and ``fixtures/`` (the synthetic runs and
replays, ``scripts/demo/generate_synthetic.py``) live next to these files.

Every output goes through ``assert_no_leaks`` (private IPs, home paths, usernames, trace keys)
and a check for UUID / trace-id shaped strings (task ids). Exit codes: 0 ok, 2 bad input,
3 sensitive data in the output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts.demo.export_results import dumps_summary
from scripts.demo.generate_fixtures import REPO_ROOT, LeakError, assert_no_leaks

DEFAULT_SRC = REPO_ROOT / "ui" / "data" / "private"
DEFAULT_OUT = REPO_ROOT / "ui" / "data" / "public"

#: Files copied unchanged (all aggregates), after the leak check.
COPIED = ("traffic.json", "load.json", "workflow.json")
MANIFEST = {"mode": "public", "synthetic": True}

# In an allow-list ``True`` keeps the whole subtree; a dict keeps only the listed keys (and
# applies its values to those); a key missing from the data is simply absent from the output.
SUMMARY_ALLOW: dict[str, Any] = {
    "schema_version": True,
    "generator": True,
    "source": {
        "repository": True,
        "branch": True,
        "n_runs": True,
        "n_runs_total": True,
        "join": {
            "runs": True,
            "csv_rows": True,
            "matched_by_order": True,
            "matched_by_fingerprint": True,
            "unmatched_runs": True,
            "ambiguous_runs": True,
            "unused_csv_rows": True,
            "match_rate": True,
            "method": True,
        },
    },
    "topologies": True,
    "tasks": True,
    "table2": {
        "title": True,
        "runs": True,
        "pooled_iats": True,
        "notes": True,
        "sections": True,
        "footnotes": True,
    },
    "iat": {
        "definition": True,
        "burst_threshold_s": True,
        "bins_s": True,
        "linear_bins_s": True,
        "bins_note": True,
        "per_topology": True,
        "fit_scope": True,
        "fits": True,
    },
    "metrics": True,
    "layers": True,
    "correlations": {
        "method": True,
        "metric_keys": True,
        "groups": True,
        "selected": True,
        "paper_heatmap": True,
    },
    "aggregates": {"stats": True, "by_topology": True, "by_topology_task": True},
    "quantile_grid": True,
    "quantiles": True,
    "scaling": True,
}

# Strings that identify one run: a UUID (task id) or a 32-hex trace id.
_ID_PATTERNS = {
    "UUID (task id)": re.compile(
        r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
    ),
    "32-hex trace id": re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{32}(?![0-9a-f])"),
}


def allow(obj: Any, spec: Any) -> Any:
    """``obj`` restricted to the keys ``spec`` allows (see ``SUMMARY_ALLOW``)."""
    if spec is True:
        return obj
    if not isinstance(obj, dict) or not isinstance(spec, dict):
        raise ValueError("allow-list expects an object where the spec lists keys")
    return {k: allow(v, spec[k]) for k, v in obj.items() if k in spec}


def public_summary(private: dict) -> dict:
    out = allow(private, SUMMARY_ALLOW)
    scaling = out.get("scaling")
    if isinstance(scaling, dict):
        # the scaling block names the experiment folders it was drawn from: keep the numbers only
        out["scaling"] = {
            **{k: v for k, v in scaling.items() if k != "definition"},
            "agents": [
                {k: v for k, v in a.items() if k != "experiments"} for a in scaling.get("agents", [])
            ],
        }
    return out


def find_ids(text: str, where: str) -> None:
    hits = []
    for name, pattern in _ID_PATTERNS.items():
        for m in pattern.finditer(text):
            hits.append(f"{name}: {m.group(0)!r}")
            if len(hits) >= 10:
                break
    if hits:
        raise LeakError(f"run identifiers in {where}:\n  " + "\n  ".join(hits))


def build(src: Path) -> dict[str, str]:
    """The public files as ``{name: text}``. Raises ValueError (bad input) or LeakError."""
    texts: dict[str, str] = {}
    try:
        private = json.loads((src / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {src / 'summary.json'}: {exc}") from exc
    texts["summary.json"] = dumps_summary(public_summary(private)) + "\n"
    for name in COPIED:
        try:
            texts[name] = (src / name).read_text(encoding="utf-8")
            json.loads(texts[name])
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {src / name}: {exc}") from exc
    for name, text in texts.items():
        assert_no_leaks(text, f"public {name}")
        find_ids(text, f"public {name}")
    texts["manifest.json"] = json.dumps(MANIFEST, separators=(",", ":")) + "\n"
    return texts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC, help="private data directory")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="public data directory")
    args = ap.parse_args(argv)
    try:
        texts = build(args.src)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    except LeakError as exc:
        print(f"error: {exc}")
        return 3
    args.out.mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (args.out / name).write_text(text, encoding="utf-8")
        print(f"wrote {args.out / name} ({len(text.encode('utf-8')) / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
