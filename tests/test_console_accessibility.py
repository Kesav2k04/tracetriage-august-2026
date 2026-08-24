"""Keyboard reachability and accessible names, measured on the HTML a judge loads.

What this exists for. The palette is derived with checked contrast ratios by
`scripts/derive_palette.py --check`, and until this file was written that was the only
accessibility property in the repository that anything measured. Colour is the one a
generator can get right by construction; the ones that break under editing are whether a
control can be reached without a mouse and whether it says what it is when it is reached.
The gap was worth closing with a check rather than an assertion.

Two defects it was written against, both real and both fixed in the same commit:

* `apps/web/components/ui.tsx` wrapped every table in a bare ``overflow-x: auto`` div.
  Every ``th`` and ``td`` sets ``white-space: nowrap``, so those tables overflow as the
  normal case, and two of the tables on the observation page contain no focusable child at
  all. The columns past the fold were mouse-only. The worst was the provenance table, whose
  most interesting cell is a 64-character SHA-256.
* Two markers in the queue explained themselves with a ``title`` and nothing else, which a
  keyboard user never sees and a screen reader reads as a bare "≥".

Why it parses the built output rather than the sources. The sources are TSX and a regex over
them measures what was typed, which is how `tests/test_console_routes.py` has to work
because it is asking which routes exist. This is asking what the browser receives, and the
answer to that lives in `apps/web/out`. That directory is `next build` output and is not
tracked, so when it is absent the two tests that read it skip with the reason rather than
passing quietly: a check that silently becomes a no-op on a fresh clone is worse than no
check, because it reports green from an empty room. The third test reads `globals.css`,
which is tracked, so it runs everywhere and the skip does not cover it.
"""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "apps" / "web" / "out"
GLOBALS_CSS = REPO / "apps" / "web" / "app" / "globals.css"

#: Every page the export writes, which is 34 files: the eight routes in the rail plus one
#: per shipped observation card. All 25 of the latter are parsed rather than one, because two
#: of the defects this pins are data dependent: the "no waterfall shipped" span only renders
#: for rows whose observation has no image, and the offset-bound marker only for a fit that
#: ran into its bound.
#:
#: It was two page types until 2026-08-24, scoped that way because the review that prompted
#: this file looked at the queue and one observation. The scope outlived its reason: /agent/,
#: /live/ and /precedent/ had no accessible-name coverage at all while this file reported
#: clean, which is the same shape as a leakage check whose exemption hid twelve real
#: violations. Widening it is cheap, and what it found is in the commit that widened it.
def _pages() -> list[Path]:
    if not OUT.is_dir():
        return []
    pages = sorted(OUT.rglob("index.html"))
    # 404.html is written by the export as well, and it is not a route a reader navigates to
    # by choice. It is checked, because a reader who mistyped a URL still needs the rail.
    not_found = OUT / "404.html"
    if not_found.is_file():
        pages.append(not_found)
    return [p for p in pages if p.is_file()]


#: Elements a keyboard user lands on and that therefore have to announce something. `a`
#: without an href is not one of them and neither is a disabled control, so both are
#: filtered where they are collected rather than here.
_INTERACTIVE = frozenset({"a", "button", "input", "select", "textarea", "summary"})

#: Input types that are not controls a user names: a hidden input is not focusable, and a
#: submit or a button carries its name in `value`, which is checked separately.
_UNNAMED_INPUT_TYPES = frozenset({"hidden"})

#: Pages that ship no `table` at all, each with the reason it has none.
#:
#: A closed list rather than a skip-if-empty, and the difference is the whole point. The table
#: check asserts that it parsed at least one table, because a check that silently measures
#: nothing is worse than no check. Widening this file from two page types to all 34 turned that
#: guard into three failures on pages that legitimately have no table, which is a missing
#: precondition and not a defect. Naming them keeps both outcomes: a page here is omitted with
#: its reason printed, and a page that loses the tables it does have fails instead of
#: disappearing into the same silence.
_NO_TABLE: dict[str, str] = {
    "live/index.html": (
        "one input, one button and a card list. Its measurement panel is built by "
        "components/LiveConsole.tsx, which renders no table in any state"
    ),
    "404/index.html": "app/not-found.tsx is a heading and a list of routes",
    "404.html": "the same not-found page, written again at the root by the static export",
}


