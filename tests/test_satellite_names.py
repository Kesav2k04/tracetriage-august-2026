"""The console names the satellite behind every observation it ranks.

The judge-facing product identified its subjects by catalogue integer alone: the queue
table, the 25 evidence cards and the observation pages all showed 40025, 5485, 63217
where a mission name would sit, while `pipeline/tracetriage/live.py:555` had been
publishing the name as `satellite` on the live path the whole time. The field was in the
snapshot and in one of the two code paths, and nothing said the other one had to carry
it.

So these are the assertions that keep it carried. Every ranked row and every built card
has a non-empty name; the two payloads agree about the observations they share; and the
name in the payload is the name in the receipt, which is the name in the snapshot. The
last one is the load-bearing test: `scripts/build_console_data.py` reads the name from
`artifacts/SATELLITE_NAMES.json` for the queue and from the snapshot record for the
cards, which is two readers of one field, and two readers can drift.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DATA = _REPO / "apps" / "web" / "public" / "data"
_RECEIPT = _REPO / "artifacts" / "SATELLITE_NAMES.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_queue_row_names_its_satellite() -> None:
    entries = _load(_DATA / "queue.json")["entries"]
    assert entries, "queue.json published no entries"
    unnamed = [
        entry["obs_id"]
        for entry in entries
        if not str(entry.get("satellite") or "").strip()
    ]
    assert not unnamed, (
        f"{len(unnamed)} of {len(entries)} queue rows carry no satellite name, "
        f"starting with {unnamed[:5]}. The exporter is meant to refuse rather than "
        f"publish a blank one."
    )


def test_every_built_card_names_its_satellite() -> None:
    cards = _load(_DATA / "cards.json")["cards"]
    assert cards, "cards.json published no cards"
    built = [card for card in cards if not card.get("degraded")]
    assert built, "cards.json published no built card, so there is nothing to name"
    unnamed = [
        card["obs_id"]
        for card in built
        if not str(card.get("satellite") or "").strip()
    ]
    assert not unnamed, (
        f"{len(unnamed)} of {len(built)} built cards carry no satellite name, "
        f"starting with {unnamed[:5]}."
    )


def test_the_two_payloads_agree_about_the_same_satellite() -> None:
    """One field, two readers, and this is the test that they read the same thing.

    The queue takes the name from the committed receipt so that a clean clone with no
    snapshot can still rebuild it. The cards take it from the snapshot record, because
    a card cannot be built without the snapshot anyway. Nothing structural stops those
    two sources diverging, so the divergence is asserted against instead.
    """
    entries = {
        int(entry["obs_id"]): entry["satellite"]
        for entry in _load(_DATA / "queue.json")["entries"]
    }
    cards = {
        int(card["obs_id"]): card["satellite"]
        for card in _load(_DATA / "cards.json")["cards"]
        if not card.get("degraded")
    }
    shared = sorted(set(entries) & set(cards))
    assert shared, "no observation appears in both payloads, so nothing was compared"
    mismatched = {
        obs_id: (entries[obs_id], cards[obs_id])
        for obs_id in shared
        if entries[obs_id] != cards[obs_id]
    }
    assert not mismatched, (
        f"the queue and the cards disagree about {len(mismatched)} satellites: "
        f"{dict(list(mismatched.items())[:3])}"
    )


def test_the_published_names_are_the_receipts_names() -> None:
    receipt = _load(_RECEIPT)
    names = receipt["names"]
    assert receipt["source_field"] == "tle0", (
        "the receipt no longer says it carries tle0, so what the console publishes as "
        "the satellite is a different quantity than the one live.py publishes"
    )
    entries = _load(_DATA / "queue.json")["entries"]
    missing = [e["obs_id"] for e in entries if str(e["obs_id"]) not in names]
    assert not missing, (
        f"{len(missing)} published rows are not in SATELLITE_NAMES.json, starting with "
        f"{missing[:5]}. The receipt is built from the same queue receipt the payload "
        f"is, so a gap means one of the two was rebuilt without the other."
    )
    wrong = [
        e["obs_id"]
        for e in entries
        if e["satellite"] != names[str(e["obs_id"])]
    ]
    assert not wrong, (
        f"{len(wrong)} published names differ from the receipt, starting with "
        f"{wrong[:5]}. Re-run scripts/build_console_data.py --skip-images."
    )


def test_the_receipt_covers_the_whole_ranked_queue() -> None:
    """A receipt that named only the shipped 25 would leave 382 rows unnamed."""
    receipt = _load(_RECEIPT)
    ranked = _load(_REPO / "artifacts" / "QUEUE_RECEIPT.json")["queue"]
    assert receipt["n_observations"] == len(ranked), (
        f"the receipt names {receipt['n_observations']} observations and the queue "
        f"ranks {len(ranked)}"
    )
    assert len(receipt["names"]) == receipt["n_observations"], (
        "the receipt's own count disagrees with the number of entries it carries"
    )
