"""Every rendered colour pair meets its WCAG floor, recomputed from the tokens.

The neutrals carry a deep plum cast expressed in OKLCH at Carbon's own lightness
values, on the claim that the tint costs no contrast. This is what makes that claim
falsifiable: it reads `apps/web/app/globals.css`, recomputes all 26 pairs, and fails
if any drops under its floor. Picking a nicer colour by eye now fails the suite instead
of an audit.

This docstring said "deep indigo" until a review found it, and it had been wrong through
two palettes: indigo at hue 264, then warm graphite at hue 70, now plum at hue 305. A
test that describes a palette the stylesheet abandoned is worse than an undocumented
one, because a reader checking whether the claim is current stops here and believes it.
The cast is named in one place, `globals.css`, and every other mention of it is a copy
that can rot; this one is kept because a test that says only "recomputes the pairs" does
not say what would make the recomputation matter.
"""

from __future__ import annotations

import pytest

from scripts.check_contrast import CSS, PAIRS, contrast, evaluate, read_tokens


@pytest.fixture(scope="module")
def tokens() -> dict[str, str]:
    return read_tokens(CSS.read_text(encoding="utf-8"))


def test_every_pair_meets_its_floor(tokens):
    failures = [
        f"{fg} on {bg}: {ratio:.2f} < {floor}"
        for fg, bg, ratio, floor, ok, _ in evaluate(tokens)
        if not ok
    ]
    assert not failures, "\n".join(failures)


def test_body_text_is_comfortably_above_the_floor(tokens):
    """The pair a reader spends the most time on should not be a near miss."""
    assert contrast(tokens["text-01"], tokens["ui-background"]) > 12.0


def test_the_smallest_text_still_clears_aa_on_a_tile(tokens):
    """--text-03 on --ui-01 is the tightest real text pair on the console."""
    assert contrast(tokens["text-03"], tokens["ui-01"]) >= 4.5


def test_the_check_can_fail(tokens):
    """A check that cannot fail is not a check."""
    broken = dict(tokens)
    broken["text-03"] = broken["ui-01"]
    assert contrast(broken["text-03"], broken["ui-01"]) == pytest.approx(1.0)
    assert any(not ok for *_, ok, _ in evaluate(broken))


def test_verdict_colours_are_four_distinct_values(tokens):
    """Four gate states, four colours. Two that collided would merge two verdicts."""
    verdicts = {
        k: v for k, v in tokens.items() if k.startswith("verdict-")
    }
    assert len(verdicts) == 4, sorted(verdicts)
    assert len(set(verdicts.values())) == 4, verdicts


def test_not_established_is_not_amber(tokens):
    """C7 removed amber from this state on two published standards. It stays out.

    Carbon assigns grey to unknown or pending states, and NASA's Appendix F display
    standard reserves yellow for CAUTION, which is a claim about the subject rather
    than about the measurement. NOT_ESTABLISHED says the interval contained the
    threshold, which is neither.
    """
    ne = tokens["verdict-not-established"].lstrip("#")
    r, g, b = (int(ne[i : i + 2], 16) for i in (0, 2, 4))
    # Amber and yellow have a large red-minus-blue gap. Grey does not.
    assert r - b < 24, f"--verdict-not-established {tokens['verdict-not-established']} reads warm"


def test_every_pair_names_a_token_that_exists(tokens):
    for fg, bg, _, _ in PAIRS:
        assert fg in tokens, fg
        assert bg in tokens, bg
