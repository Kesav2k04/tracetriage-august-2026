"""Record what the deployed console returned in one filmed take, and what the tree holds.

The film shows a screen recording of https://tracetriage.vercel.app measuring a SatNOGS
observation. A recording is a picture of a claim, not the claim, so this writes the claim
down: the observation that was typed, the numbers the endpoint gave back, the same numbers
as this repository already committed for that observation, and the digest of the video file
the film plays. A reader can take the id, type it into the console, and compare.

The observation is deliberately one from the frozen corpus. Measuring a pass recorded after
the snapshot shows the pipeline runs on new data, which `scripts/build_live_shelf.py`
already establishes. Measuring one that is in the corpus asks a different question: does the
path a reader can drive reproduce the number this project published months earlier. The fit
does, digit for digit.

    .venv/Scripts/python.exe scripts/record_live_take.py          # measures, needs network
    .venv/Scripts/python.exe scripts/record_live_take.py --check  # measures nothing

`--check` re-reads the committed receipt and verifies it against the video file on disk and
against the committed rows it quotes. It makes no network call, so `tests/test_live_take.py`
runs it in the offline suite. Where ffprobe is absent the video's frame count and duration
are not compared, and the check says so rather than failing on a number it could not read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RECEIPT = REPO / "artifacts" / "LIVE_TAKE.json"
TAKE = REPO / "apps" / "web" / "public" / "film" / "live-take.mp4"
CORRIDOR = REPO / "artifacts" / "corridor_features.json"
POOL = REPO / "artifacts" / "GATE3_POOL.json"

#: The observation typed into the console during the take.
OBS_ID = 14742699

#: How the published file was cut from the camera original. One take: the only edits are two
#: playback rates and a held final frame. The rates are fields rather than prose because the
#: film prints them on screen, and a figure a viewer reads should come from a receipt.
EDIT = {
    "takes": 1,
    "cut_from_s": 10.8,
    "handover_s": 30.0,
    "rate_before_handover": 4,
    "rate_after_handover": 2,
    "hold_last_frame_s": 3.5,
    "note": (
        "one take. The recording runs from 10.8 s to 30.0 s at 4x and from 30.0 s to its "
        "end at 2x, then the final frame is held for 3.5 s. Nothing is cut out of the "
        "middle, so the wait for the endpoint is compressed rather than removed."
    ),
}
SOURCE = {
    "tool": "playwright chromium, record_video at 1920x1080",
    "site": "https://tracetriage.vercel.app/live/",
    "raw_seconds": 39.48,
    "raw_sha256": "",
    "raw_is_tracked": False,
    "raw_note": (
        "the camera original is not tracked: it is 3.6 MB of the same frames at a quarter "
        "of the useful pixels per byte. Its digest is here so the published cut can be "
        "tied back to it."
    ),
}

#: The quantities the live path and the committed corridor fit are expected to agree on to
#: the last digit, and the ones that do not. Both lists are published: an agreement table
#: that only lists agreements is not a check.
FIT_FIELDS = (
    ("offset_hz", "fitted_offset_hz"),
    ("offset_ppm", "fitted_offset_ppm"),
    ("sigma", "sigma_curved"),
)
FIT_INNER = (
    ("detect_frac", "detect_frac_curved"),
    ("residual_p50_hz", "residual_p50_hz"),
    ("residual_p95_hz", "residual_p95_hz"),
    ("coverage", "coverage_curved"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe(path: Path) -> dict[str, object] | None:
    """Codec, size, frame count and duration of a video, or None without ffprobe."""
    if shutil.which("ffprobe") is None:
        return None
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
            "-show_entries", "stream=width,height,nb_read_frames,codec_name,r_frame_rate",
            "-show_entries", "format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    doc = json.loads(out)
    stream = doc["streams"][0]
    return {
        "codec": stream["codec_name"],
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "frames": int(stream["nb_read_frames"]),
        "fps": stream["r_frame_rate"],
        "seconds": round(float(doc["format"]["duration"]), 6),
    }


def _committed() -> dict[str, object]:
    """The rows this repository already holds for the observation that was typed."""
    corridor = next(
        row
        for row in json.loads(CORRIDOR.read_text(encoding="utf-8"))["rows"]
        if row["obs_id"] == OBS_ID
    )
    pool = next(
        row
        for row in json.loads(POOL.read_text(encoding="utf-8"))["observations"]
        if row["obs_id"] == OBS_ID
    )
    return {"corridor_features": corridor, "gate3_pool": pool}


def _measure() -> dict[str, object]:
    from pipeline.tracetriage import live as engine

    with engine.make_client() as client:
        row = engine.fetch_observation(OBS_ID, client)
        image = engine.fetch_waterfall(row["waterfall"], client)
        return engine.measure(row, image, n_nulls=200).to_dict()


def _agreement(live: dict, committed: dict) -> dict[str, object]:
    corridor = committed["corridor_features"]
    pool = committed["gate3_pool"]
    fit = live["measurement"]["fit"] or {}

    exact: list[dict[str, object]] = []
    differs: list[dict[str, object]] = []

    def compare(name: str, now: object, held: object, where: str) -> None:
        row = {
            "quantity": name,
            "measured_live": now,
            "committed": held,
            "committed_in": where,
        }
        (exact if now == held else differs).append(row)

    for live_key, held_key in FIT_FIELDS:
        compare(
            live_key,
            live["measurement"][live_key],
            corridor[held_key],
            "corridor_features.json",
        )
    for live_key, held_key in FIT_INNER:
        compare(live_key, fit.get(live_key), corridor[held_key], "corridor_features.json")
    compare("mode.verdict", live["mode"]["verdict"], pool["verdict"], "GATE3_POOL.json")
    compare(
        "mode.sigma_curved",
        live["mode"]["sigma_curved"],
        pool["sigma_curved"],
        "GATE3_POOL.json",
    )
    compare(
        "mode.sigma_vertical",
        live["mode"]["sigma_vertical"],
        pool["sigma_vertical"],
        "GATE3_POOL.json",
    )

    return {
        "n_exact": len(exact),
        "n_differs": len(differs),
        "exact": exact,
        "differs": differs,
        "reading": (
            "The offset fit reproduces to the last digit because it is the same function "
            "over the same downloaded image, and the offset is quantised to whole pixels "
            "of the waterfall. The two mode scores do not. GATE3_POOL.json is written by "
            "scripts/build_gate3_pool.py and the live figure by pipeline/tracetriage/"
            "live.py, and the two score the corrected corridor against the uncorrected one "
            "with different filter settings. Both return the same verdict. Two consecutive "
            "live measurements of this observation came back bit-identical, so the gap is "
            "between the two writers rather than between two runs."
        ),
    }


def build(raw: Path | None) -> int:
    if not TAKE.exists():
        print(f"missing {TAKE.relative_to(REPO).as_posix()}", file=sys.stderr)
        return 1

    live = _measure()
    committed = _committed()
    source = dict(SOURCE)
    # The camera original lives wherever it was recorded, which is a fact about one
    # machine and not about this repository. Given a path, its digest is taken; given
    # none, the digest already published is carried forward rather than blanked, because
    # a rebuild that measures again has not re-cut the video.
    if raw is not None:
        source["raw_sha256"] = _sha256(raw)
        source["raw_seconds"] = (_probe(raw) or {}).get("seconds", SOURCE["raw_seconds"])
    elif RECEIPT.exists():
        held = json.loads(RECEIPT.read_text(encoding="utf-8"))["take"]["source"]
        source["raw_sha256"] = held["raw_sha256"]
        source["raw_seconds"] = held["raw_seconds"]

    observation = live["observation"]
    payload = {
        "schema": "artifacts/LIVE_TAKE.json",
        "schema_version": 1,
        "what_this_is": (
            "The one filmed take of the deployed console measuring an observation, with the "
            "numbers it returned and the numbers this repository already held for the same "
            "observation."
        ),
        "what_this_does_not_measure": (
            "Nothing here says the method is right. It says the path a reader can drive "
            "returns what the committed receipts say, for one observation, on one day."
        ),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generated_by": "scripts/record_live_take.py",
        "observation": {
            "id": OBS_ID,
            "satellite": observation.get("satellite"),
            "station": observation.get("station"),
            "station_name": observation.get("station_name"),
            "start": observation.get("start"),
            "end": observation.get("end"),
            "waterfall_status": observation.get("waterfall_status"),
            "observation_status": observation.get("status"),
            "in_frozen_corpus": True,
        },
        "take": {
            "path": TAKE.relative_to(REPO).as_posix(),
            "bytes": TAKE.stat().st_size,
            "sha256": _sha256(TAKE),
            "video": _probe(TAKE),
            "edit": EDIT,
            "source": source,
        },
        "measured_live": {
            "measured_at_utc": live["provenance"]["measured_at_utc"],
            "verdict": live["mode"]["verdict"],
            "why": live["mode"]["why"],
            "mode_sigma_curved": live["mode"]["sigma_curved"],
            "mode_sigma_vertical": live["mode"]["sigma_vertical"],
            "offset_hz": live["measurement"]["offset_hz"],
            "offset_ppm": live["measurement"]["offset_ppm"],
            "fit_sigma": live["measurement"]["sigma"],
            "detect_frac": (live["measurement"]["fit"] or {}).get("detect_frac"),
            "nulls_n": live["nulls"]["n"],
            "p_value": live["nulls"]["p_value"],
            "waterfall_sha256": live["provenance"]["waterfall_sha256"],
            "waterfall_bytes": live["provenance"]["waterfall_bytes"],
            "hz_per_px": live["axis"]["hz_per_px"],
            "axis_confidence": live["axis"]["confidence"],
        },
        "committed": committed,
        "agreement": _agreement(live, committed),
    }
    # newline="\n" because write_text otherwise translates to CRLF on Windows, while
    # .gitattributes normalises the committed file to LF. The working copy would then be a
    # different size from the published one, and docs/REFERENCE.md records a byte count
    # per artifact that a clone would disagree with.
    RECEIPT.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"{RECEIPT.relative_to(REPO).as_posix()} written.")
    print(
        f"  {payload['agreement']['n_exact']} quantities agree to the last digit, "
        f"{payload['agreement']['n_differs']} do not."
    )
    return 0


def check() -> int:
    if not RECEIPT.exists():
        print("[FAIL] no LIVE_TAKE.json", file=sys.stderr)
        return 1
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    bad: list[str] = []

    take = payload["take"]
    if not TAKE.exists():
        bad.append(f"{take['path']} is not in the tree")
    else:
        size = TAKE.stat().st_size
        if size != take["bytes"]:
            bad.append(f"{take['path']} is {size} bytes, the receipt says {take['bytes']}")
        if _sha256(TAKE) != take["sha256"]:
            bad.append(f"{take['path']} digest does not match the receipt")
        probed = _probe(TAKE)
        if probed is None:
            print("[SKIP] ffprobe is not installed, so the frame count was not compared")
        elif probed != take["video"]:
            bad.append(f"{take['path']} probes as {probed}, the receipt says {take['video']}")

    if _committed() != payload["committed"]:
        bad.append("the committed rows quoted in the receipt are not the rows in the tree")

    for row in payload["agreement"]["exact"]:
        if row["measured_live"] != row["committed"]:
            bad.append(f"{row['quantity']} is listed as exact but the two values differ")
    for row in payload["agreement"]["differs"]:
        if row["measured_live"] == row["committed"]:
            bad.append(f"{row['quantity']} is listed as differing but the two values are equal")

    for line in bad:
        print(f"[FAIL] {line}", file=sys.stderr)
    if bad:
        return 1
    print(
        "[PASS] the take matches its receipt and "
        f"{payload['agreement']['n_exact']} quantities still agree to the last digit"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Receipt for the filmed live measurement.")
    parser.add_argument(
        "--check", action="store_true", help="Verify the committed receipt offline."
    )
    parser.add_argument(
        "--raw",
        type=Path,
        default=None,
        help="The camera original the published cut came from, to record its digest.",
    )
    args = parser.parse_args(argv)
    return check() if args.check else build(args.raw)


if __name__ == "__main__":
    raise SystemExit(main())
