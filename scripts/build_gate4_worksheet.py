"""Build the blinded worksheet kill gate 4 asks for, and commit to it before anyone reads it.

Gate 4 is the only gate in this project that needs a human, and it is the reason the gate is
still OPEN: nothing here has ever asked a person whether a waterfall supports a decisive
judgment at all. The threshold was fixed before the build. At least 80 percent of a balanced
sample, reviewed with the network's own labels and every model output hidden, must support a
decisive judgment about artifact usability or target consistency. Below that, the labelling
protocol is the problem and no amount of modelling fixes it.

    .venv/Scripts/python.exe scripts/build_gate4_worksheet.py
    .venv/Scripts/python.exe scripts/build_gate4_worksheet.py --out D:/tracetriage_gate4

**Why a commitment and not a promise.** A blinded study whose answer key sits in the
repository is blinded by good manners. This writes a random 32-byte salt and the mapping from
opaque item to observation into a key file **outside** the repository, and commits only
``sha256(salt | item | obs_id | image digest)`` per item. Before the review nobody can invert
that, including the reviewer, and after it anyone can verify from the receipt that the sample
and its order were fixed in advance. The reveal is published by ``scripts/score_gate4.py``
into ``artifacts/GATE4_RECEIPT.json``, and it recomputes every commitment before it scores
anything.

**What is deliberately in the bundle and not in the repository.** The images. A worksheet
that carried a per-item image digest into a public file would be invertible in a minute
against this repository's own tracked waterfalls, which is the same defect as committing the
key. The bundle is regenerable from the same seed by anyone who has either source, and the
receipt records which source was used.

The two sources, in preference order:

* the frozen snapshot, when it is present, which carries all three label classes including
  ``unknown`` and 2500 waterfalls to sample from
* the console's own tracked waterfalls, so the study can be run from a clean clone with no
  snapshot at all, at the cost of a smaller sample and no unknowns
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_gate3 import rate_lower_bound, rate_upper_bound  # noqa: E402

MANIFEST = REPO / "artifacts" / "GATE4_WORKSHEET.json"

#: Fixed before any response exists, and read by the scorer rather than typed there.
THRESHOLD = 0.80
DECISIVE_RULE = (
    "An item is decisive when the reviewer committed to an answer rather than declining. "
    "artifact_usable must be yes or no. When it is no, that is itself the decisive artifact "
    "judgment the gate names and the item counts. When it is yes, at least one of "
    "visible_signal or target_consistent must also be yes or no, because an image the "
    "reviewer calls usable and then declines to judge on every axis supported no judgment."
)
CI_METHOD = (
    "Exact one-sided Clopper-Pearson bounds at 95 percent, from "
    "scripts/run_gate3.py::rate_lower_bound and rate_upper_bound, so gates 3 and 4 read "
    "their rates from the same function."
)
VERDICT_RULE = (
    "PASSED when the 95 percent lower bound is at or above the threshold. FAILED when the "
    "upper bound is below it. NOT_ESTABLISHED when the interval contains it. NOT_RUN when no "
    "response has been recorded, which is not a failure and is not a pass."
)

#: Two opaque items for one observation is how intra-rater agreement is measured without
#: telling the reviewer they are judging the same image twice, so they must not land next to
#: each other.
MIN_REPEAT_SEPARATION = 6

#: The sample size is an arithmetic consequence of the threshold, not a taste. The verdict
#: reads the exact 95 percent lower bound, so a study of n observations can only return
#: PASSED when at least k of them are decisive, and k/n is strictly above the 0.80 the gate
#: asks for. At 36 observations k is 34, a rate of 0.944, so a corpus whose true decisive rate
#: is 0.90 could not establish the threshold no matter how the review went: the instrument
#: would return NOT_ESTABLISHED by construction. At 60 it is 54, and a true rate of 0.90 gives
#: a lower bound of 0.812, which clears it. That is the band a waterfall corpus plausibly sits
#: in, so 60 unique observations is the smallest size at which running the study can answer
#: the question it asks. The cost is reviewer minutes and it is paid once.
DEFAULT_PER_CLASS = 20
DEFAULT_REPEATS = 12


def _decisive_thresholds(n: int) -> dict[str, Any]:
    """What this sample size can and cannot conclude, computed rather than asserted."""
    pass_at = next((k for k in range(n + 1) if rate_lower_bound(k, n) >= THRESHOLD), None)
    fail_below = max(
        (k for k in range(n + 1) if rate_upper_bound(k, n) < THRESHOLD),
        default=None,
    )
    return {
        "unique_observations": n,
        "minimum_decisive_for_pass": pass_at,
        "minimum_rate_for_pass": None if pass_at is None else round(pass_at / n, 4),
        "maximum_decisive_for_fail": fail_below,
        "lower_bound_if_the_true_rate_is_0.90": round(rate_lower_bound(round(0.90 * n), n), 4),
        "lower_bound_if_the_true_rate_is_0.95": round(rate_lower_bound(round(0.95 * n), n), 4),
        "reading": (
            "The verdict reads the interval and not the point estimate, so a sample size fixes "
            "the rate at which PASSED becomes reachable at all. minimum_rate_for_pass is that "
            "rate. It is above the threshold on purpose: an exact bound at 95 percent will not "
            "certify 0.80 from a sample that merely averages 0.80."
        ),
    }

_CLASSES = ("with-signal", "without-signal", "unknown")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_stimulus(source: Path, destination: Path, item: str) -> str:
    """Write one item's image, and return the digest of what it depicts.

    A repeated observation appears twice under two item ids, and the first version of this
    wrote both copies with ``shutil.copyfile``. Byte-identical copies mean ``sha256sum *`` over
    the bundle recovers every repeat pair with no salt, no key and no repository: 45 files, 36
    distinct digests, 9 groups of two, and those 9 groups were exactly the 9 repeats. The gate
    metric survived that, because it scores first occurrences only, but intra-rater agreement
    did not: a reviewer who spots the duplicate can reproduce their earlier answer on purpose,
    and that number is the ceiling this gate puts on its own reliability.

    So each item is re-encoded through PIL with its own item id written into a PNG text chunk.
    The files differ in bytes and depict the same pixels, which is what the design needed all
    along. The returned digest is over the decoded pixels rather than the file, so a test can
    assert that a repeat is the same image without asserting the property that leaked it.
    """
    with Image.open(source) as image:
        frame = image.convert("RGB")
        meta = PngInfo()
        meta.add_text("item", item)
        frame.save(destination, format="PNG", pnginfo=meta, optimize=False)
        return hashlib.sha256(
            f"{frame.mode}|{frame.size}|".encode() + frame.tobytes()
        ).hexdigest()


def _snapshot_rows(snapshot: Path) -> list[dict[str, Any]]:
    """Every observation in the snapshot that has a waterfall on disk."""
    rows: list[dict[str, Any]] = []
    waterfalls = snapshot / "waterfalls"
    for page in sorted((snapshot / "pages").glob("*.json")):
        for row in json.loads(page.read_text(encoding="utf-8")):
            image = waterfalls / f"waterfall_{row['id']}.png"
            if image.exists():
                rows.append(
                    {
                        "obs_id": int(row["id"]),
                        "label": row.get("waterfall_status") or "unknown",
                        "image": image,
                    }
                )
    return rows


def _console_rows() -> list[dict[str, Any]]:
    """The tracked console waterfalls, for a checkout with no snapshot.

    The console ships imagery only for observations that carry a decisive network label, so
    this source has no ``unknown`` class at all. The manifest records that, rather than
    letting a two-class sample read as the balanced three-class one the gate asked for.
    """
    data = REPO / "apps" / "web" / "public" / "data" / "cards.json"
    images = REPO / "apps" / "web" / "public" / "waterfalls"
    rows: list[dict[str, Any]] = []
    for card in json.loads(data.read_text(encoding="utf-8"))["cards"]:
        obs_id = int(card["obs_id"])
        for suffix in (".webp", ".png"):
            image = images / f"{obs_id}{suffix}"
            if image.exists():
                rows.append(
                    {
                        "obs_id": obs_id,
                        "label": card.get("waterfall_status") or "unknown",
                        "image": image,
                    }
                )
                break
    return rows


def _balanced_sample(
    rows: list[dict[str, Any]], per_class: int, rng: random.Random
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Equal numbers per label class, or as close as the source allows, and say which."""
    by_class: dict[str, list[dict[str, Any]]] = {name: [] for name in _CLASSES}
    for row in rows:
        if row["label"] in by_class:
            by_class[row["label"]].append(row)

    chosen: list[dict[str, Any]] = []
    available: dict[str, int] = {}
    for name in _CLASSES:
        pool = sorted(by_class[name], key=lambda r: r["obs_id"])
        available[name] = len(pool)
        chosen.extend(rng.sample(pool, min(per_class, len(pool))))
    return chosen, available


