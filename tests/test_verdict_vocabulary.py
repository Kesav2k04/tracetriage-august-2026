"""Every verdict a gate script can emit must be a verdict the console can render.

This was not true. `scripts/run_gate3.py` gained `PASSED_UNGROUPED_ONLY` and
`UNMEASURABLE`, and `scripts/build_console_data.py` knew neither, so either one would have
raised `ValueError` on the console build. It stayed invisible because gate 3's pool could
only ever hold three observations, and three of three can only ever produce
NOT_ESTABLISHED. Growing the pool made `PASSED_UNGROUPED_ONLY` a live outcome: it is what
the script returns when the observation-level bound clears the threshold and the grouped
one does not, which is an ordinary thing for a few hundred correlated observations to do.

The failure would have landed after the scoring run, which is the most expensive possible
moment to discover it.

So the check is against the source rather than against a list somebody remembers to
update: the verdict strings assigned in the gate script are read out of its AST, and every
one has to reach a word the console knows. A new verdict added to the script and not to
the console fails here, before it is ever run.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.build_console_data import _KNOWN_VERDICTS, _MET, _RECEIPT_TO_CONSOLE

REPO = Path(__file__).resolve().parent.parent

#: Scripts that write a `verdict` into a receipt the console reads.
GATE_SCRIPTS = ("run_gate3.py",)


def _verdicts_assigned_in(path: Path) -> set[str]:
    """Every string literal assigned to a name or key called `verdict`.

    An AST walk rather than a regex, so a verdict mentioned in a docstring or a log line
    is not mistaken for one the script can return.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(
            node.value.value, str
        ):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "verdict":
                found.add(node.value.value)
    return found


@pytest.mark.parametrize("script", GATE_SCRIPTS)
def test_every_verdict_the_gate_can_emit_is_one_the_console_can_render(script):
    """The check that would have caught this before the scoring run, not after."""
    emitted = _verdicts_assigned_in(REPO / "scripts" / script)
    assert emitted, f"no verdict assignments found in {script}, so this test is inert"

    unrenderable = sorted(
        v for v in emitted if _RECEIPT_TO_CONSOLE.get(v, v) not in _KNOWN_VERDICTS
    )
    assert not unrenderable, (
        f"{script} can return {unrenderable}, and scripts/build_console_data.py knows "
        f"neither the word nor a mapping for it, so the console build raises on a real "
        f"result. Add each to _RECEIPT_TO_CONSOLE with the reason it means what it is "
        f"mapped to, or to _KNOWN_VERDICTS if it is genuinely a new state."
    )


def test_a_verdict_that_is_not_met_never_renders_as_met():
    """The specific way the mapping could be wrong rather than missing.

    `PASSED_UNGROUPED_ONLY` contains the substring "PASSED" and is not a pass: the plan's
    rule is to group before deciding. Mapping it to PASSED, or letting `_MET` become a
    prefix test, would publish a met gate that the receipt says is not met.
    """
    assert _RECEIPT_TO_CONSOLE["PASSED_UNGROUPED_ONLY"] == "NOT_ESTABLISHED"
    assert _RECEIPT_TO_CONSOLE["PASSED_UNGROUPED_ONLY"] not in _MET
    assert frozenset({"PASSED", "PRE_PASSED"}) == _MET, (
        "_MET has changed shape. If it is now a prefix or substring test, "
        "PASSED_UNGROUPED_ONLY is being counted as a met gate."
    )


def test_no_mapping_sends_a_receipt_word_somewhere_unknown():
    """A map whose right-hand side the console does not know is worse than no map."""
    bad = sorted(v for v in _RECEIPT_TO_CONSOLE.values() if v not in _KNOWN_VERDICTS)
    assert not bad, f"_RECEIPT_TO_CONSOLE maps onto unknown console verdicts: {bad}"


def test_the_typescript_union_covers_every_console_verdict():
    """The console's four words are also a TypeScript type, and it drifts separately.

    `apps/web/lib/format.ts` declares the union and `verdictColour` switches on it. A
    console verdict missing from the union is a build error at best and a default-coloured
    gate at worst, which is how a met gate once drew in the ink for one that could not be
    measured.
    """
    src = (REPO / "apps" / "web" / "lib" / "format.ts").read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if ln.startswith("export type Verdict"))
    declared = {part.strip().strip('";') for part in line.split("=", 1)[1].split("|")}
    # PRE_PASSED and OPEN are handled by verdictColour's own cases rather than the union.
    handled = declared | {v for v in ("PRE_PASSED", "OPEN") if f'case "{v}"' in src}
    missing = sorted(_KNOWN_VERDICTS - handled)
    assert not missing, (
        f"apps/web/lib/format.ts neither declares nor colours {missing}, so the console "
        f"would render them on the default branch"
    )
