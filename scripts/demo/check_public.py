"""Guard: nothing private may be committed or published.

Usage::

    python scripts/demo/check_public.py [--root DIR] [--install-hook]

Exits 0 when everything is fine and 1 with one line per problem otherwise. Stdlib only. It checks:

1. **Tracked files.** Nothing under ``ui/data/private/`` (real data) or the old locations
   ``ui/results/data/``, ``ui/playground/fixtures/``, ``ui/agentverse/fixtures/`` is tracked by git
   (``git ls-files``, so staged files count).
2. **Synthetic flag.** Every run in ``ui/data/public/runs.json`` has ``"synthetic": true``.
3. **Leak patterns.** The files under ``ui/data/public/`` contain no private IPs, home paths,
   usernames, internal hostnames or telemetry keys (the patterns of ``generate_fixtures``), and no
   task id (UUID) or 32-hex trace id.
4. **Real content.** When ``ui/data/private/`` exists locally: no real task id, run id, task
   prompt or prompt / response text from it appears in the public files. Text that the
   committed code already contains (stage messages, the example tasks in ``config.js``) is
   allowed: the repository is public.

``--install-hook`` installs a git ``pre-commit`` hook that runs this script (``make hooks``).
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.demo.export_public import _ID_PATTERNS  # noqa: E402
from scripts.demo.generate_fixtures import LEAK_PATTERNS  # noqa: E402

FORBIDDEN_TRACKED = (
    "ui/data/private",
    "ui/results/data",
    "ui/playground/fixtures",
    "ui/agentverse/fixtures",
)
PUBLIC_DIR = Path("ui/data/public")
PRIVATE_DIR = Path("ui/data/private")
#: Committed code whose text may legitimately repeat recorded text (stage messages, the example
#: tasks in config.js, prompt templates): the repository is public, so it is already published.
ALLOWED_TEXT_DIRS = (Path("ui"), Path("agents"), Path("llm"))
ALLOWED_TEXT_SUFFIXES = {".js", ".html", ".py", ".json", ".md", ".txt"}
MIN_TEXT_LEN = 40  # shorter strings are labels, ids and timestamps, not prompts or responses
MIN_TEXT_WORDS = 5
FINGERPRINT_LEN = 60
TEXT_SUFFIXES = {".json", ".js", ".html", ".txt", ".md", ".csv", ".css", ".svg"}
HOOK_MARKER = "# agentraffic check_public hook"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strings(obj: Any) -> Iterator[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


def is_prose(text: str) -> bool:
    """Prompt / response text, as opposed to a label, id, timestamp or path."""
    return len(text) >= MIN_TEXT_LEN and len(text.split()) >= MIN_TEXT_WORDS


def public_files(root: Path) -> list[Path]:
    base = root / PUBLIC_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES)


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# Checks (each returns a list of problems)
# ---------------------------------------------------------------------------


def check_tracked(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", *FORBIDDEN_TRACKED],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        return [f"cannot list tracked files in {root} (is it a git repository?): {detail}"]
    files = [line for line in out.splitlines() if line]
    if not files:
        return []
    shown = ", ".join(files[:5]) + (f", ... ({len(files)} files)" if len(files) > 5 else "")
    return [
        f"private data is tracked by git: {shown}. Run `git rm -r --cached <path>`; "
        "it must stay gitignored (ui/data/private/ and the old data locations)."
    ]


def check_synthetic(root: Path) -> list[str]:
    path = root / PUBLIC_DIR / "runs.json"
    if not path.is_file():
        return []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        runs = doc["runs"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{rel(root, path)} is not a runs document ({exc})"]
    bad = [r.get("id", "?") if isinstance(r, dict) else "?" for r in runs]
    bad = [
        run_id
        for run_id, r in zip(bad, runs)
        if not (isinstance(r, dict) and r.get("synthetic") is True)
    ]
    if not bad:
        return []
    return [
        f'{rel(root, path)}: {len(bad)} of {len(runs)} public runs lack "synthetic": true '
        f"(first: {', '.join(map(str, bad[:5]))})"
    ]


def check_patterns(root: Path) -> list[str]:
    problems = []
    for path in public_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in {**LEAK_PATTERNS, **_ID_PATTERNS}.items():
            m = pattern.search(text)
            if m:
                ctx = text[max(0, m.start() - 30) : m.end() + 30].replace("\n", " ")
                problems.append(f"{rel(root, path)}: {name} {m.group(0)!r} in ...{ctx}...")
    return problems


def private_secrets(root: Path) -> tuple[set[str], set[str]]:
    """(exact identifiers, text fingerprints) of the real data present locally."""
    ids: set[str] = set()
    texts: set[str] = set()
    private = root / PRIVATE_DIR

    def add_doc(doc: Any) -> None:
        stack = [doc]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("task_id", "run_id") and isinstance(v, str):
                        ids.add(v)
                    stack.append(v)
            elif isinstance(o, list):
                stack.extend(o)
        for s in strings(doc):
            n = norm(s)
            if is_prose(n):
                texts.add(n[:FINGERPRINT_LEN])

    summary = private / "summary.json"
    if summary.is_file():
        try:
            for f in json.loads(summary.read_text(encoding="utf-8")).get("fixtures", []):
                for key in ("task_id", "run_id"):
                    if f.get(key):
                        ids.add(f[key])
        except ValueError:
            pass
    runs = private / "runs.json"
    if runs.is_file():
        try:
            for r in json.loads(runs.read_text(encoding="utf-8")).get("runs", []):
                if r.get("task_id"):
                    ids.add(r["task_id"])
                if r.get("id"):
                    ids.add(r["id"])
        except ValueError:
            pass
    fixtures = private / "fixtures"
    if fixtures.is_dir():
        for path in sorted(fixtures.rglob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if path.name == "index.json":  # metadata: only the recorded task prompts are text
                doc = [e.get("original_task", "") for e in doc.get("fixtures", [])]
            add_doc(doc)
    return ids, texts


def committed_text(root: Path) -> Iterator[str]:
    for d in ALLOWED_TEXT_DIRS:
        for p in sorted((root / d).rglob("*")) if (root / d).is_dir() else []:
            if (
                p.suffix in ALLOWED_TEXT_SUFFIXES
                and p.is_file()
                and PRIVATE_DIR.parent not in p.relative_to(root).parents
            ):
                yield p.read_text(encoding="utf-8", errors="replace")


def check_real_content(root: Path) -> list[str]:
    if not (root / PRIVATE_DIR).is_dir():
        return []
    ids, texts = private_secrets(root)
    allowed = " ".join(norm(t) for t in committed_text(root))
    texts = {t for t in texts if t not in allowed}
    long_fps = {t for t in texts if len(t) >= FINGERPRINT_LEN}
    short_fps = sorted(t for t in texts if len(t) < FINGERPRINT_LEN)

    def leaked_text(hay: str) -> str | None:
        # a private string that is embedded anywhere in `hay` starts at some offset: look up
        # every FINGERPRINT_LEN window (long strings) and search for the short ones whole
        for i in range(len(hay) - FINGERPRINT_LEN + 1):
            if hay[i : i + FINGERPRINT_LEN] in long_fps:
                return hay[i : i + FINGERPRINT_LEN]
        return next((fp for fp in short_fps if fp in hay), None)

    problems = []
    for path in public_files(root):
        raw = path.read_text(encoding="utf-8", errors="replace")
        hays = [norm(raw)]
        if path.suffix == ".json":
            try:  # JSON escapes (\n, \", \u00e9) hide text in the raw file: look at the decoded strings
                hays = [norm(x) for x in strings(json.loads(raw))]
            except ValueError:
                pass
        name = rel(root, path)
        for ident in sorted(ids):
            if (ident in raw) if len(ident) > 8 else (f'"{ident}"' in raw):
                problems.append(f"{name}: real run/task id {ident} from ui/data/private/")
        for hay in hays:
            hit = leaked_text(hay) if len(hay) >= MIN_TEXT_LEN else None  # shorter: can't hold one
            if hit:
                problems.append(f"{name}: real prompt/response text from ui/data/private/: {hit!r}")
                break  # one per file is enough to fail
    return problems


def check_dist(root: Path) -> list[str]:
    """A built dist/public/ must not contain the Beta page (served only on the owner's machine)."""
    beta = root / "dist" / "public" / "results" / "beta"
    if beta.exists():
        return ["dist/public/results/beta/ exists: the Beta page must not be in the public build"]
    return []


def run_checks(root: Path) -> list[str]:
    problems = check_tracked(root)
    problems += check_dist(root)
    problems += check_synthetic(root)
    problems += check_patterns(root)
    problems += check_real_content(root)
    return problems


# ---------------------------------------------------------------------------
# Pre-commit hook
# ---------------------------------------------------------------------------

HOOK = f"""#!/bin/sh
{HOOK_MARKER}: installed by `make hooks`
root=$(git rev-parse --show-toplevel) || exit 1
py="$root/.venv/bin/python"
[ -x "$py" ] || py=python3
exec "$py" "$root/scripts/demo/check_public.py" --root "$root"
"""


def install_hook(root: Path) -> int:
    try:
        hooks = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"check_public: cannot find the git hooks directory: {exc}")
        return 1
    hook = (root / hooks) if not Path(hooks).is_absolute() else Path(hooks)
    hook = hook / "pre-commit"
    if hook.exists() and HOOK_MARKER not in hook.read_text(encoding="utf-8", errors="replace"):
        print(f"check_public: {hook} exists and is not ours; add this to it by hand:")
        print("  python3 scripts/demo/check_public.py || exit 1")
        return 1
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(HOOK, encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"check_public: installed {hook}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=REPO, help="repository root (default: this one)")
    ap.add_argument("--install-hook", action="store_true", help="install the git pre-commit hook")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.install_hook:
        return install_hook(root)
    problems = run_checks(root)
    if problems:
        print("check_public: FAILED, nothing private may be committed or published:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("check_public: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
