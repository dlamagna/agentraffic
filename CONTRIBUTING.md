# Contributing to agentraffic

Thank you for your interest in contributing. This document covers everything you need to get started.

---

## Table of contents

1. [Development setup](#development-setup)
2. [Code style](#code-style)
3. [Running tests](#running-tests)
4. [Submitting a pull request](#submitting-a-pull-request)
5. [Reporting bugs](#reporting-bugs)

---

## Development setup

### Prerequisites

- Python 3.11+
- Docker with the NVIDIA container runtime (only needed to run the full stack)
- `shellcheck` (for linting shell scripts)

### Install Python dev dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs `black`, `ruff`, and `pytest` alongside the package.

### Configure environment

```bash
cp infra/.env.example infra/.env
# Edit infra/.env and set HF_TOKEN=hf_...
```

### Start the stack (GPU server only)

```bash
scripts/deploy/deploy.sh
scripts/deploy/deploy.sh --monitoring   # also starts Prometheus / Grafana
```

See [README.md](README.md) for the full quick-start guide.

---

## Code style

This project uses **black** for formatting and **ruff** for linting. Both are enforced in CI.

```bash
# Format
black agents/ llm/ scripts/

# Lint
ruff check agents/ llm/

# Lint shell scripts
shellcheck scripts/**/*.sh
```

Configuration lives in `pyproject.toml`.

---

## Running tests

Pure-Python tests (no GPU required) can run anywhere:

```bash
pytest tests/
```

Full-stack integration tests require the Docker stack to be up (GPU server only). See the `scripts/ci/` directory for the smoke-test script.

---

## Submitting a pull request

1. Fork the repository and create a feature branch off `main`.
2. Make your changes. Keep commits focused and atomic.
3. Ensure `black --check`, `ruff check`, and `pytest tests/` all pass locally.
4. Open a pull request against `main`. Fill in the PR template.
5. A maintainer will review and merge.

### What makes a good PR

- One logical change per PR.
- Tests for new behaviour where feasible without a GPU.
- If you're changing a prompt template, explain the motivation and, if possible, a sample before/after response.

---

## Reporting bugs

Please use the [GitHub Issues bug report form](../../issues/new?template=bug_report.yml).
Include the output of `docker compose config` and the relevant container logs.