def _lay_out(
    unique: list[dict[str, Any]], repeats: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Order the items so no repeated pair sits within MIN_REPEAT_SEPARATION of its twin."""
    repeated = rng.sample(unique, min(repeats, len(unique)))
    attempts = 10_000
    for _ in range(attempts):
        order = unique + repeated
        rng.shuffle(order)
        positions: dict[int, list[int]] = {}
        for index, row in enumerate(order):
            positions.setdefault(row["obs_id"], []).append(index)
        if all(
            len(places) == 1 or min(b - a for a, b in zip(places, places[1:], strict=False))
            >= MIN_REPEAT_SEPARATION
            for places in positions.values()
        ):
            return order
    raise SystemExit(
        f"could not separate the repeated items by {MIN_REPEAT_SEPARATION} positions in "
        f"{attempts} attempts. Reduce --repeats or the separation."
    )


WORKSHEET_HEADER = """# Gate 4 worksheet

{n_items} images. About {minutes} minutes. Judge each one on its own and do not go back to
change an earlier answer.

You are not being asked whether a satellite was heard. You are being asked whether **this
image supports a judgment at all**, which is the thing this project has never measured.

For each item, open `images/{first_image}` and answer three questions in
`responses.csv`:

**artifact_usable** — can this image be read? Are the axes present, is the frame complete, is
it free of the rendering faults that make a spectrogram undecidable? `yes`, `no`, or `unsure`.

**visible_signal** — is there a trace above the noise anywhere in the frame? `yes`, `no`, or
`unsure`.

**target_consistent** — does any visible trace look like a satellite pass, meaning a smooth
curve drifting across frequency, rather than a straight vertical carrier or a horizontal
band? `yes`, `no`, `na` if there is nothing to judge, or `unsure`.

`unsure` is a real answer and the point of the study. Do not guess to be helpful: a guess
here inflates the exact number this gate exists to measure.

Nothing in this bundle tells you what the network labelled these observations, what the model
predicted, or which observation any item is. That is deliberate and it is committed to: the
mapping is salted and hashed into `artifacts/GATE4_WORKSHEET.json` in the repository, so it
can be verified afterwards that the sample and its order were fixed before you started.

Items, in order:

"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("D:/tracetriage_gate4"))
    ap.add_argument("--snapshot", type=Path, default=Path("D:/tracetriage_data/snap-stage1"))
    ap.add_argument("--per-class", type=int, default=DEFAULT_PER_CLASS)
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument(
        "--source",
        choices=("auto", "snapshot", "console"),
        default="auto",
        help="auto prefers the snapshot when it exists, because it carries the unknown class",
    )
    ap.add_argument(
        "--salt",
        default=None,
        help="fixed salt, for tests only. Omitted in a real build so the commitment binds.",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST,
        help=(
            "where the committed preregistration goes. Overridden by tests so a test run "
            "cannot overwrite the manifest a real study is committed to."
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help=(
            "replace an existing manifest. Without this the build refuses, because the "
            "manifest is a commitment and overwriting it destroys the evidence that the "
            "sample predated the review."
        ),
    )
    args = ap.parse_args(argv)

    if args.manifest.exists() and not args.force:
        raise SystemExit(
            f"{args.manifest} already exists, so this repository is already committed to a "
            f"worksheet. Building over it would replace a commitment with a newer one and "
            f"nothing would record that it happened. Pass --force if that is what you mean, "
            f"or --manifest to write somewhere else."
        )

    source = args.source
    if source == "auto":
        source = "snapshot" if (args.snapshot / "pages").is_dir() else "console"
    rows = _snapshot_rows(args.snapshot) if source == "snapshot" else _console_rows()
    if not rows:
        raise SystemExit(
            f"no observations with imagery from the {source} source. The snapshot lives "
            f"outside the repository; pass --source console to use the tracked waterfalls."
        )

    rng = random.Random(args.seed)
    unique, available = _balanced_sample(rows, args.per_class, rng)
    order = _lay_out(unique, args.repeats, rng)

    salt = args.salt or secrets.token_hex(32)
    images_out = args.out / "images"
    if images_out.exists():
        shutil.rmtree(images_out)
    images_out.mkdir(parents=True)

    items: list[dict[str, Any]] = []
    key_rows: list[dict[str, Any]] = []
    for index, row in enumerate(order, start=1):
        item = f"G4-{index:03d}"
        destination = images_out / f"{item}.png"
        pixel_digest = _write_stimulus(row["image"], destination, item)
        image_digest = _digest(destination)
        commitment = hashlib.sha256(
            f"{salt}|{item}|{row['obs_id']}|{image_digest}".encode()
        ).hexdigest()
        items.append({"item": item, "commitment": commitment})
        key_rows.append(
            {
                "item": item,
                "obs_id": row["obs_id"],
                "label": row["label"],
                "image_sha256": image_digest,
                "pixel_sha256": pixel_digest,
                "image_name": destination.name,
            }
        )

    # The key leaves the repository. Writing it inside would make the commitment theatre.
    (args.out / "KEY_do_not_open_until_scored.json").write_text(
        json.dumps({"salt": salt, "items": key_rows}, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    n_items = len(items)
    (args.out / "worksheet.md").write_text(
        WORKSHEET_HEADER.format(
            n_items=n_items,
            minutes=round(n_items * 25 / 60),
            first_image=key_rows[0]["image_name"],
        )
        + "\n".join(f"- `{i['item']}`" for i in items)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (args.out / "responses.csv").write_text(
        "item,artifact_usable,visible_signal,target_consistent,notes\n"
        + "".join(f"{i['item']},,,,\n" for i in items),
        encoding="utf-8",
        newline="\n",
    )

    args.manifest.write_text(
        json.dumps(
            {
                "schema": "GATE4_WORKSHEET",
                "schema_version": 1,
                "gate": 4,
                "unit": "E6",
                "source": source,
                "seed": args.seed,
                "per_class_requested": args.per_class,
                "observations_available_per_class": available,
                "unique_observations": len({r["obs_id"] for r in order}),
                "repeated_observations": args.repeats,
                "items": n_items,
                "min_repeat_separation": MIN_REPEAT_SEPARATION,
                "threshold": THRESHOLD,
                "what_this_sample_size_can_establish": _decisive_thresholds(
                    len({r["obs_id"] for r in order})
                ),
                "salt_source": (
                    "32 random bytes from secrets.token_hex, so the commitment binds"
                    if args.salt is None
                    else "fixed by --salt, which is a test path: a known salt means the "
                    "commitment proves nothing and this run must not be read as a "
                    "preregistration"
                ),
                "decisive_rule": DECISIVE_RULE,
                "verdict_rule": VERDICT_RULE,
                "ci_method": CI_METHOD,
                "commitment_scheme": (
                    "sha256(salt | item | obs_id | image_sha256) per item, with the salt and "
                    "the mapping written outside the repository. The reveal is published by "
                    "scripts/score_gate4.py, which recomputes every commitment before it "
                    "scores a single response and refuses on any mismatch."
                ),
                "what_is_hidden_from_the_reviewer": [
                    "the network's waterfall_status label",
                    "every model output, probability and reason code",
                    "the observation id, the station, the satellite and the pass time",
                    "which items are repeats of one another",
                ],
                "what_the_blinding_does_not_cover": [
                    "A reviewer who decodes the images and hashes the pixels can still group "
                    "the repeats. The files are byte-distinct, which stops the accident; "
                    "nothing here stops someone who is trying.",
                    "With --source console the images are re-encodes of waterfalls this "
                    "repository tracks, so a pixel match against apps/web/public/waterfalls "
                    "recovers the observation id and cards.json then gives the label. The "
                    "snapshot source has no such path, is preferred when present, and is what "
                    "the committed build used.",
                    "The reviewer is one person's judgment. Two readers scoring the same "
                    "bundle is what would separate the protocol from the reader, and this "
                    "instrument supports it by being reproducible from the seed rather than "
                    "by measuring it.",
                ],
                "commitments": items,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(f"bundle written to {args.out}")
    print(f"  {n_items} items, {len({r['obs_id'] for r in order})} observations, source {source}")
    print(f"  available per class: {available}")
    print(f"  manifest committed to {args.manifest}")
    print(f"  key written to {(args.out / 'KEY_do_not_open_until_scored.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
