"""End-to-end smoke test of the AgentVerse static demo (``ui/playground`` + ``js/mock-backend.js``).

Usage::

    .venv/bin/python scripts/demo/smoke_test.py [--data private|public] [--browser firefox|chromium]
        [--headed] [--screenshots DIR] [--only CASE [CASE ...]] [--list]

``--data private`` (the default) serves ``ui/`` with ``http.server`` on a free port, with the real
data in ``ui/data/private/``, and drives a headless browser (Firefox by default) through the demo
with Playwright. ``--data public`` serves the built ``dist/public/`` tree instead (``make
dist-public``: no private data, so it runs without any and can run in CI) and runs only the
``public`` case. Every other case needs the private data and runs in private mode only.

``fixtures``   every topology x task fixture replays to "Complete" with no console/page errors,
               the UI's LLM request count, final output and stage-2 discussion match the recorded
               response, and discussion rounds (incl. full-mesh) appear live, before completion
``cancel``     cancelling mid-run stops the replay, shows "Cancelled", re-enables Run; a new run
               afterwards completes
``speed``      switching the banner's speed selector from 1x to 20x mid-run takes effect at once
``demo-flag``  ``?demo=0``: no banner and requests really go to the Agent A endpoint (and fail);
               no flag and no backend: demo mode switches itself on
``custom``     a custom task shows the banner's "Custom tasks..." note and replays the math run
``examples``   the example buttons load the recorded task texts
``edges``      the topology diagram bolds each call's edge: one at a time for Sequential,
               bursts for Star / Full Mesh (at 5x and 20x)
``viewer``     ``playground/open/`` by ``?task_id=`` and ``?json=``, the old agentverse/viewer/
               redirect, the app's ``?task_id=`` deep link and the banner's provenance link all
               render
``screens``    screenshots (1280 px and 375 px wide) of a finished full-mesh run and the banner;
               no horizontal page scroll at 375 px
``results``    the four results pages (``ui/results/``: Overview, ``traffic-patterns/``,
               ``system-load/``, ``run-explorer/``): each has the sticky tabs (current one marked), a badge on every chart,
               the On this page / Next links and the Results menu; every section renders on its
               page with no console errors; runs.json is only fetched on use; heatmap click /
               keyboard -> scatter; the filter bar (topology chips + Task, System and Runs only)
               narrows the scatter, task chart and run table and its ``?topo=&task=`` query is
               carried across the tabs; scatter point -> the run on Runs; table row -> drill-down;
               old ``results/#run=`` and section links redirect to their new page; the demo run's
               Replay / View links work; screenshots and no horizontal scroll at 1280 and 375 px
``outliers``   Unusual runs on the Run explorer: chip counts match the flags in runs.json, a
               rule chip and the topology filter narrow the list, a run id opens the drill-down
               with its reasons, the table's Flagged only box; light / dark, 1280 and 375 px
               (``outliers-*.png``)
``workflow``   "Inside the workflow" (``workflow.json``): stages and roles on System load, the four
               exploratory sections (messages, context, retries, quality) on the Beta page with its
               banner; badged sections in On this page, every chart and table drawn from the data, the
               measure toggles redraw, the topology chips and Task filter narrow every chart,
               the matrix explains itself without Full mesh; light / dark, 1280 and 375 px
               (``workflow-*.png``)
``traffic``    Traffic patterns analyses (``traffic.json``): Arrivals / Models order with every section
               in On this page and badged, burst sizes / ON-OFF / gap charts and tables match the
               data, the robustness table (above its curves) shows the paper's published rate per cell, the playground
               redraws on topology / K / headroom / Resample with Poisson always beside the model;
               light / dark, 1280 and 375 px (``traffic-*.png``)
``theme``      light / dark theme on every page (launcher, runner, viewer, chat, the four results
               pages, docs): the toggle is Light / Dark only, light is the default and the OS
               setting is ignored, ``data-theme`` is set before ``<body>`` exists (no
               flash), each page renders in both themes with no console errors and no horizontal
               scroll at 375 px, the toggle's choice persists across reloads and pages, charts and
               the topology diagram recolour on toggle; light + dark screenshots (``theme-*.png``)
``docs``       the shared header and docs pages (``ui/docs/``): every page has the Results menu
               (the four results pages); on every page the Docs menu opens by
               click and keyboard (arrows, Home / End, Esc, Tab), lists Blog post then AgentVerse,
               closes on an outside click, stays inside the viewport and both entries load without
               console errors; the ACM DL, DOI and GitHub links are on every page; light and dark;
               no horizontal scroll at 375 px; the paper page's abstract matches the published version and
               its burst shares match ``summary.json``, it has no em/en dashes; Copy BibTeX copies the exact entry; the
               NAIC 2026 slides link appears only when the PDF exists; screenshots (``docs-*.png``)
``playground`` the Playground menu on every page, light and dark, 1280 and 375 px: Home · Playground ·
               Results · Docs · Paper · Code, its three entries (Run a workflow, Open a saved run, Chat
               with Agent A) with their hints and URLs (playground/run/, open/, chat/), the current tool marked, chat's hint
               saying it needs the local backend, keyboard use, inside the viewport, no old names
               (Run Viewer, Live Runner, ...); the new titles, headings and launcher cards; the chat
               page without a backend explains it and keeps Send off (``?demo=0``: as before);
               screenshots (``playground-*.png``)
``compare``    ``playground/compare/``: the three panels (Sequential, Star, Full mesh) replay one task on a
               shared clock, the shared arrivals timeline has one tick per LLM call and the table's call
               counts match the fixtures' events, the scrubber / Play / Restart / task select work, and the
               result is the same in public mode (also run under ``--data public``); light / dark,
               1280 and 375 px, no horizontal scroll (``compare-*.png``)
``analysis``   "Analyse this run" in the runner: a finished replay of each topology offers it collapsed;
               opening it draws the stat tiles, Gantt, in-flight, metrics and IAT charts (light / dark,
               no horizontal scroll); a cancelled run offers none (private and public)
``redirects``  every old URL (``agentverse/``, ``agentverse/index.html``, ``agentverse/viewer.html``,
               ``agentverse/viewer/``, ``chat/``, ``results/traffic/``, ``results/system/``,
               ``results/runs/``) forwards to its new page with the query and
               hash intact, the new page loads with no console errors, and Back skips the stub

``public``     (``--data public`` only) every page (launcher, runner, viewer, chat, the four results
               pages, docs) loads with no console errors; the data mode is public with no private
               data reachable and nothing under ``/data/private/`` is requested except the resolver's
               ``manifest.json`` probe; the results pages show the real aggregates (Overview numbers
               match the public ``summary.json``, Traffic / System load / workflow sections drawn);
               a missing ``runs.json`` and missing fixtures break nothing (notes instead of tables,
               no console errors); when the tree does have them, the Runs table and the demo
               banner appear

Exits 0 when every case passes, 1 otherwise, 2 on setup errors. Needs ``playwright`` with its
browsers installed (``playwright install firefox``), and nothing listening on :8101 (the Agent A
port), since the demo's backend detection and the ``?demo=0`` case rely on it being unreachable.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import re
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

REPO = Path(__file__).resolve().parents[2]
UI_DIR = REPO / "ui"
DATA_DIR = (
    UI_DIR / "data" / "private"
)  # the real data set: what the private-mode cases check against
FIXTURES = DATA_DIR / "fixtures"
PUBLIC_TREE = REPO / "dist" / "public"  # built by `make dist-public`: what --data public serves
# The paper and code links every page must carry (ui/common/js/site.js)
PAPER_URL = "https://dl.acm.org/doi/10.1145/3789240.3828749"
DOI_URL = "https://doi.org/10.1145/3789240.3828749"
REPO_URL = "https://github.com/dlamagna/agentraffic"
PAPER_TITLE = "Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology"
AGENT_A_PORT = 8101
# Files whose 404 is normal in some data set (see Watch._expected_failure).
OPTIONAL_DATA_FILES = (
    "/data/private/manifest.json",
    "/data/public/runs.json",
    "/data/public/fixtures/index.json",
)
FAST = 200  # ?speed= for runs whose timing doesn't matter
ROUND_EVENTS = {"discussion_round", "full_mesh_round", "vertical_iteration"}
BLOG_TITLE = "Same task, same model, different traffic"  # the docs/blog/ blog post

# Installed before any page script runs. Counts SSE chunks the mock enqueues (any JS-created
# ReadableStream), records how many stage-2 round blocks were on screen before the status said
# "Complete", and, once the app exists, counts handled SSE events and in-flight runs.
PROBE_JS = """
(() => {
  const probe = window.__probe = { enqueued: 0, liveRounds: 0, sse: 0, running: 0, runs: 0 };
  const C = window.ReadableStreamDefaultController;
  if (C) {
    const enqueue = C.prototype.enqueue;
    C.prototype.enqueue = function (chunk) { probe.enqueued++; return enqueue.call(this, chunk); };
  }
  document.addEventListener('DOMContentLoaded', () => {
    const s2 = document.getElementById('stage2Results');
    const status = document.getElementById('statusText');
    if (!s2 || !status) return;
    new MutationObserver(() => {
      const n = s2.querySelectorAll('.discussion-round').length;
      if (status.textContent !== 'Complete' && n > probe.liveRounds) probe.liveRounds = n;
    }).observe(s2, { childList: true });
  });
  window.addEventListener('load', () => {
    const h = window.agentverse && window.agentverse.streamingHandler;
    if (!h) return;
    const handle = h.handleStreamEvent.bind(h);
    h.handleStreamEvent = (event, data) => { probe.sse++; return handle(event, data); };
    const run = h.runWorkflowStreaming.bind(h);
    h.runWorkflowStreaming = async (...args) => {
      probe.running++;
      try { return await run(...args); } finally { probe.running--; probe.runs++; }
    };
  });
})();
"""

RESET_PROBE_JS = "() => Object.assign(window.__probe, { liveRounds: 0, sse: 0 })"

DONE_JS = """
id => document.getElementById('statusText').textContent === 'Complete'
  && document.getElementById('taskIdLabel').textContent.includes(id)
  && window.__probe.running === 0