class _Collector(HTMLParser):
    """One pass over a page, gathering what the two assertions need.

    Written against the parser in the standard library rather than a dependency, because
    the console has to build and be checkable with the network refused, and adding a
    parser to `pyproject.toml` for this would put a wheel between a judge and a run.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict[str, str]]] = []
        #: Every id in the document, so an aria-labelledby can be resolved rather than
        #: trusted. A name that points at an element that does not exist is not a name.
        self.ids: set[str] = set()
        #: label[for] targets, which is how the waterfall viewer names its five controls.
        self.label_targets: set[str] = set()
        #: (tag, attrs, ancestors) per interactive element, plus the text inside it.
        self.controls: list[tuple[str, dict[str, str], list[str], list[str]]] = []
        self._open_controls: list[int] = []
        #: One entry per table: the tags and attrs of its ancestors, outermost first.
        self.tables: list[list[tuple[str, dict[str, str]]]] = []

    # Void elements never close, so the stack has to drop them itself.
    _VOID = frozenset(
        {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
         "param", "source", "track", "wbr"}
    )

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "label" and a.get("for"):
            self.label_targets.add(a["for"])
        if tag == "table":
            self.tables.append(list(self.stack))
        if tag in _INTERACTIVE:
            ancestors = [t for t, _ in self.stack]
            self.controls.append((tag, a, ancestors, []))
            if tag not in self._VOID:
                self._open_controls.append(len(self.controls) - 1)
        if tag not in self._VOID:
            self.stack.append((tag, a))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self._VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        if self._open_controls and self.controls[self._open_controls[-1]][0] == tag:
            self._open_controls.pop()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        # Text counts for every control it is inside, not only the innermost: a button
        # whose label sits in a nested span is named by it.
        for i in self._open_controls:
            self.controls[i][3].append(data)


def _parsed(page: Path) -> _Collector:
    c = _Collector()
    c.feed(page.read_text(encoding="utf-8", errors="replace"))
    return c


def _relative(page: Path) -> str:
    return page.relative_to(OUT).as_posix()


#: Applied per test rather than to the module. Two of the three tests read built HTML and
#: cannot run without it; the third reads `globals.css`, which is tracked, so a module-wide
#: skip took the one check a fresh clone could have made and made it a no-op as well.
_NEEDS_THE_BUILD = pytest.mark.skipif(
    not _pages(),
    reason=(
        "apps/web/out is next build output and is not tracked. Run "
        "`npm run build` in apps/web to measure this."
    ),
)


@_NEEDS_THE_BUILD
@pytest.mark.parametrize("page", _pages(), ids=_relative)
def test_every_table_sits_in_a_focusable_named_scroll_region(page: Path) -> None:
    """A table that overflows must be scrollable without a mouse.

    The check is on the ancestor rather than on the table, because the element that
    scrolls is the wrapper. Requiring a name as well as a tab stop is deliberate: a bare
    ``tabindex`` adds a stop that announces "group" or nothing at all, which trades one
    defect for a smaller one.
    """
    parsed = _parsed(page)
    if not parsed.tables:
        reason = _NO_TABLE.get(_relative(page))
        assert reason, (
            f"{_relative(page)} parsed to zero tables and is not on the _NO_TABLE list, so "
            "either it lost a table or the list needs a new entry with its reason"
        )
        pytest.skip(f"no table on this page: {reason}")

    for i, ancestors in enumerate(parsed.tables):
        scrollers = [
            attrs
            for tag, attrs in ancestors
            if attrs.get("tabindex") == "0" and attrs.get("role") == "region"
        ]
        assert scrollers, (
            f"{_relative(page)}: table {i} has no focusable named scroll region above it. "
            "Every th and td sets white-space: nowrap, so it overflows, and without a tab "
            "stop on the scroll container its right-hand columns are mouse-only."
        )
        assert any(s.get("aria-label", "").strip() for s in scrollers), (
            f"{_relative(page)}: table {i} sits in a focusable region with no accessible "
            "name, so the extra tab stop announces nothing"
        )


@_NEEDS_THE_BUILD
@pytest.mark.parametrize("page", _pages(), ids=_relative)
def test_every_control_has_an_accessible_name(page: Path) -> None:
    """Every focusable control says what it is.

    Sources of a name, in the order the browser considers them: aria-labelledby resolved
    against the ids actually in the document, aria-label, an associated or wrapping label,
    the control's own text, then title. Anything inside an aria-hidden subtree is not
    reachable and is not required to have one.
    """
    parsed = _parsed(page)
    assert parsed.controls, f"{_relative(page)} parsed to zero controls"

    unnamed: list[str] = []
    for tag, attrs, ancestors, chunks in parsed.controls:
        if tag == "a" and not attrs.get("href"):
            continue
        if "disabled" in attrs:
            continue
        if tag == "input" and attrs.get("type", "text") in _UNNAMED_INPUT_TYPES:
            continue
        if attrs.get("aria-hidden") == "true":
            continue

        labelledby = attrs.get("aria-labelledby", "").split()
        named = (
            (labelledby and all(ref in parsed.ids for ref in labelledby))
            or bool(attrs.get("aria-label", "").strip())
            or bool(attrs.get("title", "").strip())
            or bool("".join(chunks).strip())
            or bool(attrs.get("value", "").strip())
            or (attrs.get("id", "") in parsed.label_targets)
            or "label" in ancestors
        )
        if not named:
            shown = " ".join(f'{k}="{v}"' for k, v in sorted(attrs.items()))[:120]
            unnamed.append(f"<{tag} {shown}>")

    assert not unnamed, (
        f"{_relative(page)} has {len(unnamed)} control(s) a screen reader announces as "
        "nothing:\n  " + "\n  ".join(unnamed)
    )


def test_the_shared_focus_treatment_covers_every_focusable_element() -> None:
    """The one focus rule has to name every element that can take focus.

    It said "one focus treatment everywhere" in its own comment and omitted textarea,
    which was harmless only because the single textarea on the site happened to be caught
    by a more specific rule. The next one added would have had no ring at all.
    """
    css = GLOBALS_CSS.read_text(encoding="utf-8")
    selector = next(
        (
            line
            for line in css.splitlines()
            if ":focus-visible" in line and line.strip().startswith(":where(")
        ),
        None,
    )
    assert selector is not None, "the shared :focus-visible rule is gone"
    for element in ("a", "button", "[tabindex]", "input", "select", "summary", "textarea"):
        assert element in selector, (
            f"the shared focus treatment does not cover {element}: {selector.strip()}"
        )
