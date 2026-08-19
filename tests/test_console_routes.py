"""Every page the console builds has to be reachable from the console.

The defect this exists for: `/agent/` and `/precedent/` were built, deployed, returned 200
and were described in `README.md` as two of six pages, and neither could be reached from
anywhere on the site. `apps/web/components/Nav.tsx` listed all six and was imported by
nothing. `apps/web/components/Rail.tsx`, the one that renders on every page, listed four.

Nothing could catch it. `npx next build` emitted all six routes, the deploy check found the
output directory, the live-route check got 200 from each because it requested them by URL,
and every screenshot was taken by navigating directly. A route is only unreachable to
someone who arrives at the top of the page and looks for it, and no automated check in this
repository was doing that.

So the check is structural: enumerate the page files under `apps/web/app` and require each
one's route to appear in the rail. It cannot see a link that is styled invisible, which is a
different defect with a different test, but it fails the moment a page is added and not
linked, which is the one that happened.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps" / "web" / "app"
RAIL = REPO / "apps" / "web" / "components" / "Rail.tsx"

#: Routes that are built and deliberately not in the rail, each with its reason. An
#: exemption with no reason outlives its reason, so the reason is the value.
_NOT_IN_THE_RAIL: dict[str, str] = {
    "/": "the rail's first entry is the home route, written as / rather than as a segment",
    "/observation/[id]/": (
        "one page per observation, reached from a queue row. Twenty-five links in a side "
        "rail would be a table of contents for a table"
    ),
}


def _routes() -> list[str]:
    """Every route `next build` will emit a page for, from the file tree."""
    out: list[str] = []
    for page in sorted(APP.rglob("page.tsx")):
        rel = page.parent.relative_to(APP).as_posix()
        out.append("/" if rel == "." else f"/{rel}/")
    return out


def _rail_hrefs() -> set[str]:
    text = RAIL.read_text(encoding="utf-8")
    return set(re.findall(r'href:\s*"([^"]+)"', text))


def test_the_enumeration_finds_the_pages_this_console_has():
    """Guard against a check that passes because it compares nothing."""
    routes = _routes()
    assert len(routes) >= 6, f"only {len(routes)} routes found under {APP}: {routes}"
    assert "/" in routes


@pytest.mark.parametrize("route", _routes())
def test_every_built_route_is_reachable_from_the_rail(route: str):
    if route in _NOT_IN_THE_RAIL:
        return
    hrefs = _rail_hrefs()
    assert route in hrefs, (
        f"the console builds {route} and the side rail does not link to it, so a reader "
        f"who lands on the site cannot get there. The rail links {sorted(hrefs)}. Either "
        f"add the link or add {route!r} to _NOT_IN_THE_RAIL with the reason."
    )


def test_the_rail_does_not_link_to_a_route_that_is_not_built():
    """The other direction. A dead link in the nav is a 404 a judge finds by clicking."""
    routes = set(_routes())
    unbuilt = sorted(h for h in _rail_hrefs() if h not in routes and not h.startswith("http"))
    assert not unbuilt, f"the rail links to routes the console does not build: {unbuilt}"


def test_the_readme_page_count_is_the_number_of_reachable_pages():
    """The README says how many pages the console has, and it was right by coincidence.

    Six routes existed while four were reachable, and the sentence said six. It is still
    six, and now both readings agree. If a page is added, this fails until the sentence is
    updated, which is the point: a count in prose beside a tree that grows is a count that
    drifts.
    """
    words = {4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
    reachable = len(_rail_hrefs())
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    expected = words.get(reachable)
    assert expected, f"no word for {reachable} pages; add one"
    assert f"{expected} pages:" in readme, (
        f"the rail reaches {reachable} pages and README.md does not say "
        f"'{expected} pages:'. One of the two is wrong."
    )