"""

COMPARE_READY = "() => ['ready', 'empty'].includes(document.body.dataset.cmp)"
OVERFLOW_JS = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"


def normalise(text: str) -> str:
    """Same as normalise() in mock-backend.js."""
    return re.sub(r"\s+", " ", re.sub(r"^\|+", "", text or "")).strip()


# ---------------------------------------------------------------------------
# Static server
# ---------------------------------------------------------------------------


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep the test output readable
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def serve(directory: Path) -> _Server:
    handler = functools.partial(_Handler, directory=str(directory))
    httpd = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class Watch:
    """Console errors, uncaught page errors and requests seen by one page."""

    def __init__(self, page: Page):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.requests: list[tuple[str, str]] = []
        page.on("console", self._console)
        page.on("pageerror", lambda err: self.errors.append(f"pageerror: {err}"))
        page.on("request", lambda req: self.requests.append((req.method, req.url)))

    def _console(self, msg):
        if msg.type == "error" and self._expected_failure(msg):
            return
        if msg.type == "error":
            self.errors.append(f"console.error: {msg.text[:300]}")
        elif msg.type == "warning":
            self.warnings.append(msg.text[:200])

    def _expected_failure(self, msg) -> bool:
        """Chromium logs expected failed requests as errors: the demo's backend probe (GET :8101,
        no-cors), the paper page's check for slides PDFs that are not there yet (HEAD 404) and
        the optional data files (OPTIONAL_DATA_FILES)."""
        url = (msg.location or {}).get("url", "")
        if not msg.text.startswith("Failed to load resource"):
            return False
        if "/docs/slides/" in url:
            return True
        # data/private/manifest.json: the resolver's probe (common/js/data.js), a 404 wherever
        # there is no private data; runs.json / fixtures: optional in the public data set
        if "404" in msg.text and url.split("?")[0].endswith(OPTIONAL_DATA_FILES):
            return True
        return f":{AGENT_A_PORT}/agentverse" in url and ("GET", url) in self.requests

    def agent_a(self, method: str | None = None) -> list[tuple[str, str]]:
        return [
            (m, u)
            for m, u in self.requests
            if f":{AGENT_A_PORT}/agentverse" in u and (method is None or m == method)
        ]


class Case:
    """Soft assertions: a case keeps going after a failed check and reports all of them."""

    def __init__(self, name: str):
        self.name = name
        self.failures: list[str] = []
        self.notes: list[str] = []

    def check(self, cond: bool, msg: str) -> bool:
        if not cond:
            self.failures.append(msg)
        return bool(cond)

    def eq(self, got, want, what: str) -> bool:
        return self.check(got == want, f"{what}: got {short(got)!r}, want {short(want)!r}")

    def no_errors(self, watch: Watch, since: int, what: str):
        new = watch.errors[since:]
        self.check(not new, f"{what}: {len(new)} console/page error(s): {new[:3]}")


def short(value, n: int = 120):
    return value[:n] + "..." if isinstance(value, str) and len(value) > n else value


class Env:
    def __init__(self, browser: Browser, base: str, shots: Path, tree: Path = UI_DIR):
        self.browser = browser
        self.base = base
        self.shots = shots
        self.tree = tree  # the directory being served
        index = FIXTURES / "index.json"
        # a public tree may have no fixtures (until the synthetic ones exist): only `public` runs
        self.index = json.loads(index.read_text()) if index.is_file() else {"fixtures": []}
        self._contexts: list[BrowserContext] = []
        self._cache: dict[str, object] = {}

    def entry(self, topology: str, task: str) -> dict:
        return next(
            e for e in self.index["fixtures"] if e["topology"] == topology and e["task"] == task
        )

    def fixture(self, rel: str):
        if rel not in self._cache:
            self._cache[rel] = json.loads((FIXTURES / rel).read_text())
        return self._cache[rel]

    def response(self, entry: dict) -> dict:
        return self.fixture(entry["files"]["response"])

    def events(self, entry: dict) -> list[dict]:
        return self.fixture(entry["files"]["events"])

    def open(
        self,
        path: str,
        width: int = 1280,
        height: int = 900,
        color_scheme: str | None = None,
        init: tuple[str, ...] = (),
        store_theme: bool = True,
    ) -> tuple[Page, Watch]:
        """color_scheme sets the browser's prefers-color-scheme and, unless store_theme is False,
        also stores it as the theme choice when nothing is stored yet: the UI ignores the OS
        setting, so this is how a case renders a page in that theme."""
        opts = {"color_scheme": color_scheme} if color_scheme else {}
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, **opts)
        ctx.set_default_timeout(15_000)
        ctx.add_init_script(script=PROBE_JS)
        if color_scheme and store_theme:
            ctx.add_init_script(
                script="try { if (localStorage.getItem('agentraffic-theme') === null) "
                f"localStorage.setItem('agentraffic-theme', '{color_scheme}'); }} catch (e) {{}}"
            )
        for script in init:
            ctx.add_init_script(script=script)
        self._contexts.append(ctx)
        page = ctx.new_page()
        watch = Watch(page)
        page.goto(self.base + path)
        return page, watch

    def close(self):
        for ctx in self._contexts:
            ctx.close()
        self._contexts.clear()


def text(page: Page, selector: str) -> str:
    return page.locator(selector).first.text_content() or ""


def probe(page: Page) -> dict:
    return page.evaluate("() => ({ ...window.__probe })")


def start_run(page: Page, topology: str, task: str | None = None):
    """Pick a task (example key, or leave the textarea alone), a topology, and click Run."""
    if task is not None:
        page.evaluate("k => window.agentverse.loadExample(k)", task)
    page.select_option("#topology", topology)
    page.evaluate(RESET_PROBE_JS)
    page.click("#runBtn")


def wait_done(page: Page, entry: dict, timeout: float = 15_000):
    page.wait_for_function(DONE_JS, arg=entry["task_id"], timeout=timeout)


def expected_round_responses(structure: str, rounds: list[dict]) -> int:
    if structure == "full_mesh":
        return sum(len(r.get("messages") or []) for r in rounds)
    if structure == "horizontal":
        return sum(len(r.get("responses") or []) for r in rounds)
    return sum(1 + len(r.get("reviewer_responses") or []) for r in rounds)


def check_rendered(t: Case, page: Page, env: Env, entry: dict, what: str):
    """The finished UI matches the recorded response (app and viewer share these elements)."""
    resp = env.response(entry)
    n = entry["n_llm_calls"]
    t.eq(len(resp["llm_requests"]), n, f"{what}: fixture llm_requests vs index n_llm_calls")
    t.eq(text(page, "#llmRequestCount"), f"{n} LLM requests", f"{what}: LLM request count")
    t.check(page.is_visible("#finalOutputContainer"), f"{what}: final output not shown")
    t.eq(text(page, "#finalOutput"), resp["final_output"], f"{what}: final output text")
    t.check(entry["task_id"] in text(page, "#taskIdLabel"), f"{what}: task id label")
    for i in range(1, 5):
        cls = page.get_attribute(f"#stage{i}", "class") or ""
        t.check("completed" in cls.split(), f"{what}: stage {i} not completed ({cls!r})")

    decision = resp["stages"]["decision"]
    structure, rounds = decision["structure_used"], decision["discussion_rounds"]
    s2 = text(page, "#stage2Results")
    t.eq(
        page.locator("#stage2Results .discussion-round").count(),
        len(rounds),
        f"{what}: stage 2 round blocks",
    )
    t.eq(
        page.locator("#stage2Results .round-response").count(),
        expected_round_responses(structure, rounds),
        f"{what}: stage 2 messages",
    )
    for bad in ("No reviews", "No discussion recorded", "No messages", "undefined"):
        t.check(bad not in s2, f"{what}: stage 2 shows {bad!r}")
    if structure == "full_mesh":
        t.check(s2.count("→") >= len(rounds), f"{what}: no sender → receiver messages in stage 2")


CASES: list[tuple[str, Callable[[Env, Case], None]]] = []
CASE_MODES: dict[str, tuple[str, ...]] = {}  # case -> the --data modes it runs in


def case(name: str, modes: tuple[str, ...] = ("private",)):
    def register(fn):
        CASES.append((name, fn))
        CASE_MODES[name] = modes
        return fn

    return register


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


@case("fixtures")
def case_fixtures(env: Env, t: Case):
    page, watch = env.open(f"playground/run/index.html?demo=1&speed={FAST}")
    page.wait_for_selector("#demoBanner")
    for entry in env.index["fixtures"]:
        what = f"{entry['topology']}/{entry['task']}"
        events = env.events(entry)
        since = len(watch.errors)
        t0 = time.monotonic()
        start_run(page, entry["topology"], entry["task"])
        try:
            wait_done(page, entry, timeout=20_000)
        except Exception:
            t.check(False, f"{what}: did not complete (status {text(page, '#statusText')!r})")
            continue
        elapsed = time.monotonic() - t0
        state = probe(page)
        t.eq(text(page, "#statusText"), "Complete", f"{what}: status")
        t.eq(state["sse"], len(events), f"{what}: SSE events handled")
        live = sum(e["event"] in ROUND_EVENTS for e in events)
        t.eq(state["liveRounds"], live, f"{what}: round blocks shown live, before Complete")
        t.check(not page.is_disabled("#runBtn"), f"{what}: Run still disabled")
        check_rendered(t, page, env, entry, what)
        t.no_errors(watch, since, what)
        t.eq(watch.agent_a(), [], f"{what}: requests that reached the real endpoint")
        t.notes.append(f"{what}: ok in {elapsed:.1f}s ({len(events)} events, {live} live rounds)")
    for warning in sorted(set(watch.warnings)):
        t.notes.append(f"console.warn: {warning}")


@case("cancel")
def case_cancel(env: Env, t: Case):
    page, watch = env.open("playground/run/index.html?demo=1&speed=5")
    page.wait_for_selector("#demoBanner")
    entry = env.entry("full_mesh", "math")
    start_run(page, "full_mesh", "math")
    page.wait_for_function("() => window.__probe.sse >= 8", timeout=10_000)
    t.check(page.is_visible("#cancelBtn"), "Cancel button not shown while running")
    page.click("#cancelBtn")
    page.wait_for_function("() => window.__probe.running === 0", timeout=5_000)
    t.eq(text(page, "#statusText"), "Cancelled", "status after cancel")
    t.check(not page.is_disabled("#runBtn"), "Run not re-enabled after cancel")
    t.check(not page.is_visible("#cancelBtn"), "Cancel button still shown after cancel")
    t.check(not page.is_visible("#liveBadge"), "Live badge still shown after cancel")
    panel = page.get_attribute(".workflow-panel", "class") or ""
    t.check("workflow-panel--cancelled" in panel, "workflow panel not marked cancelled")
    t.check("error" not in (page.get_attribute("#stage2", "class") or ""), "stages marked as error")
    before = probe(page)
    page.wait_for_timeout(2_000)  # 10 s of recorded time at 5x
    after = probe(page)
    t.eq(after["enqueued"], before["enqueued"], "SSE chunks enqueued after cancel")
    t.eq(after["sse"], before["sse"], "SSE events handled after cancel")
    t.check(before["sse"] < len(env.events(entry)), "run finished before it could be cancelled")
    t.check(not page.is_visible("#finalOutputContainer"), "final output shown after cancel")
    t.no_errors(watch, 0, "cancel")

    since = len(watch.errors)
    page.select_option("#demoSpeed", "20")
    entry = env.entry("full_mesh", "coding")
    start_run(page, "full_mesh", "coding")
    wait_done(page, entry)
    check_rendered(t, page, env, entry, "run after cancel")
    panel = page.get_attribute(".workflow-panel", "class") or ""
    t.check("workflow-panel--cancelled" not in panel, "cancelled styling kept on the new run")
    t.no_errors(watch, since, "run after cancel")


@case("speed")
def case_speed(env: Env, t: Case):
    page, watch = env.open("playground/run/index.html?demo=1&speed=1")
    page.wait_for_selector("#demoBanner")
    t.eq(page.input_value("#demoSpeed"), "1", "speed selector from ?speed=1")
    entry = env.entry("full_mesh", "coding")
    events = env.events(entry)
    total_s = events[-1]["t_ms"] / 1000
    start_run(page, "full_mesh", "coding")
    t0 = time.monotonic()
    page.wait_for_timeout(1_500)
    state = probe(page)
    t.check(text(page, "#statusText") != "Complete", "finished within 1.5 s at 1x")
    due = sum(e["t_ms"] <= 3_000 for e in events)
    t.check(state["sse"] <= due, f"1x replay too fast: {state['sse']} events after 1.5 s")
    page.select_option("#demoSpeed", "20")
    t1 = time.monotonic()
    wait_done(page, entry, timeout=20_000)
    after_switch = time.monotonic() - t1
    expected = (total_s - (t1 - t0)) / 20
    t.check(
        0.4 * expected <= after_switch <= expected + 4,
        f"after switching to 20x the run took {after_switch:.1f}s (expected ~{expected:.1f}s)",
    )
    # the status-bar timer shows the recorded run time, not the (much shorter) wall time
    timer_s = float(text(page, "#statusTime").rstrip("s"))
    t.check(
        abs(timer_s - total_s) <= 0.5,
        f"timer shows {timer_s:.1f}s at the end; recorded run is {total_s:.1f}s",
    )
    check_rendered(t, page, env, entry, "speed")
    t.no_errors(watch, 0, "speed")
    t.notes.append(
        f"recorded {total_s:.0f}s; finished {after_switch:.1f}s after switching 1x -> 20x "
        f"(expected ~{expected:.1f}s)"
    )


@case("demo-flag")
def case_demo_flag(env: Env, t: Case):
    # ?demo=0: the real endpoint is used, and fails since nothing listens on :8101.
    page, watch = env.open("playground/run/index.html?demo=0")
    page.wait_for_timeout(500)
    t.eq(page.locator("#demoBanner").count(), 0, "?demo=0: banner count")
    page.click("button[onclick*=\"loadExample('research')\"]")
    research = env.entry("vertical", "research")["original_task"]
    t.check(page.input_value("#task") != research, "?demo=0: example replaced by recorded text")
    start_run(page, "full_mesh", "math")
    page.wait_for_function("() => window.__probe.running === 0", timeout=10_000)
    t.eq(text(page, "#statusText"), "Error", "?demo=0: status without backend")
    t.check(bool(watch.agent_a()), f"?demo=0: no request reached :{AGENT_A_PORT}/agentverse")
    t.eq(probe(page)["enqueued"], 0, "?demo=0: SSE chunks from the mock")
    t.notes.append(f"?demo=0 requests to Agent A: {sorted(set(watch.agent_a()))}")

    # No flag, no backend: the probe fails and demo mode switches itself on.
    page, watch = env.open("playground/run/index.html")
    page.wait_for_selector("#demoBanner", timeout=8_000)
    t.check(bool(watch.agent_a("GET")), "auto: backend probe not seen")
    page.select_option("#demoSpeed", "20")
    entry = env.entry("full_mesh", "coding")
    start_run(page, "full_mesh", "coding")
    wait_done(page, entry)
    check_rendered(t, page, env, entry, "auto")
    t.eq(watch.agent_a("POST"), [], "auto: POSTs that reached the real endpoint")
    t.check(probe(page)["enqueued"] > 0, "auto: run was not replayed by the mock")
    t.no_errors(watch, 0, "auto")


@case("custom")
def case_custom(env: Env, t: Case):
    page, watch = env.open(f"playground/run/index.html?demo=1&speed={FAST}")
    page.wait_for_selector("#demoBanner")
    custom = "Plan a three-day trip to Lisbon for two people on a 600 EUR budget."
    for topology, expect_topology in (("", "vertical"), ("horizontal", "horizontal")):
        what = f"custom/{topology or 'auto'}"
        entry = env.entry(expect_topology, "math")
        page.fill("#task", custom)
        start_run(page, topology)
        wait_done(page, entry)
        provenance = text(page, "#demoProvenance")
        t.check("Custom tasks can't run in the demo" in provenance, f"{what}: no custom note")
        t.check(entry["task_id"][:8] in provenance, f"{what}: provenance {provenance!r}")
        check_rendered(t, page, env, entry, what)
    start_run(page, "horizontal", "research")
    wait_done(page, env.entry("horizontal", "research"))
    t.check("Custom" not in text(page, "#demoProvenance"), "custom note kept for a recorded task")
    t.no_errors(watch, 0, "custom")


@case("examples")
def case_examples(env: Env, t: Case):
    page, watch = env.open("playground/run/index.html?demo=1")
    page.wait_for_selector("#demoBanner")
    for key in ("math", "research", "consulting", "coding"):
        recorded = {e["original_task"] for e in env.index["fixtures"] if e["task"] == key}
        t.eq(len(recorded), 1, f"{key}: distinct recorded texts across topologies")
        page.click(f"button[onclick*=\"loadExample('{key}')\"]")
        t.eq(page.input_value("#task"), next(iter(recorded)), f"{key}: example button text")
    t.no_errors(watch, 0, "examples")


EDGE_SAMPLER_JS = """() => {
  clearInterval(window.__edgeTimer);
  window.__edgeStats = { max: 0, edges: [] };
  window.__edgeTimer = setInterval(() => {
    const lit = [...document.querySelectorAll('.topo-edge.topo-active')].map((e) => e.dataset.edge);
    const st = window.__edgeStats;
    st.max = Math.max(st.max, lit.length);
    lit.forEach((e) => st.edges.includes(e) || st.edges.push(e));
  }, 20);
}"""


@case("edges")
def case_edges(env: Env, t: Case):
    """The topology diagram bolds each LLM call's edge: one at a time for Sequential,
    fan-out bursts for Star and Full Mesh."""
    want = {  # topology -> (check on max simultaneous lit edges, edges expected over the run)
        "horizontal": (lambda n: n == 1, {"0-1", "1-2", "2-3"}),
        "vertical": (lambda n: n >= 2, {"0-1", "0-2", "0-3"}),
        "full_mesh": (lambda n: n >= 3, {"0-1", "0-2", "0-3", "1-2", "1-3", "2-3"}),
    }
    for speed in (5, 20):
        page, watch = env.open(f"playground/run/index.html?demo=1&speed={speed}")
        page.wait_for_selector("#demoBanner")
        for topology, (max_ok, edges) in want.items():
            entry = env.entry(topology, "math")
            page.evaluate(EDGE_SAMPLER_JS)
            start_run(page, topology, "math")
            wait_done(page, entry, timeout=60_000)
            st = page.evaluate("() => window.__edgeStats")
            what = f"{topology} @{speed}x"
            t.check(max_ok(st["max"]), f"{what}: max simultaneous lit edges {st['max']}")
            t.eq(set(st["edges"]), edges, f"{what}: edges lit")
        t.no_errors(watch, 0, f"edges @{speed}x")


@case("viewer")
def case_viewer(env: Env, t: Case):
    loaded = "() => document.getElementById('statusText').textContent === 'Loaded'"
    for entry in env.index["fixtures"]:
        what = f"viewer?task_id {entry['topology']}/{entry['task']}"
        page, watch = env.open(f"playground/open/?task_id={entry['task_id']}&demo=1")
        page.wait_for_function(loaded)
        check_rendered(t, page, env, entry, what)
        t.eq(
            text(page, "#taskDisplay"),
            normalise(env.response(entry)["original_task"]),
            f"{what}: task",
        )
        t.check(page.locator("#demoBanner").count() == 1, f"{what}: no banner")
        t.no_errors(watch, 0, what)
        env.close()

    for topology in ("horizontal", "vertical", "full_mesh"):
        entry = env.entry(topology, "math")
        what = f"viewer?json {topology}/math"
        page, watch = env.open(
            f"playground/open/?json=../../data/private/fixtures/{entry['files']['response']}"
        )
        page.wait_for_function(loaded)
        check_rendered(t, page, env, entry, what)
        if text(page, "#taskDisplay").startswith("|"):
            t.notes.append(f"{what}: task shows the recorded '||' prefix (not normalised)")
        t.no_errors(watch, 0, what)

    entry = env.entry("full_mesh", "research")
    page, watch = env.open(f"agentverse/viewer/?task_id={entry['task_id']}&demo=1")
    page.wait_for_function(loaded)
    t.check(page.url.split("?")[0].endswith("/playground/open/"), f"viewer/ redirect: {page.url}")
    check_rendered(t, page, env, entry, "viewer/ redirect")
    t.no_errors(watch, 0, "viewer/ redirect")

    # The live runner's ?task_id= deep link (loadFromTaskId -> GET /agentverse/<id>).
    entry = env.entry("full_mesh", "consulting")
    page, watch = env.open(f"playground/run/index.html?task_id={entry['task_id']}&demo=1")
    page.wait_for_function(
        "() => document.getElementById('statusText').textContent === 'Loaded from task ID'"
    )
    check_rendered(t, page, env, entry, "app?task_id")
    t.eq(page.input_value("#task"), entry["original_task"], "app?task_id: task textarea")
    t.check(not page.is_disabled("#runBtn"), "app?task_id: Run disabled")
    t.no_errors(watch, 0, "app?task_id")

    # The banner's provenance link opens the recorded response in the viewer.
    href = page.get_attribute("#demoProvenance a", "href") or ""
    t.check(
        f"/playground/open/?demo=1&task_id={entry['task_id']}" in href, f"banner link: {href!r}"
    )
    page.goto(href)
    page.wait_for_function(loaded)
    check_rendered(t, page, env, entry, "banner link")
    t.no_errors(watch, 0, "banner link")


@case("screens")
def case_screens(env: Env, t: Case):
    env.shots.mkdir(parents=True, exist_ok=True)
    entry = env.entry("full_mesh", "math")
    for label, width, height in (("desktop", 1280, 900), ("mobile", 375, 812)):
        page, watch = env.open(f"playground/run/index.html?demo=1&speed={FAST}", width, height)
        page.wait_for_selector("#demoBanner")
        start_run(page, "full_mesh", "math")
        wait_done(page, entry)
        check_rendered(t, page, env, entry, label)
        page.wait_for_timeout(800)  # let the smooth scroll to the raw JSON settle
        page.evaluate("() => document.getElementById('stage2').scrollIntoView({ block: 'start' })")
        page.wait_for_timeout(200)
        shots = {
            f"demo-full-mesh-{label}.png": lambda p: page.screenshot(path=p),
            f"demo-full-mesh-{label}-full.png": lambda p: page.screenshot(path=p, full_page=True),
            f"demo-banner-{label}.png": lambda p: page.locator("#demoBanner").screenshot(path=p),
        }
        for name, take in shots.items():
            take(str(env.shots / name))
            t.notes.append(str(env.shots / name))
        t.eq(page.evaluate(OVERFLOW_JS), 0, f"{label}: horizontal page scroll (px)")
        t.no_errors(watch, 0, label)

    page, watch = env.open(f"playground/open/?task_id={entry['task_id']}&demo=1", 375, 812)
    page.wait_for_function("() => document.getElementById('statusText').textContent === 'Loaded'")
    t.eq(page.evaluate(OVERFLOW_JS), 0, "viewer at 375px: horizontal page scroll (px)")
    t.no_errors(watch, 0, "viewer at 375px")


RESULTS_PAGES = {  # results page id -> path (tabs in this order)
    "overview": "results/",
    "traffic": "results/traffic-patterns/",
    "system": "results/system-load/",
    "runs": "results/run-explorer/",
}
RESULTS_TABS = ["Overview", "Traffic patterns", "System load", "Run explorer"]
RESULTS_SECTIONS = {  # section -> (page, selector that only exists once it has rendered)
    "architecture": ("overview", "#topoCards .topo-card"),
    "iat glance": ("overview", "#iatThumbs a.thumb svg path"),
    "table2": ("overview", "#table2Body table tbody tr"),
    "iat": ("traffic", "#iatCharts svg polyline.fit"),
    "iat fits": ("traffic", "#iatTable table tbody tr"),
    "scaling": ("traffic", "#scalingCharts svg path"),
    "network": ("system", "#netChart svg path"),
    "correlations": ("system", "#corrHeatmap svg rect.cell"),
    "tasks": ("system", "#taskChart svg circle"),
    "runs": ("runs", "#runTable table tbody tr[data-run]"),
    "outliers": ("runs", "#outlierBody table tbody tr[data-run]"),
}
RESULTS_ASYNC = ("runs", "outliers")  # sections drawn after runs.json loads
# Overview story order: Motivation, Set-up, Arrivals, Testbed, Table 2, Takeaways, Cite.
OVERVIEW_ORDER = [
    "#motivation",
    "#setup",
    "#iatGlance",
    "#architecture",
    "#table2",
    "#takeaways",
    "#cite",
]
OVERVIEW_FILL_JS = """() => Object.fromEntries([...document.querySelectorAll('[data-fill]')]
  .map((e) => [e.dataset.fill, e.textContent]))"""
OVERVIEW_TEXT_JS = """() => ['.findings', '#motivation', '#setup', '#takeaways']
  .map((s) => document.querySelector(s)?.innerText || '').join('\\n')"""


def overview_fills(summary: dict) -> dict[str, str]:
    """The numbers the Overview text must show, from summary.json."""
    iat, fits = summary["iat"]["per_topology"], summary["iat"]["fits"]
    agg = summary["aggregates"]["by_topology"]
    rate_row = next(
        r
        for sec in summary["table2"]["sections"]
        for r in sec["rows"]
        if r["metric"] == "Discussion call rate"
    )
    want = {"n-runs": f"{summary['source']['n_runs_total']:,}"}
    for t in ("horizontal", "vertical", "full_mesh"):
        want[f"burst-{t}"] = f"{iat[t]['burst_fraction'] * 100:.1f}%"
        want[f"ks-{t}"] = f"{fits[t]['lognormal']['ks']:.3f}"
        if t != "full_mesh":  # finding 3 compares Star with Sequential
            want[f"rate-{t}"] = rate_row["values"][t].split()[0]
    inf = {t: agg[t]["llm_inflight_mean"]["mean"] for t in agg}
    want["inflight-star"] = f"{round((inf['vertical'] / inf['horizontal'] - 1) * 100)}%"
    want["inflight"] = f"{inf['horizontal']:.2f} → {inf['full_mesh']:.2f}"
    return want


def corr_metric_count(summary: dict) -> int:
    """Metrics in the correlation matrix: duplicate and constant ones are left out."""
    constant = {"tcp_rtt_p50_mean_s", "tcp_rtt_p95_mean_s"}  # util.js DEGENERATE_FALLBACK
    left_out = {
        m["key"]
        for m in summary["metrics"]
        if m.get("duplicate_of") or m.get("degenerate", m["key"] in constant)
    }
    return len([k for k in summary["correlations"]["metric_keys"] if k not in left_out])


# Old single-page links on results/ -> where they must land now.
RESULTS_REDIRECTS = {
    "#iat": "results/traffic-patterns/#iat",
    "#scaling": "results/traffic-patterns/#scaling",
    "#correlations": "results/system-load/#correlations",
    "#tasks": "results/system-load/#tasks",
    "#network": "results/system-load/#network",
    "#runs": "results/run-explorer/#runs",
}
BADGE_LABELS = {"Real aggregate", "Recorded runs"}
RESULTS_READY = "() => document.body.dataset.ready === 'true'"
DETAIL_JS = (
    "() => !!document.querySelector('#runDetail:not([hidden]) [data-chart=\"gantt\"] svg rect')"
)
SHELL_JS = """() => ({
  tabs: [...document.querySelectorAll('.results-tabs a')].map((a) => a.textContent),
  current: [...document.querySelectorAll('.results-tabs a[aria-current="page"]')].map((a) => a.textContent),
  tabHrefs: [...document.querySelectorAll('.results-tabs a')].map((a) => a.href),
  sticky: getComputedStyle(document.querySelector('.results-tabs')).position,
  declared: document.querySelectorAll('[data-badge]').length,
  badged: [...document.querySelectorAll('[data-badge]')].filter((e) => e.querySelector('.badge')).length,
  badges: [...document.querySelectorAll('.badge')].map((b) => b.textContent),
  filterBar: !!document.querySelector('.filter-bar .chip'),
  toc: [...document.querySelectorAll('.page-toc a')].map((a) => a.getAttribute('href')),
  sections: [...document.querySelectorAll('main section[data-toc]')].map((s) => '#' + s.id),
  next: document.querySelector('.next-link')?.href,
  question: !!document.querySelector('.hero .page-question')?.textContent.trim(),
})"""
FILTER_JS = """() => ({
  search: location.search,
  pressed: [...document.querySelectorAll('.filter-bar .chip')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.topo),
  task: document.getElementById('filterTask')?.value ?? null,
  tabs: [...document.querySelectorAll('.results-tabs a')].map((a) => new URL(a.href).search),
})"""


def results_summary() -> dict:
    return json.loads((DATA_DIR / "summary.json").read_text())


def results_runs() -> list[dict]:
    return json.loads((DATA_DIR / "runs.json").read_text())["runs"]


def check_results_shell(t: Case, page: Page, watch: Watch, name: str):
    """Tabs, badges, filter bar (System / Runs only), On this page + Next, Results ▾ menu."""
    ids = list(RESULTS_PAGES)
    sh = page.evaluate(SHELL_JS)
    t.eq(sh["tabs"], RESULTS_TABS, f"{name}: tabs")
    t.eq(sh["current"], [RESULTS_TABS[ids.index(name)]], f"{name}: current tab (aria-current)")
    t.eq(sh["sticky"], "sticky", f"{name}: tabs position")
    for href, pid in zip(sh["tabHrefs"], ids):
        t.check(
            href.split("?")[0].endswith("/" + RESULTS_PAGES[pid]), f"{name}: tab {pid} -> {href}"
        )
    t.check(sh["declared"] > 0, f"{name}: no chart declares a badge")
    t.eq(sh["badged"], sh["declared"], f"{name}: charts with their badge drawn")
    t.check(set(sh["badges"]) <= BADGE_LABELS, f"{name}: badge labels {sorted(set(sh['badges']))}")
    t.eq(sh["filterBar"], name in ("system", "runs"), f"{name}: filter bar shown")
    t.check(sh["question"], f"{name}: no question under the page title")
    want_toc = sh["sections"] if len(sh["sections"]) >= 2 else []  # no list for a one-section page
    t.eq(sh["toc"], want_toc, f"{name}: On this page links")
    nxt = ids[(ids.index(name) + 1) % len(ids)]
    t.check(
        (sh["next"] or "").split("?")[0].endswith("/" + RESULTS_PAGES[nxt]),
        f"{name}: Next -> {sh['next']} (want {nxt})",
    )
    # Results ▾ in the site header lists the four pages plus Beta, this one current.
    page.click(".results-menu__button")
    items = page.eval_on_selector_all(
        ".results-menu__item",
        "els => els.map((a) => [a.querySelector('.results-menu__label').textContent, a.href, a.getAttribute('aria-current')])",
    )
    # the four core pages, then the visibly secondary Beta entry (not a tab)
    t.eq([i[0] for i in items], RESULTS_TABS + ["Beta"], f"{name}: Results menu entries")
    t.check(items[-1][1].split("?")[0].endswith("/results/beta/"), f"{name}: Beta menu link")
    t.eq(
        page.locator(".results-menu__item.site-menu__item--secondary").count(),
        1,
        f"{name}: Beta entry secondary",
    )
    t.check(
        all(i[1].split("?")[0].endswith("/" + RESULTS_PAGES[pid]) for i, pid in zip(items, ids)),
        f"{name}: Results menu links {[i[1] for i in items]}",
    )
    t.eq(
        [i[0] for i in items if i[2] == "page"],
        [RESULTS_TABS[ids.index(name)]],
        f"{name}: Results menu current entry",
    )
    page.keyboard.press("Escape")
    t.eq(
        page.get_attribute(".results-menu__button", "aria-expanded"),
        "false",
        f"{name}: Esc closes the Results menu",
    )


@case("results")
def case_results(env: Env, t: Case):
    """The four results pages: shared tabs / badges / filter bar / Results menu, every section
    renders, heatmap -> scatter -> run drill-down on Runs, the filter carried across tabs, the
    old single-page links redirect, #run= deep link, the fixture replay/view links, no
    sideways scroll."""
    summary = results_summary()
    fixture = next(
        f for f in summary["fixtures"] if f["topology"] == "full_mesh" and f["task"] == "math"
    )
    runs = results_runs()
    env.shots.mkdir(parents=True, exist_ok=True)

    # 1. Every page: shared chrome, its sections, runs.json only on the Runs page.
    for name, path in RESULTS_PAGES.items():
        page, watch = env.open(path)
        page.wait_for_function(RESULTS_READY)
        for section, (where, selector) in RESULTS_SECTIONS.items():
            n = page.locator(selector).count()
            if where == name:
                if section in RESULTS_ASYNC:
                    page.wait_for_selector(selector)
                    n = page.locator(selector).count()
                t.check(n > 0, f"{name}: section {section} rendered nothing ({selector})")
            else:
                t.eq(n, 0, f"{name}: section {section} should be on {where}")
        if name != "runs":
            t.check(
                not any("runs.json" in u for _, u in watch.requests),
                f"{name}: runs.json fetched on page open (should be lazy)",
            )
        check_results_shell(t, page, watch, name)
        t.no_errors(watch, 0, f"{name} page")
        env.close()

    # 2. Overview: paper links, IAT thumbnails link to Traffic.
    page, watch = env.open("results/")
    page.wait_for_function(RESULTS_READY)
    t.check(page.locator("#paperLink").is_visible(), "Read the paper link hidden")
    t.eq(page.get_attribute("#paperLink", "href"), PAPER_URL, "Read the paper link")
    t.eq(page.get_attribute("#codeLink", "href"), REPO_URL, "View the code link")
    # The story: section order, headline numbers from summary.json, the blog link,
    # British punctuation (no em / en dashes in the prose).
    t.eq(
        page.eval_on_selector_all("main section[data-toc]", "els => els.map((e) => '#' + e.id)"),
        OVERVIEW_ORDER,
        "Overview: section order",
    )
    fills = page.evaluate(OVERVIEW_FILL_JS)
    for key, value in overview_fills(summary).items():
        t.eq(fills.get(key), value, f"Overview: {key}")
    t.check(
        "Poisson is rejected" in text(page, ".findings")
        and "Same rate, different load" in text(page, ".findings"),
        "Overview: headline wording",
    )
    t.check(
        page.locator("#motivation a[href='../docs/blog/']").count() == 1,
        "Overview: motivation links the blog post",
    )
    t.check("only the topology changes" in text(page, "#setup"), "Overview: set-up claim missing")
    prose = page.evaluate(OVERVIEW_TEXT_JS)
    t.check("\u2014" not in prose and "\u2013" not in prose, "Overview: em/en dash in the prose")
    for word in ("Limitations", "Future work"):
        t.check(word in text(page, "#takeaways"), f"Overview: takeaways lack {word}")
    t.eq(page.locator("#iatThumbs a.thumb").count(), 3, "IAT thumbnails")
    page.locator("#iatThumbs a.thumb").first.click()
    page.wait_for_url(lambda u: u.endswith("/results/traffic-patterns/#iat"))
    page.wait_for_function(RESULTS_READY)
    t.no_errors(watch, 0, "overview -> traffic")
    env.close()

    # 3. Traffic: x-axis scale toggle redraws all panels and clips the burst spike with a label.
    page, watch = env.open("results/traffic-patterns/")
    page.wait_for_function(RESULTS_READY)
    t.eq(page.locator("#iatCharts figure").count(), 3, "IAT panels")
    page.click('#iatScale [data-scale="linear"]')
    page.wait_for_timeout(300)
    titles = page.eval_on_selector_all(
        "#iatCharts svg text", "els => els.map((e) => e.textContent)"
    )
    t.eq(sum("(linear scale)" in x for x in titles), 3, "IAT linear: axis titles")
    t.eq(
        sum("in the first" in x for x in titles),
        2,
        "IAT linear: clipped burst labels (Star, Full mesh)",
    )
    page.click('#iatScale [data-scale="log"]')
    page.wait_for_timeout(300)
    titles = page.eval_on_selector_all(
        "#iatCharts svg text", "els => els.map((e) => e.textContent)"
    )
    t.eq(sum("(log scale)" in x for x in titles), 3, "IAT log: axis titles")
    t.eq(page.locator("#scalingCharts figure").count(), 3, "scaling panels")
    t.no_errors(watch, 0, "traffic page")
    env.close()

    # 4. System: heatmap click / keyboard -> scatter; the filter narrows it; dot -> Runs page.
    page, watch = env.open("results/system-load/")
    page.wait_for_function(RESULTS_READY)
    n_metrics = corr_metric_count(summary)
    t.eq(page.locator("#corrHeatmap svg rect.cell").count(), n_metrics**2, "heatmap cells")
    t.eq(
        page.locator("#corrHeatmap svg rect.cell-paper").count(),
        2 * len(summary["correlations"]["selected"]),
        "paper rings",
    )
    page.locator("#correlations").scroll_into_view_if_needed()
    heat = page.locator("#corrHeatmap svg")
    hit = page.locator("#corrHeatmap svg rect.hit").bounding_box()
    cell = hit["width"] / n_metrics
    before = (page.input_value("#corrX"), page.input_value("#corrY"))
    page.mouse.click(hit["x"] + 2.5 * cell, hit["y"] + 0.5 * cell)  # row 0, column 2
    page.wait_for_selector("#corrScatter svg circle", state="attached", timeout=20_000)
    after = (page.input_value("#corrX"), page.input_value("#corrY"))
    t.check(after != before, f"heatmap click did not change the pair ({before} -> {after})")
    dots = page.locator("#corrScatter svg circle").count()
    t.check(dots > 1_000, f"scatter shows {dots} dots")
    t.check("All:" in text(page, "#corrRhos"), "scatter rho list missing")
    t.check(
        any("runs.json" in u for _, u in watch.requests), "runs.json not fetched for the scatter"
    )
    heat.focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    keyed = (page.input_value("#corrX"), page.input_value("#corrY"))
    t.check(keyed != after, f"keyboard Enter on the heatmap did not change the pair ({keyed})")
    dots = page.locator("#corrScatter svg circle").count()
    tasks_before = page.locator("#taskChart svg circle").count()

    # Filter bar: Task + topology chips, written to the URL and applied to scatter + task chart.
    page.select_option("#filterTask", "coding")
    page.wait_for_timeout(300)
    coded = page.locator("#corrScatter svg circle").count()
    t.check(0 < coded < dots, f"task filter: {coded} dots of {dots}")
    page.click('.filter-bar .chip[data-topo="full_mesh"]')
    page.wait_for_timeout(300)
    f = page.evaluate(FILTER_JS)
    t.eq(f["search"], "?topo=horizontal,vertical&task=coding", "filter query in the URL")
    t.eq(f["pressed"], ["horizontal", "vertical"], "chips pressed")
    t.check(all(s == f["search"] for s in f["tabs"]), f"tabs carry the filter query {f['tabs']}")
    t.check(
        page.locator("#corrScatter svg circle").count() < coded, "topology chip did not cut dots"
    )
    t.check(
        page.locator("#taskChart svg circle").count() < tasks_before,
        "filter did not narrow the task breakdown",
    )
    t.check(
        "full_mesh"
        not in (page.get_attribute(".results-menu__item[data-page='runs']", "href") or "")
        and "task=coding"
        in (page.get_attribute(".results-menu__item[data-page='runs']", "href") or ""),
        "Results menu links do not carry the filter",
    )
    # Across the tabs: Runs (applied to the table), Traffic (no bar, query kept), Overview, System.
    want = sum(
        1 for r in runs if r["topology"] in ("horizontal", "vertical") and r["task"] == "coding"
    )
    page.click(".results-tabs a[data-tab='runs']")
    page.wait_for_url(
        lambda u: u.endswith("/results/run-explorer/?topo=horizontal,vertical&task=coding")
    )
    page.wait_for_function(RESULTS_READY)
    page.wait_for_selector("#runTable table tbody tr[data-run]")
    f = page.evaluate(FILTER_JS)
    t.eq(
        (f["pressed"], f["task"]), (["horizontal", "vertical"], "coding"), "Runs: filter bar state"
    )
    t.check(
        text(page, "#runCount").startswith(f"{want:,} of {len(runs):,}"),
        f"Runs: filtered count {text(page, '#runCount')!r} (want {want})",
    )
    topos = set(
        page.eval_on_selector_all(
            "#runTable tbody tr[data-run] td.topo", "els => els.map((e) => e.textContent)"
        )
    )
    t.check(topos <= {"Sequential", "Star"}, f"Runs: table topologies {topos}")
    page.click(".results-tabs a[data-tab='traffic']")
    page.wait_for_url(
        lambda u: u.endswith("/results/traffic-patterns/?topo=horizontal,vertical&task=coding")
    )
    page.wait_for_function(RESULTS_READY)
    t.eq(page.locator(".filter-bar").count(), 0, "Traffic: filter bar hidden")
    page.click(".results-tabs a[data-tab='overview']")
    page.wait_for_url(lambda u: u.endswith("/results/?topo=horizontal,vertical&task=coding"))
    page.wait_for_function(RESULTS_READY)
    t.check(
        (page.get_attribute("#iatThumbs a.thumb", "href") or "").endswith(
            "traffic-patterns/?topo=horizontal,vertical&task=coding#iat"
        ),
        "Overview: thumbnail link drops the filter",
    )
    page.click(".results-tabs a[data-tab='system']")
    page.wait_for_url(
        lambda u: u.endswith("/results/system-load/?topo=horizontal,vertical&task=coding")
    )
    page.wait_for_function(RESULTS_READY)
    f = page.evaluate(FILTER_JS)
    t.eq(
        (f["pressed"], f["task"]), (["horizontal", "vertical"], "coding"), "System: filter restored"
    )
    page.click("#filterReset")
    f = page.evaluate(FILTER_JS)
    t.eq((f["search"], len(f["pressed"]), f["task"]), ("", 3, ""), "Show all clears the filter")
    t.no_errors(watch, 0, "filter across tabs")

    # Scatter point -> the run on the Runs page.
    page.locator("#corrPlotBtn").scroll_into_view_if_needed()
    page.evaluate("() => document.getElementById('corrPlotBtn').click()")
    page.wait_for_selector("#corrScatter svg circle", state="attached", timeout=20_000)
    page.locator("#corrScatter svg").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    dot = page.locator("#corrScatter svg circle").nth(20).bounding_box()
    page.mouse.click(dot["x"] + dot["width"] / 2, dot["y"] + dot["height"] / 2)
    page.wait_for_url(
        lambda u: re.search(r"/results/run-explorer/#run=[0-9a-f]{8}$", u) is not None
    )
    page.wait_for_function(DETAIL_JS, timeout=10_000)
    run_hash = page.evaluate("() => location.hash")
    t.check(run_hash[5:] in text(page, "#runDetail .run-head"), "drill-down shows another run")
    t.check(
        "Recorded runs" in text(page, "#runDetail .run-head"), "drill-down: no Recorded runs badge"
    )
    for chart in ("gantt", "concurrency", "metrics"):
        t.check(
            page.locator(f"#runDetail [data-chart='{chart}'] svg").count() == 1,
            f"drill-down {chart} chart",
        )
    t.no_errors(watch, 0, "scatter -> runs")
    env.close()

    # 5. Runs: chips + demo-only filter, sort, row click -> drill-down.
    page, watch = env.open("results/run-explorer/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_selector("#runTable table tbody tr[data-run]")
    t.check("1,481 of 1,481" in text(page, "#runCount"), f"run count {text(page, '#runCount')!r}")
    page.click('.filter-bar .chip[data-topo="horizontal"]')
    page.click('.filter-bar .chip[data-topo="full_mesh"]')
    page.click('.filter-bar .chip[data-topo="vertical"]')  # the last one stays on
    t.eq(page.evaluate("() => location.search"), "?topo=vertical", "Runs: Star only")
    page.check("#runFixtures")
    t.eq(page.locator("#runTable tbody tr[data-run]").count(), 4, "Star demo runs in the table")
    page.uncheck("#runFixtures")
    page.click("#runTable th[data-col='score'] button")
    t.eq(
        page.get_attribute("#runTable th[data-col='score']", "aria-sort"),
        "descending",
        "sort by score",
    )
    row = page.locator("#runTable tbody tr[data-run]").first
    row_id = row.get_attribute("data-run")
    row.locator("td").nth(1).click()
    page.wait_for_function(f"() => location.hash === '#run={row_id}'", timeout=10_000)
    page.wait_for_function(DETAIL_JS)
    t.check(row_id in text(page, "#runDetail .run-head"), "row click opened another run")
    t.eq(
        page.evaluate("() => location.search"),
        "?topo=vertical",
        "Runs: filter kept with a run open",
    )
    t.no_errors(watch, 0, "runs page")
    env.close()

    # 6. Old single-page links: #run=<id> (with the query) and moved sections forward.
    page, watch = env.open(f"results/?task=math#run={fixture['run_id']}")
    page.wait_for_url(
        lambda u: u.endswith(f"/results/run-explorer/?task=math#run={fixture['run_id']}"),
        timeout=10_000,
    )
    page.wait_for_function(DETAIL_JS, timeout=20_000)
    t.check(
        fixture["run_id"] in text(page, "#runDetail .run-head"),
        "redirected #run= opened another run",
    )
    t.no_errors(watch, 0, "#run= redirect")
    for old, new in RESULTS_REDIRECTS.items():
        page.goto(env.base + "results/" + old)
        page.wait_for_url(lambda u, n=new: u.endswith("/" + n), timeout=10_000)
        page.wait_for_function(RESULTS_READY)
        t.check(page.locator(old).count() == 1, f"redirect {old}: no {old} on {new}")
    page.goto(env.base + "results/#table2")
    page.wait_for_function(RESULTS_READY)
    t.check(page.url.endswith("/results/#table2"), f"#table2 should stay on Overview ({page.url})")
    page.evaluate("() => { location.hash = '#network'; }")  # a later hash change forwards too
    page.wait_for_url(lambda u: u.endswith("/results/system-load/#network"), timeout=10_000)
    t.no_errors(watch, 0, "section redirects")
    env.close()

    # 7. Deep link to a demo fixture: replay + view links.
    page, watch = env.open(f"results/run-explorer/#run={fixture['run_id']}")
    page.wait_for_function(DETAIL_JS, timeout=20_000)
    replay = page.get_attribute("#runDetail [data-action='replay']", "href") or ""
    view = page.get_attribute("#runDetail [data-action='view']", "href") or ""
    t.eq(replay, "../../playground/run/?replay=full_mesh/math", "replay link")
    t.eq(view, f"../../playground/open/?demo=1&task_id={fixture['task_id']}", "view link")
    t.check(
        page.locator("#runDetail .callout").count() == 1
        and "waves of 5" in text(page, "#runDetail .callout")
        and "MAX_PARALLEL" not in text(page, "#runDetail"),
        "full-mesh waves-of-5 note missing",
    )
    t.check(
        "5" == text(page, "#runDetail .tile:nth-child(5) .tile-value"),
        "corrected peak in flight != 5",
    )
    shot = env.shots / "results-desktop-run.png"
    page.locator("#runDetail").screenshot(path=str(shot))
    t.notes.append(str(shot))
    t.no_errors(watch, 0, "deep link")
    page.click("#runDetail [data-action='replay']")
    page.wait_for_url(lambda u: "/playground/run/?replay=full_mesh/math" in u)
    page.wait_for_selector("#demoBanner", timeout=10_000)
    page.wait_for_function("() => window.__probe.sse >= 3", timeout=15_000)
    t.check(page.input_value("#topology") == "full_mesh", "replay did not select Full mesh")
    t.check(
        text(page, "#statusText") not in ("", "Ready"),
        f"replay status {text(page, '#statusText')!r}",
    )
    t.no_errors(watch, 0, "replay link")
    page, watch = env.open(f"results/run-explorer/#run={fixture['run_id']}")
    page.wait_for_function(DETAIL_JS, timeout=20_000)
    page.click("#runDetail [data-action='view']")
    page.wait_for_function("() => document.getElementById('statusText')?.textContent === 'Loaded'")
    t.check(fixture["task_id"] in text(page, "#taskIdLabel"), "view link opened another run")
    t.no_errors(watch, 0, "view link")

    # 8. Screenshots; no sideways scroll at 1280 and 375 px on every page (Runs with a run open).
    for label, width, height in (("desktop", 1280, 900), ("mobile", 375, 812)):
        for name, path in RESULTS_PAGES.items():
            if name == "runs":
                path += f"#run={fixture['run_id']}"
            page, watch = env.open(path, width, height)
            page.wait_for_function(RESULTS_READY)
            if name == "runs":
                page.wait_for_function(DETAIL_JS, timeout=20_000)
                page.wait_for_selector("#runTable table")
            page.wait_for_timeout(500)
            t.eq(
                page.evaluate(OVERFLOW_JS),
                0,
                f"results {name} {label}: horizontal page scroll (px)",
            )
            if name == "runs" and label == "mobile":
                page.locator("#runDetail").screenshot(
                    path=str(env.shots / "results-mobile-run.png")
                )
                t.notes.append(str(env.shots / "results-mobile-run.png"))
            page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
            page.wait_for_timeout(300)
            for shot_name, full in (
                (f"results-{name}-{label}.png", False),
                (f"results-{name}-{label}-full.png", True),
            ):
                page.screenshot(path=str(env.shots / shot_name), full_page=full)
                t.notes.append(str(env.shots / shot_name))
            t.no_errors(watch, 0, f"results {name} {label}")
            env.close()


OUTLIER_CHIPS_JS = """() => Object.fromEntries([...document.querySelectorAll('.outlier-chips .chip')]
  .map((b) => [b.dataset.rule, Number(b.querySelector('.chip-count').textContent.replace(/,/g, ''))]))"""


@case("outliers")
def case_outliers(env: Env, t: Case):
    """Unusual runs on the Run explorer (scripts/demo/analysis_outliers.py flags in runs.json):
    chip counts match runs.json, a rule chip and the topology filter narrow the list, a run id
    opens the drill-down with its reasons, the table's Flagged only box, both themes, 375 px."""
    doc = json.loads((DATA_DIR / "runs.json").read_text())
    if "outliers" not in doc:
        t.check(
            False, "runs.json has no outlier flags (run python -m scripts.demo.analysis_outliers)"
        )
        return
    runs = doc["runs"]
    flagged = [r for r in runs if r.get("flags")]
    by_rule = {
        r["key"]: sum(1 for x in flagged if any(f["rule"] == r["key"] for f in x["flags"]))
        for r in doc["outliers"]["rules"]
    }
    env.shots.mkdir(parents=True, exist_ok=True)
    rows = "#outlierBody table tbody tr[data-run]"

    page, watch = env.open("results/run-explorer/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_selector(rows)
    chips = page.evaluate(OUTLIER_CHIPS_JS)
    t.eq(chips.get(""), len(flagged), "Any flag count")
    t.eq(chips.get("", 0) and doc["outliers"]["n_flagged"], len(flagged), "n_flagged in runs.json")
    for key, n in by_rule.items():
        t.eq(chips.get(key), n, f"chip count {key}")
    t.eq(page.locator(rows).count(), min(10, len(flagged)), "first page of flagged runs")
    first_ids = page.eval_on_selector_all(rows, "els => els.map((e) => e.dataset.run)")
    want = sorted(flagged, key=lambda r: (-len(r["flags"]), r["id"]))[:10]
    t.eq(first_ids, [r["id"] for r in want], "flagged runs sorted by number of flags, then id")

    rule = max(by_rule, key=lambda k: (by_rule[k], k))
    label = next(r["label"] for r in doc["outliers"]["rules"] if r["key"] == rule)
    page.click(f'.outlier-chips .chip[data-rule="{rule}"]')
    t.eq(
        page.get_attribute(f'.outlier-chips .chip[data-rule="{rule}"]', "aria-pressed"),
        "true",
        "rule chip pressed",
    )
    tags = page.eval_on_selector_all(
        rows,
        "els => els.map((e) => [...e.querySelectorAll('.tag--flag')].map((x) => x.textContent))",
    )
    t.check(all(label in x for x in tags), f"rows without the {label} flag: {tags}")
    t.check(text(page, "#outlierCount").startswith(f"{by_rule[rule]:,} flagged"), "rule count line")

    # Topology filter: Star only.
    page.click('.filter-bar .chip[data-topo="horizontal"]')
    page.click('.filter-bar .chip[data-topo="full_mesh"]')
    page.wait_for_timeout(200)
    star = sum(1 for r in flagged if r["topology"] == "vertical")
    t.eq(page.evaluate(OUTLIER_CHIPS_JS).get(""), star, "Any flag count, Star only")
    topos = set(
        page.eval_on_selector_all(rows + " td.topo", "els => els.map((e) => e.textContent)")
    )
    t.eq(topos, {"Star"}, "list topologies, Star only")

    # A run id opens the drill-down with its reasons.
    rid = page.get_attribute(rows + " a[data-outlier-run]", "data-outlier-run")
    page.click(rows + " a[data-outlier-run]")
    page.wait_for_function(f"() => location.hash === '#run={rid}'")
    page.wait_for_function(DETAIL_JS, timeout=10_000)
    t.check(rid in text(page, "#runDetail .run-head"), "outlier link opened another run")
    run = next(r for r in runs if r["id"] == rid)
    t.eq(
        page.locator("#runDetail [data-run-flags] li").count(),
        len(run["flags"]),
        "drill-down lists the run's flags",
    )
    t.check(
        run["flags"][0]["reason"] in text(page, "#runDetail [data-run-flags]"),
        "drill-down shows the reason",
    )
    page.locator("#runDetail").screenshot(path=str(env.shots / "outliers-drilldown.png"))
    t.notes.append(str(env.shots / "outliers-drilldown.png"))

    # The run table's Flagged only box.
    page.click("#filterReset")
    page.check("#runFlagged")
    t.check(
        text(page, "#runCount").startswith(f"{len(flagged):,} of {len(runs):,}"),
        f"Flagged only: {text(page, '#runCount')!r}",
    )
    t.check(
        page.locator("#runTable tbody tr[data-run] .tag--flag").count()
        == page.locator("#runTable tbody tr[data-run]").count(),
        "Flagged only: every row carries a flag tag",
    )
    reasons = " ".join(f["reason"] for r in flagged for f in r["flags"])
    t.check("\u2014" not in reasons and "\u2013" not in reasons, "em/en dash in a reason")
    t.no_errors(watch, 0, "outliers")
    env.close()

    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            store = f"try {{ localStorage.setItem('{THEME_KEY}', '{theme}'); }} catch (e) {{}}"
            page, watch = env.open(
                "results/run-explorer/", width, height, color_scheme=theme, init=(store,)
            )
            page.wait_for_function(RESULTS_READY)
            page.wait_for_selector(rows)
            t.eq(page.evaluate(THEME_JS), theme, f"outliers {theme} {width}: theme")
            page.wait_for_timeout(300)
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"outliers {theme} {width}: horizontal scroll")
            path = env.shots / f"outliers-{theme}-{width}.png"
            page.locator("#outliers").screenshot(path=str(path))
            t.notes.append(str(path))
            t.no_errors(watch, 0, f"outliers {theme} {width}")
            env.close()


