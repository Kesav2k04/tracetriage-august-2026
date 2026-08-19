"""The deploy configuration has to sit in the directory the host builds from.

The defect this exists for: `vercel.json` lived at `apps/web/vercel.json` while the
project's root directory was the repository root. Vercel therefore never read it. Eleven
consecutive production deployments reported READY, each finishing in under 300ms with no
install step and no build step, and the production domain answered 404 to every request.
The console had never been live, and nothing in the repository could tell you that,
because the file that was wrong was syntactically perfect and in a plausible place.

Two claims were silently false for the whole of that period. The console was reachable,
and the security headers in that file were being served. Neither was true, and both are
the kind of claim a reader checks by opening the site rather than by reading a test, which
is exactly why the test is here: the failure is invisible from inside the repository.

These assertions are cheap and they pin the one relationship that matters, that the
output directory named in the deploy contract is the directory the build actually writes.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _tracked_vercel_configs() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*vercel.json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(p for p in out.stdout.split("\n") if p.strip())


def test_exactly_one_vercel_config_and_it_is_at_the_root():
    """A second copy in a subdirectory is dead config that reads as live."""
    configs = _tracked_vercel_configs()
    assert configs == ["vercel.json"], (
        f"tracked vercel configs are {configs}. Vercel reads exactly one, the one in the "
        "project's root directory. Any other copy is a file a reader will believe and the "
        "host will ignore, which is how the headers in this project went unserved for "
        "eleven deployments."
    )


def test_the_output_directory_is_the_one_the_build_writes():
    """`outputDirectory` and `next.config.mjs` have to agree about where the export lands.

    Next writes the static export to `<app>/out` when `output: "export"` is set. If the
    deploy contract names any other directory the deployment succeeds and serves nothing,
    which is not a failure any build log reports as one.
    """
    cfg = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    assert cfg["outputDirectory"] == "apps/web/out", cfg["outputDirectory"]

    next_config = (REPO / "apps/web/next.config.mjs").read_text(encoding="utf-8")
    assert re.search(r'output:\s*"export"', next_config), (
        "next.config.mjs no longer exports statically, so apps/web/out is not what the "
        "build writes and vercel.json's outputDirectory is now wrong."
    )

    build = cfg["buildCommand"]
    assert "apps/web" in build and "npm run build" in build, build
    install = cfg["installCommand"]
    assert "apps/web" in install and "npm ci" in install, install


def test_trailing_slash_agrees_between_the_host_and_the_framework():
    """Disagreement here is a redirect loop or a 404 on every nested route."""
    cfg = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    next_config = (REPO / "apps/web/next.config.mjs").read_text(encoding="utf-8")
    next_trailing = bool(re.search(r"trailingSlash:\s*true", next_config))
    assert cfg["trailingSlash"] is next_trailing, (
        f"vercel.json says trailingSlash={cfg['trailingSlash']} and next.config.mjs says "
        f"{next_trailing}. The export writes one file layout and the host would look for "
        "the other."
    )


def test_the_security_headers_survived_the_move():
    """The headers were the collateral damage of the misplaced file, so pin them."""
    cfg = json.loads((REPO / "vercel.json").read_text(encoding="utf-8"))
    all_paths = [h for h in cfg["headers"] if h["source"] == "/(.*)"]
    assert len(all_paths) == 1, "no site-wide header block"
    keys = {h["key"] for h in all_paths[0]["headers"]}
    for required in (
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
        "Strict-Transport-Security",
    ):
        assert required in keys, f"{required} is no longer served site-wide"

    csp = next(
        h["value"] for h in all_paths[0]["headers"] if h["key"] == "Content-Security-Policy"
    )
    # The console holds no credential and talks to nothing, so these are the two
    # directives whose loosening would mean the read-only claim had changed.
    assert "connect-src 'self'" in csp, csp
    assert "object-src 'none'" in csp, csp
