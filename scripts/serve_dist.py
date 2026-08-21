"""Serve a built console the way a host serves it, which means compressed.

    .venv/Scripts/python.exe scripts/serve_dist.py apps/web/out 8201

`http.server` sends every file raw. On this site that inflates the JavaScript about
three times, so a run against it measures a transfer that will never happen and points
the optimisation at whichever file happens to be largest uncompressed. The same trap
caught a previous measurement on another project: an uncompressed static server made the
biggest bundle look like the problem and the fix went into the wrong file.

So this negotiates `Accept-Encoding` and sends gzip for the text types, with the length
of what it actually wrote. Nothing else: no caching headers, no range support, no HTTP/2.
A probe wants one thing from a server, which is that the bytes on the wire are the bytes a
reader would receive.
"""

from __future__ import annotations

import functools
import gzip
import http.server
import mimetypes
import socketserver
import sys
from pathlib import Path

#: Compressed on the way out. Everything else is already a compressed stream (PNG,
#: WebP, MP4, WOFF2) and gzipping it costs CPU for under a percent.
COMPRESS = {
    "text/html",
    "text/css",
    "text/plain",
    "text/markdown",
    "application/javascript",
    "text/javascript",
    "application/json",
    "image/svg+xml",
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802  (the base class names it)
        path = self.translate_path(self.path)
        target = Path(path)
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self.send_error(404, f"not built: {self.path}")
            return

        payload = target.read_bytes()
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        compressed = kind in COMPRESS and accepts_gzip
        if compressed:
            # mtime=0 so the same input gives the same bytes, which matters when a
            # harness diffs two runs and wants the difference to be the page.
            payload = gzip.compress(payload, compresslevel=6, mtime=0)

        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        """Silent. A probe's output is the measurement, not a request log."""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        raise SystemExit(f"usage: {Path(__file__).name} <directory> <port>")
    root, port = Path(args[0]).resolve(), int(args[1])
    if not (root / "index.html").is_file():
        raise SystemExit(
            f"{root} has no index.html, so it is not a built console. Run "
            f"`npm run build` in apps/web first. Serving an empty directory would "
            f"give a probe 404s that read as a broken page rather than a missing build."
        )
    handler = functools.partial(Handler, directory=str(root))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), handler) as httpd:
        print(f"serving {root} on http://127.0.0.1:{port} with gzip", flush=True)
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