WORKFLOW_READY = "() => document.getElementById('workflowSections')?.dataset.ready === 'true'"
WORKFLOW_SYSTEM = {  # on System load: section id -> selectors that exist once it has rendered
    "wf-stages": ("#wfStagesChart svg path", "#wfExec table tbody tr"),
    "wf-roles": ("#wfRolesChart svg circle",),
}
WORKFLOW_BETA = {  # on the Beta page (exploratory analyses)
    "wf-messages": ("#wfMsgMatrix svg rect.wf-cell", "#wfConsensusChart svg rect.hit"),
    "wf-context": ("#wfContextChart svg polyline",),
    "wf-retries": ("#wfRetryChart svg rect.hit", "#wfRetryTable table tbody tr"),
    "wf-quality": ("#wfQualityChart svg circle", "#wfQualTable table tbody tr"),
}
WORKFLOW_SECTIONS = {**WORKFLOW_SYSTEM, **WORKFLOW_BETA}
WORKFLOW_FORBIDDEN_KEYS = {"task_id", "run_id", "id", "prompt", "response", "final_output"}


def _json_keys(obj, out: set) -> set:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _json_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _json_keys(v, out)
    return out


@case("workflow")
def case_workflow(env: Env, t: Case):
    """Inside the workflow (System load, js/workflow.js + workflow.json): sections, badges and
    On this page; charts drawn; toggles; topology and task filters; both themes, 375 px."""
    path = DATA_DIR / "workflow.json"
    if not path.is_file():
        t.check(False, "no workflow.json (run python -m scripts.demo.analysis_workflow)")
        return
    data = json.loads(path.read_text())
    t.check(
        not (_json_keys(data, set()) & WORKFLOW_FORBIDDEN_KEYS),
        f"workflow.json has per-run keys: {_json_keys(data, set()) & WORKFLOW_FORBIDDEN_KEYS}",
    )
    env.shots.mkdir(parents=True, exist_ok=True)
    page, watch = env.open("results/system-load/")
    page.wait_for_function(WORKFLOW_READY)
    t.eq(text(page, "#wfGroupTitle").strip(), "Inside the workflow", "group heading")
    toc = page.eval_on_selector_all(".page-toc a", "els => els.map((a) => a.getAttribute('href'))")
    for sid, selectors in WORKFLOW_SYSTEM.items():
        for sel in selectors:
            t.check(page.locator(sel).count() > 0, f"{sid}: nothing drawn ({sel})")
        t.check(page.locator(f"#{sid} h2 .badge").count() == 1, f"{sid}: heading has no data badge")
        t.check(f"#{sid}" in toc, f"On this page lacks a section: {toc}")
    for sid in WORKFLOW_BETA:
        t.eq(page.locator(f"#{sid}").count(), 0, f"{sid} should have moved to the Beta page")
    t.eq(page.locator("#contention").count(), 0, "contention should have moved to the Beta page")
    t.check(
        page.locator('.beta-link a[href*="beta/"]').count() == 1,
        "System load links to the Beta page",
    )
    t.check(
        not any("runs.json" in u for _, u in watch.requests), "runs.json fetched by workflow.js"
    )
    t.eq(page.locator("#wfStagesChart .legend > span").count(), 3, "stage legend entries")

    # Toggles redraw.
    before = text(page, "#wfStagesChart svg")
    page.click('#wfStageMeasure button[data-value="tokens"]')
    page.wait_for_timeout(150)
    t.check(text(page, "#wfStagesChart svg") != before, "stage measure toggle did not redraw")
    t.check("Share of tokens" in text(page, "#wfStagesChart svg"), "stage axis title after toggle")
    page.select_option("#wfRoleMetric", "latency_s")
    page.wait_for_timeout(150)
    t.check("Latency per call" in text(page, "#wfRolesChart svg"), "role measure select")
    page.click('.filter-bar .chip[data-topo="full_mesh"]')
    page.wait_for_timeout(250)
    t.eq(page.locator("#wfStagesChart .legend > span").count(), 2, "stage legend without Full mesh")
    t.no_errors(watch, 0, "workflow (System load)")
    env.close()

    # The four moved sections live on the Beta page.
    page, watch = env.open("results/beta/")
    page.wait_for_function(WORKFLOW_READY)
    page.wait_for_function(LOAD_READY)
    t.check(page.locator(".beta-banner").count() == 1, "beta banner")
    t.check("outside the scope of the research" in text(page, ".beta-banner"), "beta banner text")
    t.check(page.locator("h1 .beta-tag").count() == 1, "Beta tag in the page title")
    toc = page.eval_on_selector_all(".page-toc a", "els => els.map((a) => a.getAttribute('href'))")
    for sid, selectors in WORKFLOW_BETA.items():
        for sel in selectors:
            t.check(page.locator(sel).count() > 0, f"{sid}: nothing drawn ({sel})")
        t.check(page.locator(f"#{sid} h2 .badge").count() == 1, f"{sid}: heading has no data badge")
        t.check(f"#{sid}" in toc, f"On this page lacks a section: {toc}")
    t.check("#contention" in toc, "On this page lacks the contention section")
    # The traffic model playground: tiles, timeline (model + Poisson), sweep; controls redraw.
    page.wait_for_function(TRAFFIC_READY)
    t.check("#playground" in toc, "On this page lacks the playground section")
    t.eq(page.locator("#playground").count(), 1, "Beta: one playground")
    tiles = page.evaluate(TRAFFIC_TILES_JS)
    t.eq([x[0] for x in tiles], ["load", "p99", "arrivals", "waited", "wait"], "playground tiles")
    t.check(all(x[2] for x in tiles), "playground: every tile has its comparison line")
    t.check(
        all("Poisson:" in x[2] for x in tiles[1:]), f"playground: Poisson beside the model {tiles}"
    )
    t.eq(page.locator("#pgTimeline svg path.tr-step").count(), 2, "timeline: model + Poisson")
    t.eq(page.locator("#pgSweep svg circle").count(), 14, "sweep: 7 K values x 2")
    before = page.evaluate(TRAFFIC_TILES_JS)
    page.click('#pgTopo [data-topo="vertical"]')
    page.wait_for_timeout(400)
    t.check(page.evaluate(TRAFFIC_TILES_JS) != before, "playground: topology change redraws")
    page.locator("#pgK").fill("30")
    page.wait_for_timeout(500)
    t.eq(text(page, "#pgKOut"), "30", "playground: K output")
    k30 = page.evaluate(TRAFFIC_TILES_JS)
    page.locator("#pgHead").fill("80")
    page.wait_for_timeout(500)
    t.check(page.evaluate(TRAFFIC_TILES_JS) != k30, "playground: headroom redraws")
    slots = text(page, "#pgSlotsOut")
    page.click("#pgResample")
    page.wait_for_timeout(400)
    t.eq(text(page, "#pgSlotsOut"), slots, "playground: Resample keeps the slots")
    t.eq(
        page.locator('.results-tabs [aria-current="page"]').count(),
        0,
        "no core tab current on Beta",
    )
    t.check(
        not any("runs.json" in u for _, u in watch.requests), "runs.json fetched by workflow.js"
    )

    # Numbers on the page come from the data: Full mesh's consensus rate.
    fm = data["groups"]["all"]["full_mesh"]
    rate = round(fm["consensus"]["rate"] * 100)
    t.check(f"Full mesh agreed in {rate}%" in text(page, "#wfMsgNote"), "consensus note vs data")
    t.eq(
        page.locator("#wfMsgMatrix svg rect.wf-cell:not(.wf-cell--empty)").count(),
        sum(1 for row in fm["messages"]["count"] for c in row if c),
        "matrix cells with messages",
    )

    # Toggles redraw.
    page.click('#wfMsgMeasure button[data-value="tokens"]')
    page.wait_for_timeout(150)
    t.check("tokens per message" in text(page, "#wfMsgMatrix .legend"), "matrix measure toggle")
    page.click('#wfQualCost button[data-value="span_s"]')
    page.wait_for_timeout(150)
    t.check("Run length" in text(page, "#wfQualityChart svg"), "quality cost toggle")

    # Topology chips: drop Full mesh -> two series, matrix placeholder.
    page.click('.filter-bar .chip[data-topo="full_mesh"]')
    page.wait_for_timeout(250)
    t.eq(page.locator("#wfQualityChart svg circle.hit").count(), 2, "quality points w/o Full mesh")
    t.check(
        page.locator("#wfMsgMatrix .placeholder").count() == 1, "matrix placeholder w/o Full mesh"
    )
    t.check("Full mesh" not in text(page, "#wfMsgNote"), "consensus note still names Full mesh")
    # Task filter: per-task aggregates.
    page.click("#filterReset")
    page.select_option("#filterTask", "math")
    page.wait_for_timeout(250)
    math = data["groups"]["math"]["full_mesh"]["consensus"]["rate"]
    t.check(
        f"Full mesh agreed in {round(math * 100)}%" in text(page, "#wfMsgNote"),
        "task filter: consensus note uses the math aggregates",
    )
    t.no_errors(watch, 0, "workflow (Beta)")
    env.close()

    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            page, watch = env.open("results/beta/", width, height, color_scheme=theme)
            page.wait_for_function(WORKFLOW_READY)
            page.wait_for_function(LOAD_READY)
            page.wait_for_timeout(300)
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"beta {theme} {width}: horizontal scroll")
            page.add_style_tag(content=".results-tabs { position: static !important; }")
            shot = env.shots / f"workflow-{theme}-{width}.png"
            page.locator("#workflowSections").screenshot(path=str(shot))
            t.notes.append(str(shot))
            t.no_errors(watch, 0, f"beta {theme} {width}")
            env.close()


