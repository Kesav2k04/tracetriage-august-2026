"""The console installs to a home screen, and works with the network gone.

Four defects this was written against. The first three are real and were in the tree; the
fourth is the one the receipt check exists to prevent.

* The manifest shipped a shortcut to ``/queue/``. There is no such route. The queue is the
  landing page, ``/``, and the rail calls it Queue, which is where the wrong URL came from.
  A manifest shortcut that 404s is worse than no shortcut, because it only appears once the
  reader has installed the thing and long-pressed the icon.
* ``apps/web/public/sw.js`` precaches a list of documents. Nothing connected that list to
  the rail, so a page added to the console would have been reachable, deployed, and the one
  page that stopped working on a train.
* iOS reads ``apple-touch-icon`` at 180 and ignores a maskable icon entirely, so the
  manifest's Android set is not enough on its own. Four files, one of them for one platform.
* A receipt saying eight of eight pages work offline stays green forever after a ninth page
  is added. So the receipt is checked against the rail rather than against itself.

Which of these tests can run anywhere. All but the last two read tracked files and run on a
fresh clone. The two that parse ``apps/web/out`` skip with a reason when that directory is
absent, the same arrangement as ``tests/test_console_accessibility.py``: a check that
silently becomes a no-op is worse than no check.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "apps" / "web"
PUBLIC = WEB / "public"
OUT = WEB / "out"
APP = WEB / "app"
RAIL = WEB / "components" / "Rail.tsx"
MANIFEST = PUBLIC / "manifest.webmanifest"
WORKER = PUBLIC / "sw.js"
RECEIPT = REPO / "artifacts" / "OFFLINE_RECEIPT.json"

#: A route the worker holds that is not a page of the console: the fallback it serves when
#: a document is asked for, the network is gone and the cache does not have it.
_FALLBACK = "/offline.html"


def _rail_routes() -> set[str]:
    """The hrefs in the rail's LINKS array, which is what a reader can reach."""
    source = RAIL.read_text(encoding="utf-8")
    block = source.split("const LINKS", 1)[1].split("];", 1)[0]
    return set(re.findall(r'href:\s*"([^"]+)"', block))


