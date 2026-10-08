"""Serve a directory over HTTP with ``Cache-Control: no-store`` (stdlib only).

Usage::

    python scripts/demo/serve.py [DIR] [--port 8080] [--bind 127.0.0.1]

``make local`` serves ``ui/`` with it, ``make public`` serves ``dist/public/``. The plain
``python -m http.server`` lets the browser cache the data files, so a regenerated
``ui/data/`` can look stale; ``no-store`` avoids that.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def make_server(directory: Path, port: int = 8080, bind: str = "127.0.0.1") -> Server:
    handler = functools.partial(Handler, directory=str(directory))
    return Server((bind, port), handler)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", nargs="?", type=Path, default=REPO / "ui", help="directory to serve")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args(argv)
    if not args.dir.is_dir():
        print(f"error: {args.dir} is not a directory")
        return 2
    try:
        httpd = make_server(args.dir, args.port, args.bind)
    except OSError as exc:
        print(f"error: cannot listen on {args.bind}:{args.port}: {exc}")
        return 2
    print(f"serving {args.dir} at http://{args.bind}:{httpd.server_address[1]}/ (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