# ---------------------------------------------------------------------------
# Load (System page: server and network, js/load.js + load.json)
# ---------------------------------------------------------------------------

LOAD_READY = "() => document.body.dataset.loadReady === 'true'"
LOAD_SECTIONS = [
    "network",
    "concurrency",
    "correlations",
    "comparisons",
]  # contention is on the Beta page
# ("calls" is allowed: in load.json it is a count per bin, never a list of calls)
LOAD_FORBIDDEN_KEYS = {"task_id", "run_id", "task_dir", "prompt", "response", "runs", "call_fields"}


def _seconds(v: float) -> str:
    """seconds() in ui/results/js/util.js, for values from 1 s up."""
    return f"{v:.2f} s" if v < 10 else f"{v:.1f} s" if v < 100 else f"{v:.0f} s"


@case("load")
def case_load(env: Env, t: Case):
    """Server and network (System load): flow diagram, concurrency, contention, comparisons;
    order, badges and On this page; numbers from load.json; tooltips by mouse and keyboard;
    the within-topology link; both themes, 375 px."""
    path = DATA_DIR / "load.json"
    if not path.is_file():
        t.check(False, "no load.json (run python -m scripts.demo.analysis_load)")
        return
    data = json.loads(path.read_text())
    t.check(
        not (_json_keys(data, set()) & LOAD_FORBIDDEN_KEYS),
        f"load.json has per-run keys: {_json_keys(data, set()) & LOAD_FORBIDDEN_KEYS}",
    )
    env.shots.mkdir(parents=True, exist_ok=True)
    page, watch = env.open("results/system-load/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_function(LOAD_READY)
    order = page.eval_on_selector_all("main section[data-toc]", "els => els.map((e) => e.id)")
    t.eq([i for i in order if i in LOAD_SECTIONS], LOAD_SECTIONS, "server and network order")
    toc = page.eval_on_selector_all(".page-toc a", "els => els.map((a) => a.getAttribute('href'))")
    t.check(all(f"#{i}" in toc for i in LOAD_SECTIONS), f"On this page lacks a section: {toc}")
    for sid in ("network", "concurrency", "comparisons"):
        t.eq(page.locator(f"#{sid} h2 .badge").count(), 1, f"{sid}: heading badge")
    t.check(
        text(page, "#netTitle").startswith("Same task, different load"), "network section title"
    )
    t.eq(page.locator("#netChart svg path.flow-band").count(), 12, "flow bands (3 x 4)")
    t.eq(page.locator("#concChart svg path").count() >= 3, True, "concurrency bars")
    t.eq(
        page.eval_on_selector_all("#concChart .conc-peak", "els => els.map((e) => e.textContent)"),
        [str(data["concurrency"][k]["true_peak"]) for k in ("horizontal", "vertical", "full_mesh")],
        "true peaks on the page",
    )
    t.eq(
        [data["concurrency"][k]["true_peak"] for k in ("horizontal", "vertical", "full_mesh")],
        [1, 3, 5],
        "true peaks 1 / 3 / 5",
    )
    t.eq(page.locator("#contention").count(), 0, "contention moved to the Beta page")
    cmp = data["comparisons"]
    t.eq(
        page.locator("#cmpTable td.cmp-cell").count(),
        len(cmp["metrics"]) * 3,
        "comparison cells (one median per topology)",
    )
    t.eq(page.locator("#cmpSummary").count(), 0, "comparison summary removed")
    t.check("Cliff" not in text(page, "#comparisons"), "comparisons: no Cliff's delta")
    t.check(
        set(cmp) == {"pairs", "metrics", "excluded"}
        and all(set(p) == {"n", "median"} for m in cmp["metrics"] for p in m["pairs"]),
        "comparisons: data holds only n and median per pair",
    )
    for sid in ("network", "concurrency", "comparisons", "correlations"):
        body = text(page, f"#{sid}")
        t.check(
            not re.search(
                r"Prometheus|collector|metrics\.csv|per_run_metrics|balanced_agents|rounding|(?<![\d.])10 ms"
                r"|cross_layer|workflow\.json|Reproduces",
                body,
            ),
            f"{sid}: no implementation wording",
        )
    t.check("%" in text(page, "#cmpTable"), "comparisons: percentage changes")
    t.eq(page.locator("#correlations .within-check").count(), 0, "no within-topology check")
    t.check("measurement layers agree" in text(page, "#correlations .lede"), "correlations: purpose")
    t.check(
        any(u.endswith("/data/private/load.json") for _, u in watch.requests),
        "load.json not fetched",
    )
    t.check(not any("runs.json" in u for _, u in watch.requests), "runs.json fetched by load.js")

    # Tooltips: mouse on a flow band.
    page.add_style_tag(content=".results-tabs { position: static !important; }")
    for sel, want in (("#netChart svg path.flow-band", "median run"),):
        el = page.locator(sel).first
        el.scroll_into_view_if_needed()
        el.hover()
        page.wait_for_timeout(100)
        tip = text(page, "#tooltip")
        t.check(page.is_visible("#tooltip") and want in tip, f"hover {sel}: tooltip {tip[:80]!r}")
    page.mouse.move(0, 0)
    t.no_errors(watch, 0, "load page")
    env.close()

    # Contention (exploratory) is on the Beta page, drawn from load.json too.
    page, watch = env.open("results/beta/")
    page.wait_for_function(LOAD_READY)
    t.eq(page.locator("#contention h2 .badge").count(), 1, "contention: heading badge")
    t.check(page.locator("#contChart svg circle.cont-dot").count() > 10, "contention dots")
    worst = max(data["contention"]["discussion"].values(), key=lambda d: d["latency_p95_s"])
    finding = text(page, "#contFinding")
    t.check(
        _seconds(worst["latency_p95_alone_s"]) in finding,
        f"contention finding lacks {_seconds(worst['latency_p95_alone_s'])}: {finding[:160]}",
    )
    t.no_errors(watch, 0, "load: contention on Beta")
    env.close()

    # Both themes, desktop and 375 px: no sideways scroll, no errors, screenshots.
    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            page, watch = env.open("results/system-load/", width, height, color_scheme=theme)
            page.wait_for_function(LOAD_READY)
            page.wait_for_timeout(300)
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"load {theme} {width}: horizontal scroll")
            page.add_style_tag(content=".results-tabs { position: static !important; }")
            for sid in ("network", "concurrency", "comparisons"):
                shot = env.shots / f"load-{sid}-{theme}-{width}.png"
                page.locator(f"#{sid}").screenshot(path=str(shot))
                t.notes.append(str(shot))
            t.no_errors(watch, 0, f"load {theme} {width}")
            env.close()


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

THEME_KEY = "agentraffic-theme"
# Records whether <html data-theme> was set before the parser created <body> (mutation records
# arrive in document order, so this holds even if the observer callback runs late).
THEME_PROBE_JS = """
(() => {
  const p = window.__themeProbe = { order: [] };
  const mo = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'attributes' && r.target === document.documentElement && !p.order.includes('theme')) {
        p.order.push('theme');
      }
      if (r.type === 'childList' && !p.order.includes('body')
          && [...r.addedNodes].some((n) => n.nodeName === 'BODY')) {
        p.order.push('body');
      }
    }
    if (p.order.length === 2) mo.disconnect();
  });
  mo.observe(document, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-theme'] });
})();
"""
THEME_BG = {"light": "rgb(247, 247, 245)", "dark": "rgb(15, 23, 42)"}  # --bg-primary
THEME_JS = "() => document.documentElement.getAttribute('data-theme')"
STORED_JS = f"() => {{ try {{ return localStorage.getItem('{THEME_KEY}'); }} catch (e) {{ return 'blocked'; }} }}"
CHECKED_JS = "() => document.querySelector('.theme-toggle button[aria-checked=\"true\"]')?.dataset.themeChoice"
TOGGLE_READY = "() => !!document.querySelector('.theme-toggle button[data-theme-choice]')"
VIEWER_LOADED = "() => document.getElementById('statusText').textContent === 'Loaded'"
UNSTICK_CSS = ".results-tabs { position: static !important; }"


TRAFFIC_ORDER = ["#iat", "#bursts", "#gaps", "#scaling", "#fits", "#robustness"]
TRAFFIC_READY = (
    "() => document.body.dataset.ready === 'true' && document.body.dataset.trafficReady === 'true'"
)
TRAFFIC_TILES_JS = """() => [...document.querySelectorAll('#pgTiles .tile')].map((t) => [
  t.dataset.tile, t.querySelector('.tile-value').textContent, t.querySelector('.tile-sub').textContent])"""


RUN_FOR_ZOOM = "1e43cc76"  # a Sequential run in the private runs.json


