"""Every public number must come from a generated artifact, not a keyboard.

This file is a SCAFFOLD. Bob owns the real implementation (task D2).

The contract it enforces: for each row in docs/CLAIM_REGISTER.md, the value
quoted in README.md must equal the value in the artifact the row points at.
When a model improves and the README is updated by hand but the artifact is not
regenerated, this test is what catches it.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_readme_has_no_unbacked_numbers():
    """Until the claim register is populated, every metric must read [UNMEASURED].

    This is deliberately strict. It fails the moment someone types a real number
    into the results table without adding its receipt, which is exactly the
    failure mode `docs/CLAIM_REGISTER.md` exists to prevent.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    table = re.search(
        r"## Measured results(.*?)(?=\n## )", readme, re.S
    )
    assert table, "README lost its Measured results section"

    register = REPO / "docs" / "CLAIM_REGISTER.md"
    registered = register.read_text(encoding="utf-8") if register.exists() else ""

    for line in table.group(1).splitlines():
        if not line.strip().startswith("|") or line.strip().startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in ("Metric", ""):
            continue
        value = cells[1].strip("`")
        if value == "[UNMEASURED]":
            continue
        assert cells[0] in registered, (
            f"README quotes {cells[0]!r} = {value!r} but that metric has no row in "
            f"docs/CLAIM_REGISTER.md. Generate the receipt or revert the number."
        )


@pytest.mark.xfail(reason="Bob implements this in task D2", strict=False)
def test_every_registered_claim_matches_its_artifact():
    raise NotImplementedError("task D2: parse CLAIM_REGISTER.md, load each artifact, compare")
