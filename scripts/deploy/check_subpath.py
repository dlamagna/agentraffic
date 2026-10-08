"""Check that a static build works under a sub-path such as GitHub Pages' ``/agentraffic/``.

Usage::

    .venv/bin/python scripts/deploy/check_subpath.py [--dir dist/public] [--prefix /agentraffic/]
        [--browser chromium|firefox] [--screenshot docs/img/results.png]

Serves ``--dir`` under ``--prefix`` with a stdlib server that answers 404 for anything outside the
prefix, so a root-relative URL (``href="/x"``, ``fetch('/x')``) fails exactly as it would on
GitHub Pages. Every ``*.html`` page of the build is then opened in a headless browser with
Playwright, and the check fails on any response with status 400 or above, any console error and
any uncaught page error. Every same-origin link of every page is also requested.

One miss is expected and ignored: the probe for ``data/private/manifest.json``, which does not
exist in the public build (``ui/common/js/data.js`` treats the 404 as "public mode"). Requests to
other origins (the demo's probe of a live Agent A on :8101, which switches demo mode on) are not
the build's business and are ignored; browsers' generic "Failed to load resource" console lines are
too, because the failing URL is already reported by the response check.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

REPO = Path(__file__).resolve().parents[2]
EXPECTED_MISSES = ("data/private/manifest.json",)
#: Synthetic public data that scripts/demo/generate_synthetic.py has not produced yet: reported
#: as a warning, and as a failure with --strict.
PENDING_SYNTHETIC = ("data/public/runs.json", "data/public/fixtures/index.json")
LINK_JS = "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href)"


class SubpathHandler(http.server.SimpleHTTPRequestHandler):
    """Serve ``directory`` under ``prefix``; anything outside the prefix is a 404."""

    prefix = "/"

    def translate_path(self, path: str) -> str:
        path = urlparse(path).path
        if not path.startswith(self.prefix):
            return str(Path(self.directory) / "__outside_the_prefix__")
        return super().translate_path("/" + path[len(self.prefix) :])

    def log_message(self, *args: object) -> None:  # keep the output readable
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_server(root: Path, prefix: str) -> tuple[Server, int]:
    handler = type("Handler", (SubpathHandler,), {"prefix": prefix})
    server = Server(("127.0.0.1", 0), functools.partial(handler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def pages_of(root: Path) -> list[str]:
    """Every HTML page of the build as a path relative to the site root ('' is the home page)."""
    out = []
    for html in sorted(root.rglob("*.html")):
        rel = html.relative_to(root).as_posix()
        out.append(rel[: -len("index.html")] if rel.endswith("index.html") else rel)
    return out


def expected(url: str) -> bool:
    return any(url.endswith(miss) for miss in EXPECTED_MISSES)


def check(
    root: Path, prefix: str, browser_name: str, screenshot: Path | None, strict: bool = False
) -> int:
    from playwright.sync_api import sync_playwright

    server, port = start_server(root, prefix)
    origin = f"http://127.0.0.1:{port}"
    problems: list[str] = []
    pages = pages_of(root)
    links: dict[str, str] = {}  # link -> the page it was found on
    with sync_playwright() as pw:
        browser = getattr(pw, browser_name).launch()
        for rel in pages:
            url = f"{origin}{prefix}{rel}"
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda exc, u=url: problems.append(f"{u}: page error: {exc}"))
            page.on(
                "console",
                lambda msg, u=url: (
                    msg.type == "error"
                    and not expected(msg.location.get("url", ""))
                    and not msg.text.startswith("Failed to load resource")
                    and problems.append(f"{u}: console error: {msg.text}")
                ),
            )
            page.on(
                "response",
                lambda r, u=url: (
                    r.status >= 400
                    and not expected(r.url)
                    and f"{u}: HTTP {r.status} for {r.url}" not in problems
                    and problems.append(f"{u}: HTTP {r.status} for {r.url}")
                ),
            )
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(500)
            for href in page.evaluate(LINK_JS):
                href = urldefrag(urljoin(page.url, href))[0]
                if href.startswith(origin):
                    links.setdefault(href, url)
            if screenshot and rel == "results/":
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot))
            page.close()
        # Every same-origin link must resolve inside the prefix.
        page = browser.new_page()
        for href, found_on in sorted(links.items()):
            if not urlparse(href).path.startswith(prefix):
                problems.append(f"{found_on}: link leaves the sub-path: {href}")
                continue
            status = page.request.get(href).status
            if status >= 400:
                problems.append(f"{found_on}: link {href} answers HTTP {status}")
        browser.close()
    server.shutdown()
    warnings = (
        [] if strict else [p for p in problems if p.split(" for ")[-1].endswith(PENDING_SYNTHETIC)]
    )
    problems = [p for p in problems if p not in warnings]
    for line in warnings:
        print("WARN (synthetic data not generated yet)", line)
    for line in problems:
        print("FAIL", line)
    print(f"{len(pages)} pages and {len(links)} links checked under {prefix}: ", end="")
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default="dist/public", help="the static build to serve")
    ap.add_argument("--prefix", default="/agentraffic/", help="sub-path to serve it under")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox"])
    ap.add_argument("--strict", action="store_true", help="fail on the pending synthetic data too")
    ap.add_argument("--screenshot", type=Path, help="also save the Overview page here (PNG)")
    args = ap.parse_args(argv)
    root = (REPO / args.dir).resolve()
    if not root.is_dir():
        print(f"{root} does not exist: run 'make dist-public' first", file=sys.stderr)
        return 2
    prefix = "/" + args.prefix.strip("/") + "/"
    return check(root, prefix, args.browser, args.screenshot, args.strict)


if __name__ == "__main__":
    sys.exit(main())