@case("traffic")
def case_traffic(env: Env, t: Case):
    """Traffic patterns: bursts, gaps, fits, robustness (the playground is on the Beta page)."""
    path = DATA_DIR / "traffic.json"
    if not path.is_file():
        t.check(False, "no traffic.json (run python -m scripts.demo.analysis_traffic)")
        return
    data = json.loads(path.read_text())
    rob = data["robustness"]
    env.shots.mkdir(parents=True, exist_ok=True)
    page, watch = env.open("results/traffic-patterns/")
    page.wait_for_function(TRAFFIC_READY)
    order = page.eval_on_selector_all("main section[data-toc]", "els => els.map((e) => '#' + e.id)")
    t.eq(order, TRAFFIC_ORDER, "traffic: section order")
    t.eq(
        page.eval_on_selector_all(".group-title", "els => els.map((e) => e.textContent)"),
        ["Arrivals", "Models"],
        "traffic: group titles",
    )
    for sec in TRAFFIC_ORDER:
        t.check(page.locator(f"{sec} h2 .badge").count() == 1, f"traffic: {sec} badge")
    # Bursts: three panels; Star is solver alone (25%) and reviewers in threes (75%).
    t.eq(page.locator("#burstSizes figure svg.viz").count(), 3, "burst size panels")
    star = dict(data["bursts"]["vertical"]["sizes"])
    want = f"{round(100 * 3 * star[3] / data['bursts']['vertical']['n_calls'])}%"
    labels = page.eval_on_selector_all(
        '#burstSizes figure[data-topology="vertical"] svg text.annot',
        "els => els.map((e) => e.textContent)",
    )
    t.check(want in labels, f"Star burst-of-3 label {want} in {labels}")
    t.eq(page.locator("#onOff svg rect.hit").count(), 5, "ON/OFF rows (Sequential has no ON)")
    t.eq(page.locator("#burstTable tbody tr").count(), 3, "burst table rows")
    # Gaps: panels with the all-gaps outline; table medians from the data.
    t.eq(page.locator("#gapCharts svg path.tr-outline").count(), 3, "gap outlines")
    gap_rows = page.eval_on_selector_all(
        "#gapTable tbody tr", "els => els.map((e) => e.textContent)"
    )
    t.check("9.47 s" in gap_rows[1] and "0.41 ms" in gap_rows[1], f"Star gap row: {gap_rows[1]}")
    # Fits table moved to its own section (iat.js still draws it).
    t.eq(page.locator("#fits #iatTable tbody tr").count(), 9, "fit table rows in #fits")
    # Robustness: the paper's published rates, table first then 3 panels x 3 families x 3 n markers.
    t.eq(page.locator("#robCharts circle.tr-ours").count(), 27, "robustness: markers")
    t.eq(page.locator("#robCharts circle.tr-paper").count(), 0, "robustness: no paper markers")
    t.eq(page.locator("#robCaption").count(), 0, "robustness: no provenance caption")
    t.check("published in the paper" not in text(page, "#robustness"), "robustness: no caption")
    t.check(
        page.evaluate(
            "() => document.getElementById('robTable').compareDocumentPosition("
            "document.getElementById('robCharts')) & Node.DOCUMENT_POSITION_FOLLOWING"
        ) > 0,
        "robustness: table above the plots",
    )
    t.check(
        not re.search(r"ours|Monte Carlo|seed|within \d+ point", text(page, "#robustness"), re.I),
        "robustness: no comparison with recomputed numbers",
    )
    t.eq(page.locator("#iatNotes .important").count(), 0, "fits: no provenance caption")
    t.check("published in the paper" not in text(page, "#iatNotes"), "fits: no caption")
    cells = page.eval_on_selector_all(
        "#robTable tbody td.num", "els => els.map((e) => e.textContent)"
    )
    t.eq(len(cells), 27, "robustness table cells")
    t.eq(cells[2].strip(), "51%", "Full mesh n=50 exponential cell (paper)")
    t.check(
        all(
            c["source"] == "paper"
            for tp in rob["per_topology"].values()
            for cell in tp["cells"].values()
            for c in cell.values()
        ),
        "robustness data: every cell is the paper's",
    )
    page.locator("#robCharts rect.hit").first.focus()
    t.check(page.locator("#tooltip").is_visible(), "robustness: keyboard focus shows the tooltip")
    # Full-screen view of each IAT histogram (js/fullscreen.js).
    fs_btns = page.locator("#iatCharts figure button.fs-btn")
    t.eq(fs_btns.count(), 3, "iat full screen: one button per topology")
    t.check(
        "full screen" in (fs_btns.first.get_attribute("aria-label") or "")
        and (fs_btns.first.get_attribute("title") or ""),
        "iat full screen: labelled button with tooltip",
    )
    inpage_w = page.locator("#iatCharts figure svg.viz").first.bounding_box()["width"]
    fs_btns.first.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog.fs-dialog[open] svg.viz")
    t.check(
        page.locator("dialog.fs-dialog[open] svg.viz").first.bounding_box()["width"] > inpage_w * 1.5,
        "iat full screen: dialog svg wider than the in-page one",
    )
    t.check(
        page.evaluate("document.activeElement.closest('dialog') !== null"),
        "iat full screen: focus moves into the dialog",
    )
    t.check(
        page.evaluate("getComputedStyle(document.documentElement).overflow") == "hidden",
        "iat full screen: page scroll locked",
    )
    t.check(
        page.locator("dialog.fs-dialog svg", has_text="log scale").count() >= 1,
        "iat full screen: starts on the log axis",
    )
    page.locator('dialog.fs-dialog [data-scale="linear"]').click()
    page.wait_for_function(
        "[...document.querySelectorAll('dialog.fs-dialog svg text')].some((e) => e.textContent.includes('linear scale'))"
    )
    t.eq(
        page.locator('#iatScale [aria-checked="true"]').get_attribute("data-scale"),
        "linear",
        "iat full screen: toggle in the dialog drives the page toggle",
    )
    page.keyboard.press("Escape")
    page.wait_for_selector("dialog.fs-dialog", state="detached")
    t.check(
        page.evaluate("document.activeElement === document.querySelector('#iatCharts figure button.fs-btn')"),
        "iat full screen: Esc closes and focus returns to the button",
    )
    page.locator('#iatScale [data-scale="log"]').click()
    fs_btns.nth(2).click()
    page.wait_for_selector("dialog.fs-dialog[open] svg.viz")
    page.locator("dialog.fs-dialog .fs-close").click()
    page.wait_for_selector("dialog.fs-dialog", state="detached")
    t.check(
        page.evaluate("document.activeElement === document.querySelectorAll('#iatCharts figure button.fs-btn')[2]"),
        "iat full screen: close button returns focus to its opener",
    )
    # The other distribution plots get the same full-screen view (scaling, bursts, ON/OFF, gaps).
    for name, scope, count in (
        ("scaling", "#scalingCharts figure", 3),
        ("burst sizes", "#burstSizes figure", 3),
        ("ON/OFF", "figure:has(> #onOff)", 1),  # already full width in the page: just not narrower
        ("gaps", "#gapCharts figure", 3),
    ):
        grow = 1.0 if name == "ON/OFF" else 1.5
        btn_sel = f"{scope} > button.fs-btn"
        btns = page.locator(btn_sel)
        t.eq(btns.count(), count, f"{name} full screen: one button per figure")
        t.check(
            "full screen" in (btns.first.get_attribute("aria-label") or "")
            and (btns.first.get_attribute("title") or ""),
            f"{name} full screen: labelled button with tooltip",
        )
        inpage_w = page.locator(f"{scope} svg.viz").first.bounding_box()["width"]
        btns.last.focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("dialog.fs-dialog[open] svg.viz")
        t.check(
            page.locator("dialog.fs-dialog[open] svg.viz").first.bounding_box()["width"] > inpage_w * grow,
            f"{name} full screen: dialog svg wider than the in-page one",
        )
        t.check(
            page.evaluate("document.activeElement.closest('dialog') !== null"),
            f"{name} full screen: focus moves into the dialog",
        )
        page.keyboard.press("Escape")
        page.wait_for_selector("dialog.fs-dialog", state="detached")
        t.check(
            page.evaluate(
                "(sel) => document.activeElement === [...document.querySelectorAll(sel)].pop()",
                btn_sel,
            ),
            f"{name} full screen: Esc closes and focus returns to the button",
        )
    # Range selection (js/zoom.js): drag zooms every IAT chart, the hash carries the range,
    # Escape / Reset clear it, and the filter query is left alone.
    page.goto(page.url.split("#")[0] + "?topo=horizontal,vertical#iat")
    page.wait_for_function(TRAFFIC_READY)
    box = page.locator("#iatCharts svg.zoomable").first.bounding_box()
    y = box["y"] + 80
    page.mouse.move(box["x"] + box["width"] * 0.5, y)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] * 0.7, y, steps=5)
    page.mouse.up()
    t.check(
        "#iat&zoom=" in page.url and "?topo=horizontal,vertical" in page.url,
        f"zoom: hash {page.url}",
    )
    t.eq(
        page.locator("#iatCharts svg", has_text="zoomed").count(), 3, "zoom: every IAT chart zoomed"
    )
    t.eq(page.locator("#iat .zoom-readout li").count(), 3, "zoom: readout per topology")
    t.eq(
        page.locator("#onOff svg", has_text="zoomed").count(),
        1,
        "zoom: ON/OFF chart follows the range",
    )
    t.eq(
        page.locator("#scalingCharts svg", has_text="zoomed").count(),
        3,
        "zoom: agent-count charts follow the range",
    )
    t.eq(page.locator("#scaling .zoom-readout li").count(), 3, "zoom: agent-count readout")
    t.check(
        page.locator("#gaps .zoom-bar__range").inner_text().startswith("Zoomed"),
        "zoom: shared with the gap charts",
    )
    page.reload()
    page.wait_for_function(TRAFFIC_READY)
    t.check(
        page.locator("#iat .zoom-bar__range").inner_text().startswith("Zoomed"),
        "zoom: restored from the hash",
    )
    page.locator("#gapCharts svg.zoomable").first.focus()
    page.keyboard.press("Escape")
    t.check("zoom=" not in page.url, f"zoom: Escape resets {page.url}")
    t.no_errors(watch, 0, "traffic zoom")
    # Run explorer: the time range of a run's Gantt / in-flight charts rides in the hash next to #run=.
    rz, rwatch = env.open("results/run-explorer/")
    rz.goto(rz.url.split("#")[0] + "#run=" + RUN_FOR_ZOOM)
    rz.wait_for_selector("[data-chart=gantt] svg.zoomable")
    rz.locator("[data-chart=gantt] svg.zoomable").first.scroll_into_view_if_needed()
    box = rz.locator("[data-chart=gantt] svg.zoomable").first.bounding_box()
    y = box["y"] + 40
    rz.mouse.move(box["x"] + box["width"] * 0.3, y)
    rz.mouse.down()
    rz.mouse.move(box["x"] + box["width"] * 0.6, y, steps=5)
    rz.mouse.up()
    t.check(f"#run={RUN_FOR_ZOOM}&tzoom=" in rz.url, f"run zoom: hash {rz.url}")
    t.eq(
        rz.locator("[data-chart=concurrency] svg", has_text="zoomed").count(),
        1,
        "run zoom: in-flight chart follows",
    )
    rz.reload()
    rz.wait_for_selector("[data-chart=gantt] svg.zoomable")
    t.check(
        rz.locator("[data-chart=time-zoom] .zoom-bar__range").inner_text().startswith("Zoomed"),
        "run zoom: restored from the hash",
    )
    t.no_errors(rwatch, 0, "run explorer zoom")
    t.no_errors(watch, 0, "traffic page")
    env.close()

    for theme, width in (("light", 1280), ("dark", 1280), ("light", 375), ("dark", 375)):
        init = (f"try {{ localStorage.setItem('{THEME_KEY}', '{theme}'); }} catch (e) {{}}",)
        page, watch = env.open("results/traffic-patterns/", width, 900, init=init)
        page.wait_for_function(TRAFFIC_READY)
        t.eq(page.evaluate(THEME_JS), theme, f"traffic {theme}: data-theme")
        t.eq(page.evaluate(OVERFLOW_JS), 0, f"traffic {theme} {width}px: horizontal page scroll")
        page.add_style_tag(content=UNSTICK_CSS)
        for sec in ("bursts", "gaps", "robustness"):
            page.locator(f"#{sec}").screenshot(
                path=str(env.shots / f"traffic-{sec}-{theme}-{width}.png")
            )
        page.locator("#iatCharts figure button.fs-btn").nth(1).click()
        page.wait_for_selector("dialog.fs-dialog[open] svg.viz")
        page.wait_for_timeout(300)
        t.eq(page.evaluate(OVERFLOW_JS), 0, f"traffic {theme} {width}px: overlay horizontal scroll")
        box = page.locator("dialog.fs-dialog").bounding_box()
        t.check(box["width"] <= width + 1, f"traffic {theme} {width}px: overlay fits the viewport")
        page.screenshot(path=str(env.shots / f"traffic-iat-fullscreen-{theme}-{width}.png"))
        page.keyboard.press("Escape")
        page.wait_for_selector("dialog.fs-dialog", state="detached")
        for tag, sel in (
            ("scaling", "#scalingCharts figure > button.fs-btn"),
            ("bursts", "#burstSizes figure button.fs-btn"),
            ("onoff", "figure:has(> #onOff) > button.fs-btn"),
            ("gaps", "#gapCharts figure button.fs-btn"),
        ):
            page.locator(sel).first.click()
            page.wait_for_selector("dialog.fs-dialog[open] svg.viz")
            page.wait_for_timeout(250)
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"traffic {theme} {width}px: {tag} overlay horizontal scroll")
            page.screenshot(path=str(env.shots / f"traffic-{tag}-fullscreen-{theme}-{width}.png"))
            page.keyboard.press("Escape")
            page.wait_for_selector("dialog.fs-dialog", state="detached")
        t.no_errors(watch, 0, f"traffic {theme} {width}px")
        env.close()


def theme_pages(env: Env) -> dict[str, tuple[str, str]]:
    """page -> (path, JS that is true once it has rendered)."""
    fm = env.entry("full_mesh", "math")["task_id"]
    return {
        "launcher": ("index.html", TOGGLE_READY),
        "runner": (
            "playground/run/index.html?demo=1",
            "() => !!document.getElementById('demoBanner')",
        ),
        "viewer": (f"playground/open/?demo=1&task_id={fm}", VIEWER_LOADED),
        "compare": ("playground/compare/", COMPARE_READY),
        "chat": ("playground/chat/", TOGGLE_READY),
        "results": ("results/", RESULTS_READY),
        "results-traffic": ("results/traffic-patterns/", RESULTS_READY),
        "results-system": ("results/system-load/", RESULTS_READY),
        "results-runs": ("results/run-explorer/", RESULTS_READY),
        "results-beta": ("results/beta/", RESULTS_READY),
        "blog": ("docs/blog/", TOGGLE_READY),
        "agentverse-docs": ("docs/agentverse/", TOGGLE_READY),
    }


def pick_theme(page: Page, choice: str):
    page.click(f'.theme-toggle button[data-theme-choice="{choice}"]')


def check_theme_state(t: Case, page: Page, theme: str, choice: str, what: str):
    t.eq(page.evaluate(THEME_JS), theme, f"{what}: data-theme")
    t.eq(page.evaluate(CHECKED_JS), choice, f"{what}: toggle shows")
    t.eq(
        page.evaluate("() => getComputedStyle(document.body).backgroundColor"),
        THEME_BG[theme],
        f"{what}: page background",
    )


def check_no_flash(t: Case, page: Page, what: str):
    order = page.evaluate("() => window.__themeProbe && window.__themeProbe.order")
    t.check(
        bool(order) and order[0] == "theme",
        f"{what}: data-theme not set before <body> (mutation order {order})",
    )


# System page: heatmap cell, colour ramp, Sequential network bar, first scatter dot, card.
CHART_COLOURS_JS = """() => {
  const fill = (el) => el ? getComputedStyle(el).fill : null;
  const cell = [...document.querySelectorAll('#corrHeatmap rect.cell')]
    .find((r) => (r.getAttribute('fill') || '').startsWith('#'));
  return {
    cell: cell ? cell.getAttribute('fill') : null,
    ramp: document.querySelector('#corrScale .ramp')?.style.background || null,
    bar: fill(document.querySelector('#netChart svg path[fill^="var("]')),
    dot: fill(document.querySelector('#corrScatter svg circle')),
    card: getComputedStyle(document.querySelector('#correlations')).backgroundColor,
  };
}"""
# Traffic page: Sequential IAT bar and the log-normal fit curve.
IAT_COLOURS_JS = """() => ({
  bar: getComputedStyle(document.querySelector('#iatCharts figure[data-topology="horizontal"] svg path[fill^="var("]')).fill,
  fit: getComputedStyle(document.querySelector('#iatCharts polyline.fit--lognormal')).stroke,
})"""


def plot_scatter(page: Page):
    """Open the correlation scatter for a screenshot or colour check. The results case tests the
    real click path; here the layout can still shift while sections render as they scroll into
    view, which made a mouse click occasionally miss, so trigger the button directly."""
    page.locator("#corrPlotBtn").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    page.evaluate("() => document.getElementById('corrPlotBtn').click()")


@case("theme")
def case_theme(env: Env, t: Case):
    env.shots.mkdir(parents=True, exist_ok=True)
    pages = theme_pages(env)
    init = (THEME_PROBE_JS,)

    # 1. Every page in both themes, with the OS asking for dark: light with nothing stored (the
    #    default; the OS setting is ignored), dark from a stored choice. Renders with no errors,
    #    theme applied before <body>, no sideways scroll at 375 px.
    for theme in ("light", "dark"):
        for name, (path, ready) in pages.items():
            for width, height in ((1280, 900), (375, 812)):
                what = f"{name} {theme} @{width}"
                page, watch = env.open(
                    path, width, height, color_scheme="dark", init=init, store_theme=theme == "dark"
                )
                page.wait_for_function(ready, timeout=20_000)
                page.wait_for_function(TOGGLE_READY)
                check_theme_state(t, page, theme, theme, what)
                check_no_flash(t, page, what)
                if theme == "light":
                    t.eq(page.evaluate(STORED_JS), None, f"{what}: nothing stored")
                t.eq(page.locator(".theme-toggle").count(), 1, f"{what}: toggles in the header")
                t.eq(
                    page.evaluate(
                        "() => [...document.querySelectorAll('.theme-toggle button')]"
                        ".map((b) => b.dataset.themeChoice)"
                    ),
                    ["light", "dark"],
                    f"{what}: toggle choices",
                )
                if width == 375:
                    t.eq(page.evaluate(OVERFLOW_JS), 0, f"{what}: horizontal page scroll (px)")
                t.no_errors(watch, 0, what)
                env.close()

    # 2. The choice persists across reloads, pages and open tabs; the OS setting never changes it.
    page, watch = env.open("index.html", color_scheme="dark", init=init, store_theme=False)
    page.wait_for_function(TOGGLE_READY)
    t.eq(page.evaluate(STORED_JS), None, "nothing stored on first visit")
    check_theme_state(t, page, "light", "light", "launcher defaults to Light while the OS is dark")
    page.emulate_media(color_scheme="light")
    pick_theme(page, "dark")
    check_theme_state(t, page, "dark", "dark", "launcher after picking Dark")
    t.eq(page.evaluate(STORED_JS), "dark", "stored choice")
    page.reload()
    page.wait_for_function(TOGGLE_READY)
    check_theme_state(t, page, "dark", "dark", "launcher after reload")
    check_no_flash(t, page, "launcher after reload")
    for name in ("results", "runner", "viewer", "chat"):
        path, ready = pages[name]
        page.goto(env.base + path)
        page.wait_for_function(ready, timeout=20_000)
        page.wait_for_function(TOGGLE_READY)
        check_theme_state(t, page, "dark", "dark", f"{name} after picking Dark on the launcher")
        check_no_flash(t, page, f"{name} (stored Dark)")
    other = page.context.new_page()  # a second tab follows the choice through the storage event
    other.goto(env.base + "index.html")
    other.wait_for_function(TOGGLE_READY)
    check_theme_state(t, other, "dark", "dark", "second tab (stored Dark)")
    pick_theme(page, "light")  # on the chat page; OS says light
    check_theme_state(t, page, "light", "light", "Light on the chat page")
    other.wait_for_function("() => document.documentElement.getAttribute('data-theme') === 'light'")
    check_theme_state(t, other, "light", "light", "second tab follows Light")
    other.close()
    page.emulate_media(color_scheme="dark")
    page.wait_for_timeout(200)
    check_theme_state(t, page, "light", "light", "Light stays when the OS switches to dark")
    page.goto(env.base + "index.html")
    page.wait_for_function(TOGGLE_READY)
    check_theme_state(t, page, "light", "light", "launcher keeps Light while the OS is dark")
    page.focus('.theme-toggle button[data-theme-choice="light"]')  # arrows move the selection
    page.keyboard.press("ArrowRight")
    check_theme_state(t, page, "dark", "dark", "ArrowRight on the toggle")
    page.keyboard.press("ArrowRight")
    check_theme_state(t, page, "light", "light", "ArrowRight wraps to Light (OS dark)")
    t.eq(page.evaluate(STORED_JS), "light", "stored Light")
    page.evaluate(f"() => localStorage.setItem('{THEME_KEY}', 'system')")  # an old saved value
    page.reload()
    page.wait_for_function(TOGGLE_READY)
    check_theme_state(t, page, "light", "light", "a stale 'system' choice reads as Light")
    check_no_flash(t, page, "launcher (stale 'system')")
    t.no_errors(watch, 0, "persistence")
    env.close()

    # 3. Charts recolour on toggle (System page): CSS-variable marks and the computed heatmap.
    page, watch = env.open("results/system-load/", color_scheme="light", init=init)
    page.wait_for_function(RESULTS_READY)
    page.locator("#correlations").scroll_into_view_if_needed()
    plot_scatter(page)
    page.wait_for_selector("#corrScatter svg circle", state="attached", timeout=20_000)
    light = page.evaluate(CHART_COLOURS_JS)
    pick_theme(page, "dark")
    page.wait_for_timeout(200)
    dark = page.evaluate(CHART_COLOURS_JS)
    for key in ("cell", "ramp", "bar", "card"):
        t.check(
            light[key] and dark[key] and light[key] != dark[key],
            f"results: {key} colour did not change on toggle ({light[key]} -> {dark[key]})",
        )
    t.check(
        light["dot"] == light["bar"],
        f"results: scatter dot {light['dot']} != Sequential bar {light['bar']}",
    )
    t.check(
        dark["dot"] == dark["bar"], f"results: dark scatter dot {dark['dot']} != bar {dark['bar']}"
    )
    t.eq(
        page.locator("#corrHeatmap svg rect.cell").count(),
        corr_metric_count(results_summary()) ** 2,
        "heatmap cells after toggle",
    )
    pick_theme(page, "light")
    page.wait_for_timeout(200)
    t.eq(page.evaluate(CHART_COLOURS_JS), light, "results: colours after toggling back to light")
    t.no_errors(watch, 0, "results toggle")
    t.notes.append(
        f"results light {light['bar']} / dark {dark['bar']} (Sequential); heatmap cell {light['cell']} -> {dark['cell']}"
    )
    env.close()
    # ... and on the Traffic page: IAT bars (same Sequential colour as the System page) and fits.
    page, watch = env.open("results/traffic-patterns/", color_scheme="light", init=init)
    page.wait_for_function(RESULTS_READY)
    iat_light = page.evaluate(IAT_COLOURS_JS)
    pick_theme(page, "dark")
    page.wait_for_timeout(200)
    iat_dark = page.evaluate(IAT_COLOURS_JS)
    for key in ("bar", "fit"):
        t.check(
            iat_light[key] != iat_dark[key],
            f"traffic: IAT {key} colour did not change on toggle ({iat_light[key]})",
        )
    t.eq(
        (iat_light["bar"], iat_dark["bar"]),
        (light["bar"], dark["bar"]),
        "traffic: Sequential bar vs System page",
    )
    t.no_errors(watch, 0, "traffic toggle")
    env.close()

    # 4. Runner: the topology diagram and flow graph recolour mid-replay; no errors.
    page, watch = env.open(
        "playground/run/index.html?demo=1&speed=20", color_scheme="dark", init=init
    )
    page.wait_for_selector("#demoBanner")
    start_run(page, "full_mesh", "math")
    # attached, not visible: at 20x the run can finish and collapse stage 1 first
    page.wait_for_selector(".topo-diagram-svg .topo-node circle", state="attached", timeout=20_000)
    node_js = (
        "() => getComputedStyle(document.querySelector('.topo-diagram-svg .topo-node circle')).fill"
    )
    edge_js = (
        "() => getComputedStyle(document.querySelector('.topo-diagram-svg .topo-edge')).stroke"
    )
    before = (page.evaluate(node_js), page.evaluate(edge_js))
    pick_theme(page, "light")
    page.wait_for_timeout(400)  # edges ease their stroke over 0.15 s
    after = (page.evaluate(node_js), page.evaluate(edge_js))
    t.check(before[0] != after[0], f"runner: topology node fill did not change ({before[0]})")
    t.check(before[1] != after[1], f"runner: topology edge did not change ({before[1]})")
    wait_done(page, env.entry("full_mesh", "math"), timeout=30_000)
    check_rendered(t, page, env, env.entry("full_mesh", "math"), "runner (light)")
    t.no_errors(watch, 0, "runner toggle")
    env.close()

    # 5. Screenshots, light + dark, 1280 and 375 px.
    fixture = next(
        f
        for f in results_summary()["fixtures"]
        if f["topology"] == "full_mesh" and f["task"] == "math"
    )
    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            tag = f"{theme}-{width}"

            def shoot(page: Page, name: str, element: str | None = None):
                path = str(env.shots / f"theme-{name}-{tag}.png")
                if element:  # unstick the results TOC so it doesn't cover a stitched element
                    page.locator(element).screenshot(path=path, style=UNSTICK_CSS)
                else:
                    page.screenshot(path=path)
                t.notes.append(path)

            page, watch = env.open("index.html", width, height, color_scheme=theme)
            page.wait_for_function(TOGGLE_READY)
            shoot(page, "launcher")
            t.no_errors(watch, 0, f"launcher shot {tag}")

            page, watch = env.open(
                "playground/run/index.html?demo=1&speed=4", width, height, color_scheme=theme
            )
            page.wait_for_selector("#demoBanner")
            start_run(page, "full_mesh", "math")
            page.wait_for_function(
                "() => document.querySelectorAll('.topo-edge.topo-active').length >= 2",
                timeout=30_000,
                polling=20,
            )
            page.evaluate(
                "() => document.querySelector('.topo-diagram').scrollIntoView({ block: 'center' })"
            )
            page.wait_for_timeout(80)
            shoot(page, "runner")
            t.no_errors(watch, 0, f"runner shot {tag}")

            page, watch = env.open(pages["viewer"][0], width, height, color_scheme=theme)
            page.wait_for_function(pages["viewer"][1])
            page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
            page.wait_for_timeout(300)
            shoot(page, "viewer")
            page.evaluate(
                "() => document.getElementById('detailedFlowSection').scrollIntoView({ block: 'start' })"
            )
            page.wait_for_timeout(300)
            shoot(page, "viewer-flow")
            t.no_errors(watch, 0, f"viewer shot {tag}")

            page, watch = env.open("playground/chat/", width, height, color_scheme=theme)
            page.wait_for_function(TOGGLE_READY)
            shoot(page, "chat")
            t.no_errors(watch, 0, f"chat shot {tag}")

            page, watch = env.open("results/", width, height, color_scheme=theme)
            page.wait_for_function(RESULTS_READY)
            page.wait_for_timeout(300)
            shoot(page, "results-top")
            page.goto(env.base + "results/traffic-patterns/")
            page.wait_for_function(RESULTS_READY)
            page.evaluate("() => document.getElementById('iat').scrollIntoView({ block: 'start' })")
            page.wait_for_timeout(300)
            shoot(page, "results-iat")
            page.goto(env.base + "results/system-load/")
            page.wait_for_function(RESULTS_READY)
            plot_scatter(page)
            page.wait_for_selector("#corrScatter svg circle", state="attached", timeout=20_000)
            page.wait_for_timeout(300)
            page.mouse.move(0, 0)
            shoot(page, "results-corr", "#correlations")
            page.goto(env.base + f"results/run-explorer/#run={fixture['run_id']}")
            page.wait_for_function(DETAIL_JS, timeout=20_000)
            page.wait_for_timeout(500)
            shoot(page, "results-run", "#runDetail")
            t.no_errors(watch, 0, f"results shots {tag}")
            env.close()


