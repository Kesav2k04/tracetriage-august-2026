"""The console publishes a sha256 for every receipt, and now something checks them.

`apps/web/public/data/provenance.json` lists 41 receipts with a digest each, and
`/provenance` renders the table. Nothing compared a published digest against the file it
names, so a receipt regenerated after the console build kept its old digest on a public
page. Four were in exactly that state when this test was written: the three the release
audit rewrites and the sign-off's own receipt.

Those four are a fixed point rather than an ordering mistake. Each records the commit it
was measured at, `scripts/signoff.py` writes them after the console payload exists, and no
commit can record its own hash. They are marked in the payload and named here. Everything
else has to match, and the count of everything else is asserted so the exemption cannot
grow to cover a real drift.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROVENANCE = REPO / "apps" / "web" / "public" / "data" / "provenance.json"
ARTIFACTS = REPO / "artifacts"


def _load(name: str):
    """Import a script by path. `scripts/` is not a package."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def published() -> list[dict]:
    payload = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    return payload["receipts"]


@pytest.fixture(scope="module")
def note() -> str:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))["receipts_note"]


def test_every_unmarked_published_digest_is_the_digest_of_its_file(published: list[dict]) -> None:
    wrong: list[str] = []
    checked = 0
    for row in published:
        if row["rewritten_after_this_payload"]:
            continue
        path = ARTIFACTS / row["name"]
        if not path.exists():
            wrong.append(f"{row['name']}: published but absent from artifacts/")
            continue
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != row["sha256"]:
            wrong.append(f"{row['name']}: file is {got[:12]}, page says {row['sha256'][:12]}")
        elif path.stat().st_size != row["bytes"]:
            wrong.append(f"{row['name']}: {path.stat().st_size} bytes, page says {row['bytes']}")
        else:
            checked += 1
    assert not wrong, (
        "the console publishes a digest that is not the file's:\n  "
        + "\n  ".join(wrong)
        + "\nRun scripts/build_console_data.py and commit the payload with the receipts."
    )
    # A test that exempted everything would also report no failures.
    assert checked >= 30, f"only {checked} digests were actually compared"


def test_the_exemption_is_exactly_what_the_signoff_rewrites(published: list[dict]) -> None:
    """Derived from the sign-off, not typed twice.

    The failure this prevents is a receipt added to the payload's exemption list and never
    added to the sign-off, which is an unchecked digest wearing a reason.
    """
    signoff = _load("signoff")
    marked = {r["name"] for r in published if r["rewritten_after_this_payload"]}
    assert marked == set(signoff._WRITTEN_BY_THIS_RUN), (
        f"payload marks {sorted(marked)}, signoff writes "
        f"{sorted(signoff._WRITTEN_BY_THIS_RUN)}"
    )
    assert len(marked) == 4, f"the exemption grew to {sorted(marked)}"


def test_the_marked_rows_still_name_a_file_that_exists(published: list[dict]) -> None:
    """A marked digest is one generation behind, not permission to publish a fiction."""
    for row in published:
        if not row["rewritten_after_this_payload"]:
            continue
        path = ARTIFACTS / row["name"]
        assert path.exists(), row["name"]
        assert len(row["sha256"]) == 64, row["name"]
        assert row["bytes"] > 0, row["name"]


def test_the_payload_lists_every_receipt_on_disk(published: list[dict]) -> None:
    """A receipt with no published digest is a receipt a reader cannot check at all."""
    on_disk = {p.name for p in ARTIFACTS.glob("*.json")}
    listed = {r["name"] for r in published}
    assert on_disk == listed, (
        f"unlisted: {sorted(on_disk - listed)}, phantom: {sorted(listed - on_disk)}"
    )


def test_the_note_says_why_four_are_marked(note: str) -> None:
    """The reason travels with the payload, because the page is what a judge reads."""
    for said in ("signoff.py", "one generation behind", "commit"):
        assert said in note, said
