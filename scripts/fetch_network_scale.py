"""Record how big the public network is, from that network's own API.

The README opens by saying what this problem is the size of. That sentence names three
figures, and a figure in this repository is only allowed to exist if something rebuilds
it, so this is the something. It writes `artifacts/NETWORK_SCALE.json`.

What it is careful about, because the numbers are easy to get subtly wrong:

*Observations* are counted by summing the per-station `observations` field over every
station. Each observation belongs to exactly one station, so the sum is the network total
and no pagination of the observation list is needed. That sum is then cross-checked
against the newest observation id, which is issued monotonically and never reused, so it
runs ahead of the surviving count by whatever has been deleted since. The two routes
agreeing to a few percent is what says the sum is a real total rather than one page of it.
A gap wider than `MAX_GAP` fails rather than publishes.

*Stations* are counted as registered, and reported with the online/offline split beside
them, because "4,442 ground stations" on its own reads as 4,442 receivers listening right
now and 330 of them were. The split is not decoration; it is the difference between the
claim being true and being marketing.

Nothing here feeds a result. No gate, split, queue or interval is computed from these
figures, and the 71% undecided rate measured on 600 sampled observations is not multiplied
up onto the network anywhere. This is context for a reader, held to the same rule as
everything else only because it is published.

    .venv/Scripts/python.exe scripts/fetch_network_scale.py
    .venv/Scripts/python.exe scripts/fetch_network_scale.py --check

SatNOGS is volunteer-run infrastructure. This makes three unauthenticated GETs, holds no
token, and writes nothing back.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "NETWORK_SCALE.json"

STATIONS = "https://network.satnogs.org/api/stations/"
SATELLITES = "https://db.satnogs.org/api/satellites/"
NEWEST = "https://network.satnogs.org/api/observations/?page_size=1"

HUMAN = {
    "stations": "https://network.satnogs.org/stations/",
    "satellites": "https://db.satnogs.org/satellites/",
    "observations": "https://network.satnogs.org/observations/",
}

USER_AGENT = "TraceTriage/1.0 (+https://github.com/Kesav2k04/tracetriage-august-2026)"
TIMEOUT = 120

#: How far the two independent routes to the observation total may disagree before this
#: refuses to publish either. Deleted observations leave gaps in the id sequence, so some
#: drift is expected; a large gap means one of the two routes is not measuring what it is
#: assumed to measure and neither number is safe to put in a README.
MAX_GAP = 10.0


def _get(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def measure() -> dict:
    stations = _get(STATIONS)
    satellites = _get(SATELLITES)
    newest = _get(NEWEST)
    newest_id = int((newest[0] if isinstance(newest, list) else newest)["id"])

    total = sum(int(s.get("observations") or 0) for s in stations)
    by_status = dict(collections.Counter(s.get("status") for s in stations))
    fields = {(s.get("qthlocator") or "")[:2] for s in stations if s.get("qthlocator")}
    gap = round((newest_id - total) / newest_id * 100, 2)
    if gap > MAX_GAP or gap < 0:
        raise SystemExit(
            f"the two routes to the observation total disagree by {gap}%, over the "
            f"{MAX_GAP}% this is willing to publish: summed {total:,} against a newest "
            f"id of {newest_id:,}. One of them is not counting what it is assumed to."
        )

    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return {
        "schema": "network_scale",
        "schema_version": 1,
        "what_this_is": (
            "The size of the public network TraceTriage reads, taken from that network's "
            "own public API so a reader can fetch the same endpoints and get the same "
            "order of magnitude. It is context for the README's opening, not an input to "
            "any result: no gate, split, queue or interval in this repository is computed "
            "from these numbers, and nothing here is extrapolated from the "
            "600-observation sample onto the network."
        ),
        "generated_by": "scripts/fetch_network_scale.py",
        "fetched_at": now.isoformat(timespec="seconds"),
        "method": "unauthenticated GET, no token, no writes, one request per endpoint",
        "sources": {
            "stations": STATIONS,
            "satellites": SATELLITES,
            "observations": NEWEST,
        },
        "human_pages": HUMAN,
        "ground_stations": {
            "registered": len(stations),
            "by_status": by_status,
            "distinct_maidenhead_fields": len(fields),
        },
        "observations": {
            "total": total,
            "how": (
                "sum of the per-station observation count over every station; each "
                "observation belongs to exactly one station, so the sum is the network "
                "total"
            ),
            "cross_check": {
                "newest_observation_id": newest_id,
                "why_it_differs": (
                    "ids are issued monotonically and never reused, so the newest id runs "
                    "ahead of the surviving count by whatever has been deleted since"
                ),
                "gap_percent": gap,
                "gap_percent_allowed": MAX_GAP,
            },
        },
        "satellites": {
            "in_database": len(satellites),
            "alive": sum(1 for s in satellites if s.get("status") == "alive"),
        },
        "what_this_does_not_establish": [
            "That the undecided rate measured on 600 sampled observations holds across "
            "all of them. It was measured on the sample and is reported on the sample.",
            "That every registered station is listening. The online count is beside the "
            "registered count for exactly this reason.",
            "Anything about how many people depend on the satellites in that list. The "
            "live count is a count of spacecraft, not of users.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify, write nothing")
    args = parser.parse_args(argv)

    if args.check:
        if not RECEIPT.is_file():
            print(f"{RECEIPT.relative_to(REPO)} is missing", file=sys.stderr)
            return 1
        held = json.loads(RECEIPT.read_text(encoding="utf-8"))
        gap = held["observations"]["cross_check"]["gap_percent"]
        print(
            f"{RECEIPT.relative_to(REPO)}: "
            f"{held['observations']['total']:,} observations, "
            f"{held['ground_stations']['registered']:,} stations "
            f"({held['ground_stations']['by_status'].get('Online', 0)} online), "
            f"{held['satellites']['alive']:,} live satellites, "
            f"routes agree to {gap}%, read {held['fetched_at']}"
        )
        return 0

    RECEIPT.write_text(json.dumps(measure(), indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {RECEIPT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