# ---------------------------------------------------------------------------
# Docs menu, paper / code links, docs pages
# ---------------------------------------------------------------------------

EXPECTED_BIBTEX = (
    "@inproceedings{lamagna2026agentraffic, title={Towards Traffic Modelling of Multi-Agent Systems: "
    "The Role of Coordination Topology}, author={Lamagna, Davide and Cabellos, Albert and Rodriguez-"
    "Natal, Alberto and R{\\'e}tv{\\'a}ri, G{\\'a}bor and Serracanta, Berta}, booktitle={3rd ACM SIGCOMM "
    "Workshop on Networks for AI Computing (NAIC)}, year={2026}, publisher={ACM}, "
    "doi={10.1145/3789240.3828749}, url={https://doi.org/10.1145/3789240.3828749}}"
)
NAV_READY = "() => !!document.querySelector('.docs-menu__button') && !!document.querySelector('.paper-footer')"
MENU_JS = """() => {
  const b = document.querySelector('.docs-menu__button');
  const p = document.getElementById(b.getAttribute('aria-controls'));
  const r = p.getBoundingClientRect();
  const a = document.activeElement;
  return {
    expanded: b.getAttribute('aria-expanded'),
    shown: !p.hidden && r.width > 0,
    labels: [...p.querySelectorAll('.docs-menu__label')].map((e) => e.textContent),
    hrefs: [...p.querySelectorAll('a')].map((e) => e.href),
    focus: a === b ? 'button' : (a && a.dataset && a.dataset.doc) || (a && a.tagName),
    left: r.left, right: r.right, vw: document.documentElement.clientWidth,
    bg: getComputedStyle(p).backgroundColor,
  };
}"""
# A viewport point outside the Docs menu where a click hits nothing interactive.
OUTSIDE_POINT_JS = """() => {
  const menu = document.querySelector('.docs-menu');
  const skip = 'a, button, input, select, textarea, label, summary, svg, [onclick], [tabindex], .theme-toggle, #demoBanner';
  for (let y = 12; y < innerHeight - 12; y += 23) {
    for (let x = 6; x < innerWidth - 6; x += 29) {
      const el = document.elementFromPoint(x, y);
      if (el && !menu.contains(el) && !el.closest(skip) && getComputedStyle(el).cursor !== 'pointer') return [x, y];
    }
  }
  return null;
}"""
SURFACE = {"light": "rgb(255, 255, 255)", "dark": "rgb(30, 41, 59)"}  # --bg-secondary
# Records what the page hands to the clipboard API (then passes it on).
CLIPBOARD_SPY_JS = """
(() => {
  window.__copied = [];
  const c = navigator.clipboard;
  if (!c) return;
  const write = c.writeText.bind(c);
  c.writeText = (text) => { window.__copied.push(text); return write(text); };
})();
"""


# The paper's abstract as published (camera-ready, DOI 10.1145/3789240.3828749); the paper page
# must quote it word for word. Embedded so the check also runs without the LaTeX sources.
PUBLISHED_ABSTRACT = [
    "Multi-agent LLM systems are an emerging networked workload whose rapid deployment raises questions about the traffic patterns they generate. Compared to conventional applications, these systems generate requests internally: a single user task can induce a structured sequence of model calls whose timing is governed by coordination logic rather than by user arrival rate. It is not clear whether classical traffic models, designed for human-driven workloads, apply to this setting.",
    "We present an empirical characterisation of LLM-call inter-arrival time distributions across sequential, star, and full-mesh agentic coordination topologies, using a multi-layer measurement framework over 500 repeated runs per topology. We find that topology fundamentally shapes the arrival process of requests to the LLM backend: fan-out coordination introduces a structural bimodality absent in sequential execution, and the reasoning-phase component is best described by a log-normal distribution, with the Poisson exponential null model decisively rejected across all topologies. These differences propagate to inference and network level metrics. The framework and analysis pipeline are released openly at https://github.com/dlamagna/agentraffic.",
]


def check_copy(t: Case, page: Page, what: str):
    page.locator("[data-site-cite]").scroll_into_view_if_needed()
    shown = text(page, ".cite-block__code")
    page.click(".cite-block__copy")
    page.wait_for_function("() => !!document.querySelector('.cite-block__copy').dataset.state")
    copied = page.evaluate("() => window.__copied")
    t.eq(page.get_attribute(".cite-block__copy", "data-state"), "copied", f"{what}: copy state")
    t.check("Copied" in text(page, ".cite-block__status"), f"{what}: no 'Copied' status")
    t.eq(len(copied), 1, f"{what}: clipboard writes")
    if copied:
        t.eq(copied[0], shown, f"{what}: copied text vs shown BibTeX")
        t.eq(
            re.sub(r"\s+", "", copied[0]),
            re.sub(r"\s+", "", EXPECTED_BIBTEX),
            f"{what}: BibTeX entry",
        )


@case("docs")
def case_docs(env: Env, t: Case):
    env.shots.mkdir(parents=True, exist_ok=True)
    pages = theme_pages(env)

    # 1. Every page, both themes, 1280 and 375 px: links, menu by click (+ outside click), keyboard.
    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            for name, (path, ready) in pages.items():
                what = f"{name} {theme} @{width}"
                page, watch = env.open(path, width, height, color_scheme=theme)
                page.wait_for_function(ready, timeout=20_000)
                page.wait_for_function(NAV_READY)
                for href, label in ((PAPER_URL, "ACM DL"), (DOI_URL, "DOI"), (REPO_URL, "GitHub")):
                    n = page.locator(f'a[href="{href}"]').count()
                    t.check(n >= 1, f"{what}: no {label} link ({href})")
                t.eq(page.locator(".docs-menu").count(), 1, f"{what}: Docs menus")
                t.eq(
                    page.eval_on_selector_all(
                        ".results-menu__label", "els => els.map((e) => e.textContent)"
                    ),
                    RESULTS_TABS + ["Beta"],
                    f"{what}: Results menu entries",
                )
                m = page.evaluate(MENU_JS)
                t.check(m["expanded"] == "false" and not m["shown"], f"{what}: menu open on load")

                page.click(".docs-menu__button")
                m = page.evaluate(MENU_JS)
                t.check(
                    m["expanded"] == "true" and m["shown"], f"{what}: click did not open the menu"
                )
                t.eq(m["labels"], ["Blog post", "AgentVerse"], f"{what}: menu entries")
                t.check(
                    len(m["hrefs"]) == 2
                    and m["hrefs"][0].endswith("/docs/blog/")
                    and m["hrefs"][1].endswith("/docs/agentverse/"),
                    f"{what}: menu links {m['hrefs']}",
                )
                t.eq(m["bg"], SURFACE[theme], f"{what}: menu background")
                t.check(
                    m["left"] >= 0 and m["right"] <= m["vw"],
                    f"{what}: menu outside the viewport ({m['left']:.0f}-{m['right']:.0f} of {m['vw']})",
                )
                if width == 375:
                    t.eq(
                        page.evaluate(OVERFLOW_JS),
                        0,
                        f"{what}: horizontal scroll with the menu open",
                    )
                point = page.evaluate(OUTSIDE_POINT_JS)
                if t.check(point is not None, f"{what}: no free point to click outside"):
                    page.mouse.click(*point)
                    m = page.evaluate(MENU_JS)
                    t.check(
                        m["expanded"] == "false" and not m["shown"],
                        f"{what}: outside click left it open",
                    )
                if width == 375:
                    t.eq(page.evaluate(OVERFLOW_JS), 0, f"{what}: horizontal page scroll (px)")

                if width == 1280:
                    page.focus(".docs-menu__button")
                    for key, focus in (
                        ("ArrowDown", "blog"),
                        ("ArrowDown", "agentverse"),
                        ("ArrowDown", "blog"),
                        ("ArrowUp", "agentverse"),
                        ("Home", "blog"),
                        ("End", "agentverse"),
                    ):
                        page.keyboard.press(key)
                        m = page.evaluate(MENU_JS)
                        t.check(
                            m["expanded"] == "true" and m["focus"] == focus,
                            f"{what}: {key} -> focus {m['focus']}, expanded {m['expanded']} (want {focus})",
                        )
                    page.keyboard.press("Escape")
                    m = page.evaluate(MENU_JS)
                    t.check(
                        m["expanded"] == "false" and not m["shown"] and m["focus"] == "button",
                        f"{what}: Esc -> expanded {m['expanded']}, focus {m['focus']}",
                    )
                    page.keyboard.press("Enter")
                    t.eq(page.evaluate(MENU_JS)["expanded"], "true", f"{what}: Enter opens")
                    page.keyboard.press("Tab")
                    t.eq(page.evaluate(MENU_JS)["focus"], "blog", f"{what}: Tab into the menu")
                    page.keyboard.press("Escape")
                    page.keyboard.press(" ")
                    t.eq(page.evaluate(MENU_JS)["expanded"], "true", f"{what}: Space opens")
                    page.keyboard.press(" ")
                    t.eq(page.evaluate(MENU_JS)["expanded"], "false", f"{what}: Space closes")
                t.no_errors(watch, 0, what)
                env.close()

    # 2. From every page, both menu entries load without console errors.
    targets = {
        "blog": ("/docs/blog/", BLOG_TITLE),
        "agentverse": ("/docs/agentverse/", "AgentVerse"),
    }
    for name, (path, ready) in pages.items():
        for doc, (suffix, heading) in targets.items():
            page, watch = env.open(path)
            page.wait_for_function(ready, timeout=20_000)
            page.wait_for_function(NAV_READY)
            page.click(".docs-menu__button")
            page.click(f'.docs-menu__item[data-doc="{doc}"]')
            page.wait_for_url(lambda u, s=suffix: u.endswith(s))
            page.wait_for_function(NAV_READY)
            t.eq(text(page, "#pageTitle"), heading, f"{name} -> {doc}: page heading")
            current = page.get_attribute(f'.docs-menu__item[data-doc="{doc}"]', "aria-current")
            t.eq(current, "page", f"{name} -> {doc}: current entry")
            t.no_errors(watch, 0, f"{name} -> {doc}")
            env.close()

    # 3. Paper page content: abstract, numbers, BibTeX, slides.
    page, watch = env.open("docs/blog/", init=(CLIPBOARD_SPY_JS,))
    page.wait_for_function(NAV_READY)
    shown = [
        re.sub(r"\s+", " ", x).strip()
        for x in page.eval_on_selector_all(
            "#abstractText p", "els => els.map((e) => e.textContent)"
        )
    ]
    t.eq(shown, PUBLISHED_ABSTRACT, "abstract vs the published (camera-ready) version")
    # Blog post: casual text, the paper for details, and no em or en dashes (house style).
    body = page.inner_text("main")
    t.check("—" not in body and "–" not in body, "blog post: em/en dash in the text")
    t.check(page.locator(".tldr li").count() >= 3, "blog post: TL;DR list")
    t.check(
        page.locator(f'main a[href="{PAPER_URL}"]').count() >= 3,
        "blog post: links that point readers to the paper",
    )
    iat = results_summary()["iat"]["per_topology"]
    for topo, shown_pct in page.eval_on_selector_all(
        "[data-burst]", "els => els.map((e) => [e.dataset.burst, e.textContent.trim()])"
    ):
        want = f"{round(iat[topo]['burst_fraction'] * 100)}%"
        t.eq(shown_pct, want, f"blog post: {topo} burst share vs summary.json")
    t.eq(page.get_attribute("#readPaper", "href"), PAPER_URL, "Read the paper button")
    t.eq(page.get_attribute("#viewCode", "href"), REPO_URL, "View the code button")
    check_copy(t, page, "paper page BibTeX")
    # The NAIC 2026 slides: linked when the PDF is there, otherwise "to be added" and no link.
    slides_js = (
        "() => [...document.querySelectorAll('[data-slides]')].every((e) => e.dataset.state)"
    )
    pdf = UI_DIR / "docs" / "slides" / "naic2026-slides.pdf"
    page.wait_for_function(slides_js)
    t.eq(page.locator("[data-slides]").count(), 1, "slides entries")
    item = page.locator("[data-slides]").first
    link = item.locator("[data-slides-link]")
    t.eq(
        item.get_attribute("data-state"), "available" if pdf.exists() else "missing", "slides state"
    )
    t.eq(link.is_visible(), pdf.exists(), "slides link shown")
    if pdf.exists():
        target = link.evaluate("a => a.href")
        t.check(
            target.endswith("/docs/slides/naic2026-slides.pdf"), f"slides link target {target!r}"
        )
        t.eq(
            text(page, "[data-slides-link]").strip(),
            "Slides (NAIC 2026 talk, PDF)",
            "slides link text",
        )
    t.no_errors(watch, 0, "paper page")
    env.close()

    # The other branch, with the PDF answered by a route (404 if it is there, a PDF if it is not).
    page, watch = env.open("index.html")
    if pdf.exists():
        page.context.route(
            "**/docs/slides/naic2026-slides.pdf", lambda route: route.fulfill(status=404, body="no")
        )
    else:
        page.context.route(
            "**/docs/slides/naic2026-slides.pdf",
            lambda route: route.fulfill(
                status=200, content_type="application/pdf", body=b"%PDF-1.4\n%%EOF\n"
            ),
        )
    page.goto(env.base + "docs/blog/")
    page.wait_for_function(slides_js)
    item = page.locator("[data-slides]").first
    t.eq(
        item.get_attribute("data-state"),
        "missing" if pdf.exists() else "available",
        "slides state (routed)",
    )
    t.eq(
        item.locator("[data-slides-link]").is_visible(),
        not pdf.exists(),
        "slides link shown (routed)",
    )
    t.no_errors(watch, 0, "slides (routed)")
    env.close()

    # Results page: the same citation block.
    page, watch = env.open("results/", init=(CLIPBOARD_SPY_JS,))
    page.wait_for_function(RESULTS_READY)
    check_copy(t, page, "results page BibTeX")
    t.no_errors(watch, 0, "results page citation")
    env.close()

    # 4. Screenshots: paper page light / dark at 1280 and 375, AgentVerse page, menu open on the runner.
    def shot(page: Page, name: str, full: bool = False):
        path = str(env.shots / f"docs-{name}.png")
        page.screenshot(path=path, full_page=full)
        t.notes.append(path)

    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            tag = f"{theme}-{width}"
            page, watch = env.open("docs/blog/", width, height, color_scheme=theme)
            page.wait_for_function(NAV_READY)
            page.wait_for_timeout(200)
            shot(page, f"paper-{tag}")
            shot(page, f"paper-{tag}-full", full=True)
            page, watch = env.open("docs/agentverse/", width, height, color_scheme=theme)
            page.wait_for_function(NAV_READY)
            page.wait_for_timeout(200)
            shot(page, f"agentverse-{tag}")
            if theme == "light" and width == 1280:
                shot(page, f"agentverse-{tag}-full", full=True)
            page, watch = env.open(
                "playground/run/index.html?demo=1", width, height, color_scheme=theme
            )
            page.wait_for_selector("#demoBanner")
            page.wait_for_function(NAV_READY)
            page.click(".docs-menu__button")
            page.wait_for_timeout(200)
            shot(page, f"runner-menu-{tag}")
            t.no_errors(watch, 0, f"docs shots {tag}")
            env.close()


# ---------------------------------------------------------------------------
# Playground menu (the interactive tools)
# ---------------------------------------------------------------------------