def _built_routes() -> set[str]:
    """Every route the app builds, read from the page files rather than from the output.

    Same source as `tests/test_console_routes.py`, and for the same reason: the sources are
    tracked and `out/` is not.
    """
    routes = set()
    for page in APP.rglob("page.tsx"):
        rel = page.relative_to(APP).parent.as_posix()
        routes.add("/" if rel == "." else f"/{rel}/")
    return routes


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _worker_documents() -> list[str]:
    """The worker's precache list, parsed out of its DOCUMENTS array."""
    source = WORKER.read_text(encoding="utf-8")
    block = source.split("const DOCUMENTS", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', block)


def _pages() -> list[Path]:
    if not OUT.is_dir():
        return []
    return [p for p in sorted(OUT.rglob("index.html")) if p.is_file()]


def test_the_manifest_declares_what_an_install_prompt_needs() -> None:
    manifest = _manifest()
    for field in ("name", "short_name", "start_url", "scope", "display", "icons"):
        assert manifest.get(field), f"manifest has no {field}"
    assert manifest["display"] == "standalone"
    # Chrome will not offer an install without a 192 and a 512, and Android's adaptive
    # launcher crops any icon that is not declared maskable.
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes, sizes
    purposes = {icon.get("purpose") for icon in manifest["icons"]}
    assert "maskable" in purposes, "no maskable icon, so Android will crop the mark"


def test_every_icon_the_manifest_names_is_on_disk() -> None:
    missing = [
        icon["src"]
        for icon in _manifest()["icons"]
        if not (PUBLIC / icon["src"].lstrip("/")).is_file()
    ]
    assert not missing, f"manifest names icons that do not exist: {missing}"


def test_ios_has_its_own_icon_and_the_layout_points_at_it() -> None:
    """iOS ignores the manifest's maskable variant and reads `apple-touch-icon` at 180."""
    apple = PUBLIC / "icons" / "apple-touch-icon.png"
    assert apple.is_file(), "no apple-touch-icon.png, so an iOS install gets a screenshot"
    layout = (APP / "layout.tsx").read_text(encoding="utf-8")
    assert "apple-touch-icon.png" in layout
    assert "appleWebApp" in layout, "without appleWebApp.capable an install opens in Safari"


def _dead_shortcuts(manifest: dict, routes: set[str]) -> list[str]:
    return [s["url"] for s in manifest.get("shortcuts", []) if s["url"] not in routes]


def _not_precached(rail: set[str], documents: set[str]) -> list[str]:
    return sorted(rail - documents)


def test_every_manifest_shortcut_is_a_route_the_console_builds() -> None:
    bad = _dead_shortcuts(_manifest(), _built_routes())
    assert not bad, f"manifest shortcuts point at routes that do not exist: {bad}"


def test_the_shortcut_check_fires_on_the_manifest_as_it_was_first_written() -> None:
    """The defect, restored as a fixture rather than described.

    The shipped manifest pointed its first shortcut at `/queue/` because the rail calls the
    landing page Queue. This and the check above call the same function, so a rewrite that
    made the real one vacuous would take this one with it.
    """
    routes = _built_routes()
    assert "/queue/" not in routes, "the fixture is only a defect while /queue/ is not real"
    as_written = {"shortcuts": [{"url": "/queue/"}, {"url": "/live/"}]}
    assert _dead_shortcuts(as_written, routes) == ["/queue/"]


def test_the_worker_precaches_every_page_in_the_rail() -> None:
    documents = set(_worker_documents())
    missing = set(_not_precached(_rail_routes(), documents))
    assert not missing, (
        f"pages in the rail that the worker does not precache: {sorted(missing)}. "
        "They will not open offline."
    )
    assert _FALLBACK in documents, "the fallback page itself has to be precached"
    unknown = documents - _rail_routes() - {_FALLBACK}
    assert not unknown, f"the worker precaches paths that are not routes: {sorted(unknown)}"


def test_the_precache_check_fires_on_a_rail_page_the_worker_does_not_hold() -> None:
    """The failure this is really guarding: a page ships, is reachable, and is the one page
    that stops working with no network. It cannot be provoked by editing the real files
    without editing the thing under test, so it is provoked on a copy of them."""
    rail = _rail_routes() | {"/operators/"}
    documents = set(_worker_documents())
    assert _not_precached(rail, documents) == ["/operators/"]
    assert _not_precached(_rail_routes(), documents) == []


def test_the_worker_leaves_the_measurement_endpoint_alone() -> None:
    """A cached measurement would be a measurement attributed to a run nobody made."""
    source = WORKER.read_text(encoding="utf-8")
    assert 'url.pathname.startsWith("/api/")' in source
    assert 'request.method !== "GET"' in source


def test_the_icons_are_the_mark_they_claim_to_be() -> None:
    pytest.importorskip("PIL", reason="Pillow renders the icons; not a test dependency")
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "build_pwa_icons.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_offline_receipt_covers_every_page_in_the_rail() -> None:
    """The staleness check. A ninth page must not inherit an eight-page pass."""
    assert RECEIPT.is_file(), "no OFFLINE_RECEIPT.json; run apps/web/audit/offline-probe.mjs"
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    measured = {doc["path"] for doc in receipt["documents"]}
    missing = _rail_routes() - measured
    assert not missing, (
        f"the offline receipt does not cover {sorted(missing)}. Re-run "
        "apps/web/audit/offline-probe.mjs --receipt against a fresh build."
    )
    failed = [doc["path"] for doc in receipt["documents"] if not doc["offline_ok"]]
    assert not failed, f"pages measured as broken offline: {failed}"
    # The font count is the property that fails silently: the pages render, in Times.
    for doc in receipt["documents"]:
        assert all(doc["self_hosted_faces_held"]), f"{doc['path']} lost its own fonts offline"
    assert receipt["uncached_page_gets_fallback"] is True
    assert receipt["verdict"]["clean"] is True


def test_the_built_pages_register_the_worker_and_link_the_manifest() -> None:
    pages = _pages()
    if not pages:
        pytest.skip("apps/web/out is absent; run npm run build in apps/web")
    without_worker = []
    without_manifest = []
    for page in pages:
        html = page.read_text(encoding="utf-8", errors="replace")
        if "serviceWorker.register" not in html:
            without_worker.append(page.relative_to(OUT).as_posix())
        if 'rel="manifest"' not in html:
            without_manifest.append(page.relative_to(OUT).as_posix())
    assert not without_worker, f"pages that do not register the worker: {without_worker[:5]}"
    assert not without_manifest, f"pages with no manifest link: {without_manifest[:5]}"


def test_the_export_ships_the_worker_and_the_fallback() -> None:
    if not OUT.is_dir():
        pytest.skip("apps/web/out is absent; run npm run build in apps/web")
    for name in ("sw.js", "offline.html", "manifest.webmanifest"):
        assert (OUT / name).is_file(), f"{name} is not in the export a deployment serves"
