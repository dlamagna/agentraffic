"""Tests for scripts/demo/check_public.py, run against temporary git repositories."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.demo import check_public as cp

TASK_ID = "8fb8c4c9-9079-4f0d-b236-fd973b68c1e4"
PROMPT = "Compute the number of distinct ways to tile a three by ten board with dominoes."
RESPONSE = "The planner proposes a transfer matrix over the column profiles of the board."


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def write(root: Path, rel: str, content) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    write(root, "ui/data/public/summary.json", {"n_runs_total": 3})
    write(root, "ui/data/public/manifest.json", {"mode": "public", "synthetic": True})
    write(root, ".gitignore", "ui/data/private/\n")
    return root


def problems(root: Path) -> list[str]:
    return cp.run_checks(root)


def test_clean_repo_passes(repo):
    assert problems(repo) == []
    assert cp.main(["--root", str(repo)]) == 0


@pytest.mark.parametrize(
    "rel",
    [
        "ui/data/private/summary.json",
        "ui/results/data/runs.json",
        "ui/playground/fixtures/index.json",
        "ui/agentverse/fixtures/vertical/x.json",
    ],
)
def test_tracked_private_paths_fail_even_when_ignored(repo, rel, capsys):
    write(repo, rel, "{}")
    git(repo, "add", "-f", rel)  # staged counts, as in a pre-commit hook
    found = problems(repo)
    assert len(found) == 1 and rel in found[0]
    assert cp.main(["--root", str(repo)]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_untracked_ignored_private_data_is_fine(repo):
    write(repo, "ui/data/private/summary.json", {"fixtures": [{"task_id": TASK_ID}]})
    assert problems(repo) == []


def test_public_runs_must_be_synthetic(repo):
    runs = {
        "runs": [
            {"id": "syn-1", "synthetic": True},
            {"id": "syn-2"},
            {"id": "x", "synthetic": False},
        ]
    }
    write(repo, "ui/data/public/runs.json", runs)
    found = problems(repo)
    assert len(found) == 1 and "2 of 3" in found[0] and "syn-2" in found[0]
    runs["runs"] = [{"id": "syn-1", "synthetic": True}]
    write(repo, "ui/data/public/runs.json", runs)
    assert problems(repo) == []


def test_malformed_public_runs_are_reported(repo):
    write(repo, "ui/data/public/runs.json", "{not json")
    assert any("not a runs document" in p for p in problems(repo))


@pytest.mark.parametrize(
    "text, what",
    [
        ('{"u":"/home/someone/x"}', "home directory path"),
        ('{"u":"http://10.0.0.5:8101"}', "private IPv4"),
        ('{"trace_id":"abc"}', "telemetry key"),
        ('{"u":"dlamagna"}', "username"),
        ('{"id":"%s"}' % TASK_ID, "UUID"),
        ('{"id":"0123456789abcdef0123456789abcdef"}', "trace id"),
    ],
)
def test_leak_patterns_in_public_files_fail(repo, text, what):
    write(repo, "ui/data/public/fixtures/a.json", text)
    found = problems(repo)
    assert found and any(what in p for p in found)


def test_public_repo_slug_is_not_a_leak(repo):
    write(repo, "ui/data/public/x.json", '{"r":"dlamagna/agentraffic"}')
    assert problems(repo) == []


def make_private(repo: Path) -> None:
    write(
        repo,
        "ui/data/private/summary.json",
        {"fixtures": [{"task_id": TASK_ID, "run_id": "8fb8c4c9"}]},
    )
    write(repo, "ui/data/private/runs.json", {"runs": [{"id": "8fb8c4c9", "task_id": TASK_ID}]})
    write(repo, "ui/data/private/fixtures/index.json", {"fixtures": [{"original_task": PROMPT}]})
    write(
        repo,
        "ui/data/private/fixtures/vertical/math.response.json",
        {"llm_requests": [{"prompt": PROMPT, "response": RESPONSE, "label": "vertical_solver"}]},
    )


def test_real_ids_in_public_files_fail_when_private_data_exists(repo):
    make_private(repo)
    assert problems(repo) == []
    write(repo, "ui/data/public/runs.json", {"runs": [{"id": "8fb8c4c9", "synthetic": True}]})
    found = problems(repo)
    assert any("8fb8c4c9" in p for p in found)
    write(repo, "ui/data/public/runs.json", {"runs": [{"id": "syn-8fb8c4c9", "synthetic": True}]})
    assert problems(repo) == []  # only the exact quoted run id counts


def test_real_task_id_in_public_files_fails_even_without_the_pattern_check(repo):
    make_private(repo)
    write(repo, "ui/data/public/notes.txt", f"see {TASK_ID}")
    assert any("real run/task id" in p for p in problems(repo))


def test_real_prompt_and_response_text_fail_in_any_form(repo):
    make_private(repo)
    # decoded JSON string with escapes and different whitespace; text embedded in a longer string
    write(
        repo,
        "ui/data/public/fixtures/a.json",
        {"text": f"[syn]\n  {PROMPT.replace(' ', '  ')} (copy)"},
    )
    found = problems(repo)
    assert any("real prompt/response text" in p for p in found)
    (repo / "ui/data/public/fixtures/a.json").unlink()
    write(repo, "ui/data/public/fixtures/b.json", {"r": "x " + RESPONSE})
    assert any("real prompt/response text" in p for p in problems(repo))


def test_synthetic_text_and_short_labels_pass(repo):
    make_private(repo)
    write(
        repo,
        "ui/data/public/fixtures/a.json",
        {"text": "[synthetic] planner, round 2: proposes a plan", "k": "vertical_solver"},
    )
    assert problems(repo) == []


def test_text_already_in_committed_code_is_allowed(repo):
    make_private(repo)
    write(repo, "ui/data/public/fixtures/a.json", {"task": PROMPT})
    assert problems(repo) != []
    write(
        repo, "ui/playground/js/config.js", f"export const EXAMPLE_TASKS = {{ math: '{PROMPT}' }};"
    )
    assert problems(repo) == []


def test_beta_page_in_the_public_build_fails(repo):
    assert problems(repo) == []
    write(repo, "dist/public/results/beta/index.html", "<html></html>")
    found = problems(repo)
    assert any("results/beta" in p for p in found)


def test_beta_page_in_source_or_private_build_is_fine(repo):
    write(repo, "ui/results/beta/index.html", "<html></html>")
    write(repo, "dist/private/results/beta/index.html", "<html></html>")
    assert problems(repo) == []


def test_not_a_git_repo_is_reported(tmp_path):
    found = cp.check_tracked(tmp_path)
    assert found and "git" in found[0]


def test_install_hook_runs_the_check_and_blocks_a_bad_commit(repo):
    shutil.copytree(
        cp.REPO / "scripts", repo / "scripts", ignore=shutil.ignore_patterns("__pycache__", "queue")
    )
    assert cp.install_hook(repo) == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.is_file() and hook.stat().st_mode & 0o111
    assert cp.install_hook(repo) == 0  # re-installing our own hook is fine
    # a tracked private file makes the hook fail the commit
    write(repo, "ui/data/private/summary.json", "{}")
    git(repo, "add", "-f", "ui/data/private/summary.json")
    res = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"],
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0 and "private data is tracked" in res.stdout + res.stderr


def test_install_hook_does_not_overwrite_a_foreign_hook(repo):
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\necho mine\n")
    assert cp.install_hook(repo) == 1
    assert "mine" in hook.read_text()
