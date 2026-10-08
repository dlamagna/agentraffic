# Public site on GitHub Pages (owner steps)

`.github/workflows/pages.yml` publishes `dist/public` (the site without `ui/data/private/`) on every
push to `main`. One setting is the owner's to make, once:

1. Repository *Settings > Pages > Build and deployment > Source:* **GitHub Actions**.
2. Push to `main` (or run the workflow by hand from the *Actions* tab). The site appears at
   `https://dlamagna.github.io/agentraffic/`; the URL is also shown on the workflow run.

The site is served under the `/agentraffic/` sub-path, so every URL in `ui/` is relative. Check that
locally, before pushing, with:

```bash
make dist-public
.venv/bin/python scripts/deploy/check_subpath.py    # needs Playwright and a browser
```

It serves `dist/public` under `/agentraffic/`, opens every page and fails on any 404, console error
or link that leaves the sub-path. It reports (as warnings) the synthetic data files that
`scripts/demo/generate_synthetic.py` has not produced yet; `--strict` makes them failures.