# The main menu on every page, then the Playground entries: (data-tool, label, hint, path).
MAIN_MENU = ["Home", "Playground", "Results", "Docs", "Paper", "Code", "Portal"]
PLAYGROUND = [
    (
        "runner",
        "Run a workflow",
        "Start an AgentVerse run, or replay a recorded one",
        "/playground/run/",
    ),
    ("viewer", "Open a saved run", "Load a response.json or a run ID", "/playground/open/"),
    (
        "compare",
        "Compare topologies",
        "One task under all three topologies, side by side",
        "/playground/compare/",
    ),
    (
        "chat",
        "Chat with Agent A",
        "Send one task to the orchestrator; needs the live backend",
        "/playground/chat/",
    ),
]
CHAT_OFFLINE = "Send one task to the orchestrator; needs the local backend"
OLD_NAMES = ("Run Viewer", "Live Runner", "Classic Chat", "Try AgentVerse", "Agent Chat")
# page -> the Playground entry it is (current), for the tool pages
PLAYGROUND_CURRENT = {"runner": "runner", "viewer": "viewer", "compare": "compare", "chat": "chat"}
PLAY_READY = (
    "() => !!document.querySelector('.playground-menu__button') && !!document.querySelector('.paper-footer')"
    " && document.querySelector('.playground-menu__item[data-tool=\"chat\"]').dataset.backend === 'offline'"
)
PLAY_JS = """() => {
  const b = document.querySelector('.playground-menu__button');
  const p = document.getElementById(b.getAttribute('aria-controls'));
  const r = p.getBoundingClientRect();
  const a = document.activeElement;
  const host = document.querySelector('[data-site-nav]');
  const first = (n) => (n.matches('.site-menu') ? n.querySelector('button') : n).childNodes[0].textContent.trim();
  return {
    main: [...host.children].map(first),
    menus: document.querySelectorAll('.playground-menu').length,
    expanded: b.getAttribute('aria-expanded'),
    current: b.classList.contains('is-current'),
    shown: !p.hidden && r.width > 0,
    items: [...p.querySelectorAll('a')].map((e) => ({
      tool: e.dataset.tool,
      label: e.querySelector('.playground-menu__label').textContent,
      hint: e.title,
      path: new URL(e.href).pathname,
      current: e.getAttribute('aria-current'),
      backend: e.dataset.backend || null,
    })),
    focus: a === b ? 'button' : (a && a.dataset && a.dataset.tool) || (a && a.tagName),
    left: r.left, right: r.right, vw: document.documentElement.clientWidth,
    bg: getComputedStyle(p).backgroundColor,
  };
}"""


@case("playground")
def case_playground(env: Env, t: Case):
    env.shots.mkdir(parents=True, exist_ok=True)
    pages = theme_pages(env)

    # 1. Every page, light and dark, 1280 and 375 px: the main menu, the Playground entries (chat
    #    says it needs the local backend: nothing listens on :8101), the current tool, no old names.
    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            for name, (path, ready) in pages.items():
                what = f"{name} {theme} {width}"
                page, watch = env.open(path, width, height, color_scheme=theme)
                page.wait_for_function(ready, timeout=20_000)
                page.wait_for_function(PLAY_READY, timeout=8_000)
                m = page.evaluate(PLAY_JS)
                t.eq(m["main"], MAIN_MENU, f"{what}: main menu")
                t.eq(m["menus"], 1, f"{what}: Playground menus")
                t.eq(
                    m["current"],
                    name in PLAYGROUND_CURRENT,
                    f"{what}: Playground button marked current",
                )
                t.check(not m["shown"], f"{what}: Playground menu open on load")
                want = [
                    {
                        "tool": tool,
                        "label": label,
                        "hint": CHAT_OFFLINE if tool == "chat" else hint,
                        "path": p,
                        "current": "page" if PLAYGROUND_CURRENT.get(name) == tool else None,
                        "backend": "offline" if tool == "chat" else None,
                    }
                    for tool, label, hint, p in PLAYGROUND
                ]
                t.eq(m["items"], want, f"{what}: Playground entries")
                body = page.inner_text("body")
                old = [n for n in OLD_NAMES if n in body]
                t.check(not old, f"{what}: old names on the page: {old}")

                page.click(".playground-menu__button")
                m = page.evaluate(PLAY_JS)
                t.check(m["expanded"] == "true" and m["shown"], f"{what}: click did not open it")
                t.eq(m["bg"], SURFACE[theme], f"{what}: menu background")
                t.check(
                    m["left"] >= 0 and m["right"] <= m["vw"],
                    f"{what}: menu outside the viewport ({m['left']:.0f}-{m['right']:.0f} of {m['vw']})",
                )
                if width == 375:
                    t.eq(
                        page.evaluate(OVERFLOW_JS),
                        0,
                        f"{what}: horizontal scroll with the menu open",
                    )
                page.click(".playground-menu__button")
                t.eq(page.evaluate(PLAY_JS)["expanded"], "false", f"{what}: second click closes")

                # Keyboard, as for the Docs menu: arrows wrap, Home / End, Esc, Enter / Space, Tab.
                if width == 1280:
                    page.focus(".playground-menu__button")
                    for key, focus in (
                        ("ArrowDown", "runner"),
                        ("ArrowDown", "viewer"),
                        ("ArrowDown", "compare"),
                        ("ArrowDown", "chat"),
                        ("ArrowDown", "runner"),
                        ("ArrowUp", "chat"),
                        ("Home", "runner"),
                        ("End", "chat"),
                    ):
                        page.keyboard.press(key)
                        m = page.evaluate(PLAY_JS)
                        t.check(
                            m["expanded"] == "true" and m["focus"] == focus,
                            f"{what}: {key} -> focus {m['focus']}, expanded {m['expanded']} (want {focus})",
                        )
                    page.keyboard.press("Escape")
                    m = page.evaluate(PLAY_JS)
                    t.check(
                        m["expanded"] == "false" and not m["shown"] and m["focus"] == "button",
                        f"{what}: Esc -> expanded {m['expanded']}, focus {m['focus']}",
                    )
                    page.keyboard.press("Enter")
                    t.eq(page.evaluate(PLAY_JS)["expanded"], "true", f"{what}: Enter opens")
                    page.keyboard.press("Tab")
                    t.eq(page.evaluate(PLAY_JS)["focus"], "runner", f"{what}: Tab into the menu")
                    page.keyboard.press("Escape")
                    page.keyboard.press(" ")
                    t.eq(page.evaluate(PLAY_JS)["expanded"], "true", f"{what}: Space opens")
                    page.keyboard.press(" ")
                    t.eq(page.evaluate(PLAY_JS)["expanded"], "false", f"{what}: Space closes")
                t.no_errors(watch, 0, what)
                env.close()

    # 2. The new names: titles, headings, launcher cards; each entry opens its page.
    names = {
        "playground/run/index.html?demo=1": ("Run a workflow · agentraffic", "Run a workflow"),
        "playground/open/": ("Open a saved run · agentraffic", "Open a saved run"),
        "playground/compare/": ("Compare topologies · agentraffic", "Compare topologies"),
        "playground/chat/": ("Chat with Agent A · agentraffic", "Chat with Agent A"),
    }
    for path, (title, heading) in names.items():
        page, watch = env.open(path)
        page.wait_for_function(PLAY_READY, timeout=8_000)
        t.eq(page.title(), title, f"{path}: <title>")
        t.eq(" ".join(text(page, "h1").split()), heading, f"{path}: heading")
        env.close()
    page, watch = env.open("agentverse/viewer/")
    page.wait_for_url(lambda u: "/playground/open/" in u)
    t.eq(page.title(), "Open a saved run · agentraffic", "viewer/ redirect: <title>")
    env.close()
    page, watch = env.open("index.html")
    page.wait_for_function(PLAY_READY, timeout=8_000)
    cards = page.eval_on_selector_all(
        ".benchmark-card[data-tool]",
        "els => els.map((e) => [e.dataset.tool, e.querySelector('h2').textContent,"
        " new URL(e.querySelector('a').href).pathname])",
    )
    t.eq(
        cards,
        [[tool, label, p] for tool, label, _, p in PLAYGROUND],
        "launcher: Playground cards",
    )
    for tool, label, _, p in PLAYGROUND:
        page.goto(env.base + "index.html")
        page.wait_for_function(PLAY_READY, timeout=8_000)
        page.click(".playground-menu__button")
        page.click(f'.playground-menu__item[data-tool="{tool}"]')
        page.wait_for_url(lambda u, s=p: u.split("?")[0].endswith(s))
        page.wait_for_function(PLAY_READY, timeout=8_000)
        t.eq(" ".join(text(page, "h1").split()), label, f"launcher -> {tool}: heading")
    t.no_errors(watch, 0, "launcher -> Playground entries")
    env.close()

    # 3. Chat without a backend: the page explains it and Send is off (no request is sent);
    #    with ?demo=0 (use the endpoint anyway) the note is gone and Send works as before.
    page, watch = env.open("playground/chat/")
    page.wait_for_function("() => document.body.dataset.backend === 'offline'", timeout=8_000)
    t.check(page.is_visible("#backendNote"), "chat offline: no backend note")
    t.check(
        "needs the local backend" in text(page, "#backendNote").lower(), "chat offline: note text"
    )
    t.eq(
        text(page, "#backendUrl"),
        f"http://127.0.0.1:{AGENT_A_PORT}",
        "chat offline: Agent A URL in the note",
    )
    t.check(page.is_disabled("#sendBtn"), "chat offline: Send enabled")
    page.fill("#prompt", "hello")
    page.focus("#prompt")
    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(300)
    posts = [u for m, u in watch.requests if m == "POST" and f":{AGENT_A_PORT}" in u]
    t.eq(posts, [], "chat offline: POSTs sent by Ctrl+Enter")
    t.eq(text(page, "#status"), "", "chat offline: status after Ctrl+Enter")
    page.click("#backendRetry")
    page.wait_for_timeout(500)
    t.check(page.is_visible("#backendNote"), "chat offline: Check again hid the note")
    t.no_errors(watch, 0, "chat offline")
    env.close()
    page, watch = env.open("playground/chat/?demo=0")
    page.wait_for_function("() => document.body.dataset.backend === 'live'", timeout=8_000)
    t.check(not page.is_visible("#backendNote"), "chat ?demo=0: note shown")
    t.check(page.is_enabled("#sendBtn"), "chat ?demo=0: Send disabled")
    m = page.evaluate(
        "() => document.querySelector('.playground-menu__item[data-tool=\"chat\"]').dataset.backend || null"
    )
    t.eq(m, None, "chat ?demo=0: menu entry marked offline")
    env.close()

    # 4. Screenshots: the menu open on the launcher (light 1280, dark 375) and the offline chat page.
    for theme, width, height in (("light", 1280, 900), ("dark", 375, 812)):
        tag = f"{theme}-{width}"
        page, watch = env.open("index.html", width, height, color_scheme=theme)
        page.wait_for_function(PLAY_READY, timeout=8_000)
        page.click(".playground-menu__button")
        page.wait_for_timeout(200)
        path = str(env.shots / f"playground-launcher-{tag}.png")
        page.screenshot(path=path)
        t.notes.append(path)
        page.goto(env.base + "playground/chat/")
        page.wait_for_function("() => document.body.dataset.backend === 'offline'", timeout=8_000)
        path = str(env.shots / f"playground-chat-{tag}.png")
        page.screenshot(path=path)
        t.notes.append(path)
        t.no_errors(watch, 0, f"playground shots {tag}")
        env.close()


# ---------------------------------------------------------------------------
# Redirects: the old URLs
# ---------------------------------------------------------------------------

RUNNER_READY = "() => !!document.getElementById('demoBanner')"


def redirect_cases(env: Env) -> list[tuple[str, str, str]]:
    """(old URL, the new URL it must forward to, JS that is true once the new page rendered)."""
    fm = env.entry("full_mesh", "math")["task_id"]
    run_id = next(
        f["run_id"]
        for f in results_summary()["fixtures"]
        if f["topology"] == "full_mesh" and f["task"] == "math"
    )
    q = f"?demo=1&task_id={fm}"
    return [
        (
            "agentverse/?replay=full_mesh/math&speed=200#stage2",
            "playground/run/?replay=full_mesh/math&speed=200#stage2",
            RUNNER_READY,
        ),
        ("agentverse/index.html?demo=1#top", "playground/run/?demo=1#top", RUNNER_READY),
        (f"agentverse/viewer.html{q}#flow", f"playground/open/{q}#flow", VIEWER_LOADED),
        (f"agentverse/viewer/{q}#flow", f"playground/open/{q}#flow", VIEWER_LOADED),
        ("chat/?demo=1#send", "playground/chat/?demo=1#send", TOGGLE_READY),
        (
            "results/traffic/?topo=vertical,full_mesh&task=math#iat",
            "results/traffic-patterns/?topo=vertical,full_mesh&task=math#iat",
            RESULTS_READY,
        ),
        (
            "results/system/?task=coding#network",
            "results/system-load/?task=coding#network",
            RESULTS_READY,
        ),
        (
            f"results/runs/?task=math#run={run_id}",
            f"results/run-explorer/?task=math#run={run_id}",
            RESULTS_READY,
        ),
    ]


@case("compare", modes=("private", "public"))
def case_compare(env: Env, t: Case):
    """Compare topologies: three panels on a shared clock plus the arrivals timeline."""
    env.shots.mkdir(parents=True, exist_ok=True)
    pub = env.tree / "data" / ("private" if (env.tree / "data" / "private" / "manifest.json").is_file() else "public")
    index_path = pub / "fixtures" / "index.json"
    if not index_path.is_file():
        page, watch = env.open("playground/compare/")
        page.wait_for_function(COMPARE_READY)
        t.eq(page.evaluate("() => document.body.dataset.cmp"), "empty", "no fixtures: empty state")
        t.eq(page.locator(".cmp-panel").count(), 0, "no fixtures: no panels")
        t.no_errors(watch, 0, "compare without fixtures")
        env.close()
        return
    fixtures = json.loads(index_path.read_text())["fixtures"]
    tasks = sorted({f["task"] for f in fixtures})
    task = "math" if "math" in tasks else tasks[0]
    want = {}
    for topo in ("horizontal", "vertical", "full_mesh"):
        ent = next(f for f in fixtures if f["topology"] == topo and f["task"] == task)
        events = json.loads((index_path.parent / ent["files"]["events"]).read_text())
        want[topo] = sum(1 for e in events if e["event"] == "llm_request")

    q = f"playground/compare/?task={task}&speed=200"
    page, watch = env.open(q)
    page.wait_for_function(COMPARE_READY)
    t.eq(page.locator(".cmp-panel").count(), 3, "three panels")
    t.eq(
        page.eval_on_selector_all(".cmp-panel h3", "els => els.map((e) => e.textContent.trim())"),
        ["Sequential", "Star", "Full mesh"],
        "panel order",
    )
    t.eq(page.locator("#cmpTask option").count(), len(tasks), "task options")
    # speed 200: the replay finishes within a second or so
    page.wait_for_function("() => document.querySelectorAll('.cmp-badge.is-done').length === 3", timeout=15_000)
    got = page.eval_on_selector_all(
        ".cmp-panel [data-m=calls]", "els => els.map((e) => e.textContent.trim())"
    )
    t.eq(got, [f"{want[k]} / {want[k]}" for k in ("horizontal", "vertical", "full_mesh")], "calls")
    t.eq(
        page.eval_on_selector_all(
            "#cmpTimeline .cmp-tick", "els => els.length"
        ),
        sum(want.values()),
        "one timeline tick per LLM call",
    )
    t.eq(
        page.eval_on_selector_all(
            "#cmpStats tbody tr:first-child td", "els => els.map((e) => Number(e.textContent))"
        ),
        [want[k] for k in ("horizontal", "vertical", "full_mesh")],
        "stats table: calls",
    )
    t.eq(page.inner_text("#cmpPlay"), "Replay", "play button after the end")
    # Scrubbing back to the start clears the panels; Play runs again.
    page.fill("#cmpScrub", "0")
    page.dispatch_event("#cmpScrub", "input")
    t.eq(page.inner_text("#cmpClock").split(" s")[0], "0.0", "scrub to 0: clock")
    t.check(
        page.eval_on_selector_all("#cmpTimeline .cmp-tick", "els => els.length") <= 3,
        "scrub to 0: only the calls sent at t=0 remain",
    )
    page.click("#cmpPlay")
    page.wait_for_function("() => document.querySelectorAll('.cmp-badge.is-done').length === 3", timeout=15_000)
    # Pause stops the clock.
    page.select_option("#cmpSpeed", "1")
    page.click("#cmpRestart")
    page.click("#cmpPlay")
    clock = page.inner_text("#cmpClock")
    page.wait_for_timeout(600)
    t.eq(page.inner_text("#cmpClock"), clock, "paused clock does not move")
    t.eq(
        page.evaluate("() => document.body.dataset.cmp"), "ready", "page state"
    )
    t.eq(page.evaluate(OVERFLOW_JS), 0, "horizontal scroll at 1280")
    t.no_errors(watch, 0, "compare page")
    env.close()

    for theme in ("light", "dark"):
        for width, height in ((1280, 900), (375, 812)):
            page, watch = env.open(
                f"playground/compare/?task={task}&play=0&t=30", width, height, color_scheme=theme
            )
            page.wait_for_function(COMPARE_READY)
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"{theme} @{width}: horizontal scroll")
            t.check(
                page.eval_on_selector_all("#cmpTimeline .cmp-tick", "els => els.length") > 0,
                f"{theme} @{width}: timeline drawn",
            )
            page.screenshot(path=str(env.shots / f"compare-{theme}-{width}.png"), full_page=True)
            t.no_errors(watch, 0, f"compare {theme} @{width}")
            env.close()


@case("analysis", modes=("private", "public"))
def case_analysis(env: Env, t: Case):
    """Run analysis (playground/js/run-analysis.js): a finished replay offers a collapsed
    "Analyse this run" with the Results drill-down's charts; a cancelled run does not."""
    topos = ("horizontal", "vertical", "full_mesh")
    for theme in ("light", "dark"):
        for topology in topos if theme == "light" else ("vertical",):
            page, watch = env.open(
                f"playground/run/index.html?demo=1&speed={FAST}", color_scheme=theme
            )
            page.wait_for_selector("#demoBanner")
            page.evaluate("() => window.agentverse.loadExample('math')")
            page.select_option("#topology", topology)
            page.click("#runBtn")
            page.wait_for_function("() => document.getElementById('statusText').textContent === 'Complete'")
            what = f"{topology} ({theme})"
            t.check(page.is_visible("#runAnalysis"), f"{what}: analysis not offered")
            t.check(not page.evaluate("() => document.getElementById('runAnalysis').open"), f"{what}: not collapsed")
            t.check("Analyse this run" in text(page, "#runAnalysis summary"), f"{what}: heading")
            page.click("#runAnalysis summary")
            page.wait_for_selector("#runAnalysisBody [data-chart=run-iat] svg path")
            for chart in ("gantt", "concurrency", "metrics", "run-iat"):
                t.check(
                    page.locator(f"#runAnalysisBody [data-chart={chart}] svg").count() == 1,
                    f"{what}: {chart} chart not drawn",
                )
            t.check(page.locator("#runAnalysisBody .tile").count() >= 6, f"{what}: stat tiles")
            t.check(page.locator("#runAnalysisBody [data-chart=gantt] rect[rx]").count() > 5, f"{what}: Gantt bars")
            t.eq(page.evaluate(OVERFLOW_JS), 0, f"{what}: horizontal page scroll (px)")
            if theme == "dark":
                env.shots.mkdir(parents=True, exist_ok=True)
                page.locator("#runAnalysis").screenshot(path=str(env.shots / "analysis-dark.png"))
            t.no_errors(watch, 0, what)
            # a new run hides it again
            page.click("#runBtn")
            t.check(not page.is_visible("#runAnalysis"), f"{what}: still shown while a new run starts")
            env.close()

    page, watch = env.open("playground/run/index.html?demo=1&speed=1", 375, 812)
    page.wait_for_selector("#demoBanner")
    page.evaluate("() => window.agentverse.loadExample('math')")
    page.click("#runBtn")
    page.wait_for_function(
        "() => parseInt(document.getElementById('llmRequestCount').textContent, 10) >= 2",
        timeout=40_000,
    )
    page.click("#cancelBtn")
    page.wait_for_function("() => document.getElementById('statusText').textContent === 'Cancelled'")
    t.check(not page.is_visible("#runAnalysis"), "cancelled run: analysis offered")
    t.no_errors(watch, 0, "cancelled run")


@case("redirects")
def case_redirects(env: Env, t: Case):
    for old, new, ready in redirect_cases(env):
        what = f"redirect {old}"
        page, watch = env.open("index.html")
        page.wait_for_function(TOGGLE_READY)
        page.goto(env.base + old)
        try:
            page.wait_for_url(
                lambda u, w=env.base + new: u == w, wait_until="commit", timeout=10_000
            )
        except Exception:
            t.check(False, f"{what}: landed on {page.url}, want {env.base + new}")
            env.close()
            continue
        page.wait_for_function(ready, timeout=10_000)
        t.check("moved to" not in (page.text_content("body") or ""), f"{what}: still on the stub")
        t.no_errors(watch, 0, what)
        page.go_back()
        page.wait_for_url(lambda u: u == env.base + "index.html", timeout=10_000)
        t.eq(page.url, env.base + "index.html", f"{what}: Back skips the stub")
        env.close()


# ---------------------------------------------------------------------------
# Public data set (--data public)
# ---------------------------------------------------------------------------

MODE_JS = """async () => {
  const d = await (await import('/common/js/data.js')).getDataMode();
  return { mode: d.mode, synthetic: d.synthetic, privateAvailable: d.privateAvailable, base: d.base.pathname };
}"""
LOADED_JS = "() => document.readyState === 'complete'"


def public_pages() -> dict[str, tuple[str, str]]:
    """page -> (path, JS that is true once it has rendered)."""
    return {
        "launcher": ("index.html", TOGGLE_READY),
        "runner": ("playground/run/", TOGGLE_READY),
        "viewer": ("playground/open/", TOGGLE_READY),
        "compare": ("playground/compare/", COMPARE_READY),
        "chat": ("playground/chat/", TOGGLE_READY),
        "results": ("results/", RESULTS_READY),
        "results-traffic": ("results/traffic-patterns/", TRAFFIC_READY),
        "results-system": ("results/system-load/", LOAD_READY),
        "results-runs": ("results/run-explorer/", RESULTS_READY),
        "blog": ("docs/blog/", TOGGLE_READY),
        "agentverse-docs": ("docs/agentverse/", TOGGLE_READY),
    }


