# One-command use of the website's data modes.
#
#   make data          regenerate the private data from data/att-paper, then the public data
#   make local         serve ui/ on :8080 in private mode (no-store caching)
#   make public        build dist/public/ (ui/ without data/private/) and serve it on :8081
#   make hooks         install the git pre-commit hook that runs scripts/demo/check_public.py
#   make check         run scripts/demo/check_public.py
#
# Override with e.g. `make local PORT=9000`, `make local BIND=127.0.0.1`, `make data SOURCE=/path/to/paper-branch`.

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
SOURCE ?= data/att-paper
PORT ?= 8080
# 0.0.0.0 so the Mac host can reach the VM; use `make local BIND=127.0.0.1` on a shared network.
BIND ?= 0.0.0.0
PUBLIC_PORT ?= 8081
# Git URL of the repository holding the paper's recorded runs (owner only; needed by `make data`).
SOURCE_REPO ?=

.PHONY: data local public dist-public hooks check

# The paper-branch checkout: sparse, responses only.
$(SOURCE)/data:
	@test -n "$(SOURCE_REPO)" || { echo "set SOURCE_REPO=<git url of the paper's data repository>"; exit 1; }
	git clone --depth 1 --branch paper-branch --filter=blob:none --no-checkout $(SOURCE_REPO) $(SOURCE)
	cd $(SOURCE) && git sparse-checkout set --no-cone \
	  'data/agentverse/balanced_agents4_*/tasks/*/response.json.gz' \
	  'data/agentverse/combined_agents4_analysis/' 'figures/' 'scripts/experiment/agentverse/' \
	  && git checkout paper-branch

# Fixtures first: export_results maps them to the runs. The synthetic runs (generate_synthetic.py)
# are built from the public aggregates, so they come last; skipped until that script exists.
data: $(SOURCE)/data
	$(PY) -m scripts.demo.generate_fixtures --source $(SOURCE)
	$(PY) -m scripts.demo.export_results --source $(SOURCE)
	$(PY) -m scripts.demo.export_public
	@if [ -f scripts/demo/generate_synthetic.py ]; then \
	  $(PY) -m scripts.demo.generate_synthetic; \
	else echo "(no scripts/demo/generate_synthetic.py yet: skipping the synthetic data)"; fi
	$(PY) scripts/demo/check_public.py

local:
	$(PY) scripts/demo/serve.py ui --port $(PORT) --bind $(BIND)

check:
	$(PY) scripts/demo/check_public.py

# The exact public preview: nothing from ui/data/private/ is copied.
# The old build goes first: the check below also inspects dist/public (no Beta page in it).
dist-public:
	rm -rf dist/public
	$(PY) scripts/demo/check_public.py
	mkdir -p dist
	cp -a ui dist/public
	rm -rf dist/public/data/private dist/public/results/beta
	$(PY) scripts/demo/check_public.py
	@echo "built dist/public ($$(du -sh dist/public | cut -f1))"

public: dist-public
	$(PY) scripts/demo/serve.py dist/public --port $(PUBLIC_PORT) --bind $(BIND)

hooks:
	$(PY) scripts/demo/check_public.py --install-hook