def private_requests(watch: Watch) -> list[str]:
    """Requests under /data/private/ other than the resolver's manifest probe."""
    return [
        u
        for _, u in watch.requests
        if "/data/private/" in u and not u.split("?")[0].endswith("/data/private/manifest.json")
    ]


@case("public", modes=("public",))
def case_public(env: Env, t: Case):
    """The public site (the built dist/public tree, no private data): every page loads cleanly in
    public mode, the results pages show the real aggregates, and a missing runs.json / fixtures
    breaks nothing."""
    pub = env.tree / "data" / "public"
    t.check(not (env.tree / "data" / "private").exists(), "the tree has a data/private/ directory")
    t.check(not (env.tree / "results" / "data").exists(), "the tree has the old results/data/")
    t.check(
        not (env.tree / "playground" / "fixtures").exists(), "the tree has playground/fixtures/"
    )
    t.eq(
        json.loads((pub / "manifest.json").read_text()),
        {"mode": "public", "synthetic": True},
        "public manifest",
    )
    summary = json.loads((pub / "summary.json").read_text())
    t.check("fixtures" not in summary, "the public summary has the fixtures task-id mapping")
    has_runs = (pub / "runs.json").is_file()
    has_fixtures = (pub / "fixtures" / "index.json").is_file()
    t.notes.append(f"tree has runs.json: {has_runs}, fixtures: {has_fixtures}")

    # 1. Every page: no console errors, public mode, nothing private requested.
    for name, (path, ready) in public_pages().items():
        page, watch = env.open(path)
        page.wait_for_function(ready)
        page.wait_for_load_state("networkidle")
        mode = page.evaluate(MODE_JS)
        t.eq(
            (mode["mode"], mode["synthetic"], mode["privateAvailable"]),
            ("public", True, False),
            f"{name}: data mode",
        )
        t.check(mode["base"].endswith("/data/public/"), f"{name}: data base {mode['base']}")
        t.eq(private_requests(watch), [], f"{name}: requests under /data/private/")
        t.no_errors(watch, 0, f"{name} page")
        t.eq(page.evaluate(OVERFLOW_JS), 0, f"{name}: horizontal page scroll (px)")
        if name == "runner":  # replays need fixtures; without them demo mode stays off
            t.eq(
                bool(page.locator("#demoBanner").count()),
                has_fixtures,
                "runner: demo banner (shown only with fixtures)",
            )
        env.close()

    # 2. Results pages draw from the aggregates.
    page, watch = env.open("results/")
    page.wait_for_function(RESULTS_READY)
    fills = page.evaluate(OVERVIEW_FILL_JS)
    for key, value in overview_fills(summary).items():
        t.eq(fills.get(key), value, f"Overview: {key}")
    for section, (where, selector) in RESULTS_SECTIONS.items():
        if where == "overview":
            t.check(page.locator(selector).count() > 0, f"overview: {section} rendered nothing")
    t.check(
        not any("runs.json" in u for _, u in watch.requests), "overview: runs.json fetched on open"
    )
    t.no_errors(watch, 0, "overview")
    env.close()

    page, watch = env.open("results/traffic-patterns/")
    page.wait_for_function(TRAFFIC_READY)
    for section, (where, selector) in RESULTS_SECTIONS.items():
        if where == "traffic":
            t.check(page.locator(selector).count() > 0, f"traffic: {section} rendered nothing")
    t.eq(page.locator("#burstSizes figure svg.viz").count(), 3, "traffic: burst size panels")
    t.check(page.locator("#robCharts svg").count() > 0, "traffic: robustness charts (traffic.json)")
    t.no_errors(watch, 0, "traffic")
    env.close()

    page, watch = env.open("results/system-load/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_function(LOAD_READY)
    page.wait_for_function(WORKFLOW_READY)
    for section, (where, selector) in RESULTS_SECTIONS.items():
        if where == "system" and section not in RESULTS_ASYNC:
            t.check(page.locator(selector).count() > 0, f"system: {section} rendered nothing")
    for sid, selectors in WORKFLOW_SYSTEM.items():
        for sel in selectors:
            t.check(page.locator(sel).count() > 0, f"{sid}: nothing drawn ({sel})")
    for sid in ("concurrency", "comparisons"):
        t.check(page.locator(f"#{sid} svg, #{sid} table").count() > 0, f"{sid}: nothing drawn")
    t.check(
        not any("runs.json" in u for _, u in watch.requests), "system: runs.json fetched on open"
    )
    # The scatter needs runs.json: a note without it, dots with it.
    page.click("#corrPlotBtn")
    if has_runs:
        page.wait_for_selector("#corrScatter svg circle, #corrScatter svg path")
    else:
        page.wait_for_selector("#corrScatter .placeholder:has-text('not available')")
    t.no_errors(watch, 0, "system")
    env.close()

    # The Beta page is behind the login: not in the public build, not linked from any page.
    t.check(not (env.tree / "results" / "beta").exists(), "the tree has results/beta/")
    for beta_path in ("results/beta/", "results/beta/index.html"):
        try:
            status = urllib.request.urlopen(env.base + beta_path).status
        except urllib.error.HTTPError as err:
            status = err.code
        t.eq(status, 404, f"/{beta_path} status")
    for name, (path, ready) in public_pages().items():
        page, watch = env.open(path)
        page.wait_for_function(ready)
        page.wait_for_function(NAV_READY)
        page.evaluate(MODE_JS)  # the mode has resolved, so nav.js has hidden the Beta entries
        page.click(".results-menu__button")
        labels = page.eval_on_selector_all(
            ".results-menu__label", "els => els.map((e) => e.textContent)"
        )
        t.eq(labels, RESULTS_TABS, f"{name}: Results menu entries (no Beta)")
        dead = page.eval_on_selector_all(
            "a[href]", "els => els.map((a) => a.href).filter((h) => /\\/beta\\//.test(h))"
        )
        t.eq(dead, [], f"{name}: links to the Beta page")
        if name == "results-system":
            t.eq(page.locator("#betaSignIn").count(), 0, "System load: no sign-in note")
            t.eq(page.locator(".beta-link").count(), 0, "System load: no Beta line")
        env.close()

    # 3. Run explorer: the table and the unusual runs need runs.json.
    page, watch = env.open("results/run-explorer/")
    page.wait_for_function(RESULTS_READY)
    if has_runs:
        page.wait_for_selector("#runTable table tbody tr[data-run]")
        t.eq(page.locator("#runTable .placeholder").count(), 0, "runs: unexpected note")
    else:
        page.wait_for_selector("#runTable .placeholder:has-text('not available')")
        page.wait_for_selector("#outlierBody .placeholder:has-text('not available')")
        t.eq(page.locator("#runTable table").count(), 0, "runs: table without runs.json")
    t.eq(private_requests(watch), [], "run explorer: requests under /data/private/")
    t.no_errors(watch, 0, "run explorer")
    env.close()

    # 4. Portal menu, notices, synthetic labels, deep links, replay.
    check_portal(env, t, "public")
    check_public_modes(env, t)


# ---------------------------------------------------------------------------
# Portal menu, data-mode notices (common/js/mode.js, nav.js), both modes
# ---------------------------------------------------------------------------

NOTICE_RUNS = "Individual runs, timelines and call details are synthetic, generated to match the real aggregates"
NOTICE_DEMO = "Demo: synthetic data, replayed in the browser; nothing is sent to a real backend"
PORTAL_JS = """() => {
  const b = document.querySelector('.portal-menu__button');
  const p = document.getElementById(b.getAttribute('aria-controls'));
  const r = p.getBoundingClientRect();
  const host = document.querySelector('[data-site-nav]');
  const kids = [...host.children].map((n) => (n.matches('.site-menu') ? n.querySelector('button') : n).childNodes[0].textContent.trim());
  return {
    order: kids, expanded: b.getAttribute('aria-expanded'), shown: !p.hidden && r.width > 0,
    left: r.left, right: r.right, vw: document.documentElement.clientWidth,
    groups: [...p.querySelectorAll('[data-portal-group]')].map((g) => g.dataset.portalGroup),
    signed: /Signed in: real data/.test(p.textContent),
    signin: (p.querySelector('[data-portal-link="signin"]') || {}).href || null,
    switchPressed: [...p.querySelectorAll('.mode-switch button[aria-pressed="true"]')].map((x) => x.dataset.mode),
    stored: (() => { try { return localStorage.getItem('agentraffic-endpoint'); } catch (e) { return null; } })(),
    status: (p.querySelector('.portal-menu__status') || {}).textContent,
  };
}"""


def check_portal(env: Env, t: Case, mode: str):
    """Portal menu on every page: next to Code, Connect saves the endpoint in the browser, the real-data group
    is hidden (public) or shows 'Signed in: real data' and the switch (owner's machine)."""
    for name, (path, ready) in public_pages().items():
        for width, height, theme in ((1280, 900, "light"), (375, 812, "dark")):
            what = f"portal {name} {theme} {width}"
            page, watch = env.open(path, width, height, color_scheme=theme)
            page.wait_for_function(ready, timeout=20_000)
            page.wait_for_function("() => !!document.querySelector('.portal-menu__button')")
            page.evaluate(MODE_JS)
            page.wait_for_timeout(100)
            m = page.evaluate(PORTAL_JS)
            t.eq(m["order"][-2:], ["Code", "Portal"], f"{what}: Portal comes after Code")
            t.check(not m["shown"], f"{what}: Portal menu open on load")
            page.click(".portal-menu__button")
            m = page.evaluate(PORTAL_JS)
            t.check(m["expanded"] == "true" and m["shown"], f"{what}: click did not open it")
            t.check(
                m["left"] >= 0 and m["right"] <= m["vw"],
                f"{what}: panel outside the viewport ({m['left']:.0f}-{m['right']:.0f} of {m['vw']})",
            )
            t.eq(m["groups"], ["connect", "signin"], f"{what}: groups")
            if mode == "public":
                t.check(not m["signed"], f"{what}: 'Signed in' on the public site")
                t.eq(m["signin"], "https://agentraffic-private.pages.dev/", f"{what}: Sign in link")
                t.eq(m["switchPressed"], [], f"{what}: switch on the public site")
            else:
                t.check(m["signed"], f"{what}: 'Signed in: real data' missing")
                t.eq(m["switchPressed"], ["private"], f"{what}: switch state")
            page.keyboard.press("Escape")
            t.check(not page.evaluate(PORTAL_JS)["shown"], f"{what}: Esc did not close it")
            t.no_errors(watch, 0, what)
            env.close()

    # Connect: a bad value is refused, a good one is saved in the browser and cleared again.
    page, watch = env.open("playground/run/")
    page.wait_for_function(TOGGLE_READY)
    page.click(".portal-menu__button")
    page.fill("#portalEndpoint", "ftp://nope")
    page.press("#portalEndpoint", "Enter")
    m = page.evaluate(PORTAL_JS)
    t.check(m["stored"] is None and "http" in (m["status"] or ""), "Connect: a bad URL was saved")
    page.fill("#portalEndpoint", "http://localhost:9999")
    page.press("#portalEndpoint", "Enter")
    m = page.evaluate(PORTAL_JS)
    t.eq(m["stored"], "http://localhost:9999/agentverse", "Connect: saved endpoint")
    page.reload()
    page.wait_for_function(TOGGLE_READY)
    used = page.evaluate(
        "async () => (await import('/playground/js/utils.js')).getDefaultEndpoint()"
    )
    t.eq(
        used, "http://localhost:9999/agentverse", "Connect: the playground uses the saved endpoint"
    )
    page.click(".portal-menu__button")
    page.click(".portal-menu__clear")
    t.eq(page.evaluate(PORTAL_JS)["stored"], None, "Connect: Clear")
    t.no_errors(watch, 0, "Connect")
    env.close()


@case("portal", modes=("private",))
def case_portal(env: Env, t: Case):
    """Private mode: the Portal menu shows 'Signed in: real data' and the switch; the playground
    banner keeps 'Replay of a recorded run'; badges keep 'Recorded runs'."""
    check_portal(env, t, "private")
    page, watch = env.open("playground/run/")
    page.wait_for_selector("#demoBanner")
    banner = page.inner_text("#demoBanner")
    t.check("Replay of a recorded run" in banner, "private banner lost its wording")
    t.check(NOTICE_DEMO not in banner, "private banner carries the public notice")
    t.check(
        page.locator("#demoBanner .mode-switch").count() == 1, "banner: no Real / Synthetic switch"
    )
    env.close()
    page, watch = env.open("results/run-explorer/")
    page.wait_for_function(RESULTS_READY)
    t.check(
        page.locator("[data-mode-notice]:visible").count() == 0, "private: synthetic notice shown"
    )
    t.check(
        page.locator(".badge[data-badge-kind=runs]").count() > 0,
        "private: no 'Recorded runs' badge",
    )
    page.wait_for_selector("[data-mode-switch] .mode-switch", timeout=5_000)
    t.check(page.locator("[data-mode-switch] .mode-switch").count() == 1, "results header: switch")
    page.click("[data-mode-switch] .mode-switch button[data-mode=public]")
    page.wait_for_selector(".mode-notice")
    env.close()


def check_public_modes(env: Env, t: Case):
    """Public mode: notices, synthetic labels, the #run=syn-... deep link and a synthetic replay."""
    pub = env.tree / "data" / "public"
    if not (pub / "runs.json").is_file():
        t.notes.append("no runs.json: skipped the synthetic-run checks")
        return
    runs = json.loads((pub / "runs.json").read_text())["runs"]
    rid = runs[0]["id"]
    t.check(rid.startswith("syn-") and len(rid) > 8, f"synthetic id shape: {rid}")

    # Runs page: the notice, synthetic badges, the whole id in the table and the deep link.
    page, watch = env.open("results/run-explorer/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_selector("#runTable table tbody tr[data-run]")
    page.wait_for_selector(".mode-notice")
    t.check(NOTICE_RUNS in page.inner_text("#runs"), "runs: notice missing")
    t.eq(page.locator(".badge[data-badge-kind=runs]").count(), 0, "runs: 'Recorded runs' badge")
    t.check(
        page.locator(".badge[data-badge-kind=synthetic]").count() > 0, "runs: no synthetic badge"
    )
    t.check("Synthetic illustration" in page.inner_text("#runs"), "runs: badge label")
    env.close()

    for suffix in ("", "&tzoom=100,900"):
        page, watch = env.open(f"results/run-explorer/#run={rid}{suffix}")
        page.wait_for_function(RESULTS_READY)
        page.wait_for_selector("#runDetail h3 code")
        t.eq(text(page, "#runDetail h3 code"), rid, f"deep link {suffix or 'plain'}: whole id")
        detail = page.inner_text("#runDetail")
        t.check(NOTICE_RUNS in detail, f"deep link {suffix or 'plain'}: notice in the run view")
        t.check("Synthetic illustration" in detail, "deep link: badge in the run view")
        t.check(
            "Synthetic run" in detail and "Source:" not in detail,
            "deep link: synthetic wording",
        )
        t.check(
            "recorded as" not in detail and f"task {rid}" not in detail, "deep link: old wording"
        )
        t.eq(page.locator("#runDetail .placeholder").count(), 0, "deep link: placeholder")
        t.no_errors(watch, 0, f"deep link {suffix or 'plain'}")
        env.close()

    # System page: the scatter carries the notice and the synthetic badge.
    page, watch = env.open("results/system-load/")
    page.wait_for_function(RESULTS_READY)
    page.wait_for_function(LOAD_READY)
    page.click("#corrPlotBtn")
    page.wait_for_selector("#corrScatter svg circle, #corrScatter svg path")
    page.wait_for_selector(".corr-side .mode-notice")
    t.check(
        page.locator(".corr-side .badge[data-badge-kind=synthetic]").count() == 1, "scatter: badge"
    )
    t.no_errors(watch, 0, "system scatter")
    env.close()

    # Playground: the banner says synthetic, shows the whole id, and a synthetic fixture replays.
    index = pub / "fixtures" / "index.json"
    if not index.is_file():
        t.notes.append("no fixtures: skipped the replay checks")
        return
    entry = json.loads(index.read_text())["fixtures"][0]
    page, watch = env.open(
        f"playground/run/?replay={entry['topology']}/{entry['task']}&speed={FAST}"
    )
    page.wait_for_selector("#demoBanner")
    page.wait_for_function(
        "() => document.getElementById('statusText').textContent === 'Complete'", timeout=30_000
    )
    banner = page.inner_text("#demoBanner")
    t.check(NOTICE_DEMO in banner, "runner banner: demo notice")
    t.check(
        "Replay of a recorded run" not in banner and "recorded 20" not in banner,
        "banner: recorded wording",
    )
    t.check("Synthetic run" in banner and entry["task_id"] in banner, "banner: provenance")
    t.check(page.locator("#demoBanner .portal-link").count() == 1, "banner: Portal pointer")
    t.eq(page.locator("#demoBanner .mode-switch").count(), 0, "banner: switch on the public site")
    page.click("#demoBanner .portal-link")
    t.check(page.evaluate(PORTAL_JS)["shown"], "banner Portal link did not open the menu")
    t.no_errors(watch, 0, "synthetic replay")
    env.close()

    page, watch = env.open(f"playground/open/?demo=1&task_id={entry['task_id']}")
    page.wait_for_function(VIEWER_LOADED, timeout=20_000)
    t.check(NOTICE_DEMO in page.inner_text("#demoBanner"), "viewer: demo notice")
    t.no_errors(watch, 0, "viewer")
    env.close()

    # Chat: the notice replaces "needs the local backend".
    page, watch = env.open("playground/chat/")
    page.wait_for_selector("#demoNote .mode-notice")
    t.check(NOTICE_DEMO in page.inner_text("#demoNote"), "chat: demo notice")
    t.check(not page.locator("#backendNote").is_visible(), "chat: 'needs the local backend' shown")
    t.check(page.locator("#sendBtn").is_disabled(), "chat: Send enabled without a backend")
    t.no_errors(watch, 0, "chat")
    env.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def launch(p, name: str, headed: bool) -> Browser:
    try:
        return getattr(p, name).launch(headless=not headed)
    except Exception as err:
        if name == "chromium":
            raise
        print(f"[smoke] {name} failed to launch ({err}); falling back to chromium")
        return p.chromium.launch(headless=not headed)


def main(argv: list[str] | None = None) -> int:
    names = [name for name, _ in CASES]
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--browser", choices=("firefox", "chromium"), default="firefox")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument(
        "--screenshots",
        type=Path,
        default=Path(tempfile.gettempdir()) / "agentverse-demo-smoke",
        help="where the 'screens' case writes PNGs (default: %(default)s)",
    )
    ap.add_argument(
        "--data",
        choices=("private", "public"),
        default="private",
        help="private: serve ui/ with the real data (default); public: serve the built "
        "dist/public/ tree (make dist-public) and run only the public case",
    )
    ap.add_argument("--only", nargs="+", choices=names, metavar="CASE", help="run these cases")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    args = ap.parse_args(argv)
    if args.list:
        print("\n".join(f"{n}  ({'/'.join(CASE_MODES[n])})" for n in names))
        return 0
    runnable = [n for n in names if args.data in CASE_MODES[n]]
    wrong = [n for n in args.only or [] if n not in runnable]
    if wrong:
        print(f"[smoke] case(s) {', '.join(wrong)} do not run with --data {args.data}")
        return 2
    tree = UI_DIR if args.data == "private" else PUBLIC_TREE
    if args.data == "private" and not (DATA_DIR / "manifest.json").is_file():
        print(f"[smoke] no private data in {DATA_DIR}: run `make data` (or use --data public)")
        return 2
    if args.data == "public" and not (tree / "data" / "public" / "summary.json").is_file():
        print(f"[smoke] no built public tree at {tree}: run `make dist-public` first")
        return 2
    if port_open(AGENT_A_PORT):
        print(
            f"[smoke] something is listening on :{AGENT_A_PORT}; stop it (the test needs no backend)"
        )
        return 2

    httpd = serve(tree)
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"[smoke] serving {tree} at {base} (data: {args.data})")
    results: list[Case] = []
    started = time.monotonic()
    try:
        with sync_playwright() as p:
            browser = launch(p, args.browser, args.headed)
            print(f"[smoke] {browser.browser_type.name} {browser.version}")
            env = Env(browser, base, args.screenshots, tree)
            for name, fn in CASES:
                if name not in runnable or (args.only and name not in args.only):
                    continue
                t = Case(name)
                t0 = time.monotonic()
                try:
                    fn(env, t)
                except Exception as err:  # a hard failure (e.g. a timeout) ends the case
                    # first line of the error plus where in the case it happened
                    frames = traceback.extract_tb(err.__traceback__)
                    where = next(
                        (f for f in reversed(frames) if f.filename == __file__), frames[-1]
                    )
                    t.failures.append(
                        f"{type(err).__name__}: {str(err).splitlines()[0]} "
                        f"(smoke_test.py:{where.lineno}: {where.line})"
                    )
                finally:
                    env.close()
                results.append(t)
                status = "FAIL" if t.failures else "PASS"
                print(f"{status}  {name}  ({time.monotonic() - t0:.1f}s)")
                for note in t.notes:
                    print(f"      {note}")
                for failure in t.failures:
                    print(f"   !! {failure}")
            browser.close()
    finally:
        httpd.shutdown()

    failed = [t.name for t in results if t.failures]
    total = time.monotonic() - started
    print(f"[smoke] {len(results) - len(failed)}/{len(results)} cases passed in {total:.0f}s")
    if failed:
        print(f"[smoke] failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
