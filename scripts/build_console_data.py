"""Build the static evidence console's data and imagery (unit C5).

Everything the console shows is produced here, from the committed receipts and the
local snapshot, and written into ``apps/web/public``. The console itself performs
no computation on a claim: it renders numbers that were measured by the pipeline
and validated against their contracts before they reached disk.

Three decisions worth stating, because each one could reasonably have gone the
other way.

**Intensity is the unweighted channel mean.** A SatNOGS waterfall is false
coloured, so its luma is not its intensity: converting with the usual ITU weights
would show a different quantity from the one the corridor fit scored, and two
different intensities can share a luma. ``corridor_fit.normalised_rows`` uses
``rgb.mean(axis=2)``, so the exported image is that same mean, written as an 8-bit
greyscale. The console then applies its palette on the GPU. What a judge sees is
what was measured.

**The corridor overlay is computed by the pipeline, not redrawn by the console.**
``physics.corridor_columns`` maps the predicted Doppler curve to pixel columns
through the axis sign convention, and the exported path is exactly what the
matched filter scored at the fitted offset. A curve the console drew for itself
would be a picture of the physics rather than evidence of it.

**Only a curated subset ships.** Waterfalls are 1.9 MB PNGs and there are 2,500 of
them. The console ships the top of the shipped queue plus the observations the
findings actually name, as greyscale WebP at roughly an eighth the weight, with
attribution, under the terms in DATA_LICENSE.md.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from pipeline.tracetriage.physics import (  # noqa: E402
    corridor_columns,
    corridor_for_obs,
)
from pipeline.tracetriage.splits import (  # noqa: E402
    _PAGES_DIR,
    _load_raw_pages,
)
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402

_ARTIFACTS = _REPO / "artifacts"
_WATERFALL_DIR = Path("D:/tracetriage_data/snap-stage1/waterfalls")
_OUT_DIR = _REPO / "apps" / "web" / "public"
_DATA_DIR = _OUT_DIR / "data"
_IMG_DIR = _OUT_DIR / "waterfalls"

#: Observations the findings name by number. They ship whatever their queue rank,
#: because a console that only shows the top of its own ranking cannot show the
#: cases the write-up discusses.
NAMED_OBSERVATIONS = [
    14740031,  # 32.0 ppm from catalogue, strongest uncorrected match in A3
    14746118,  # strongest corrected match in A3
]

#: How many of the shipped queue to carry imagery for.
DEFAULT_SHOWCASE = 24

#: WebP quality for the full waterfall. 82 holds the trace structure at about an
#: eighth of the PNG weight; the intensity that matters is a broad gradient, not
#: fine texture, so this is not a lossy-edit trap.
_WEBP_QUALITY = 82
_THUMB_WIDTH = 180


def _load(name: str) -> dict[str, Any]:
    return json.loads((_ARTIFACTS / name).read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(doc: dict[str, Any], key: str) -> Any:
    """Fetch a receipt field, refusing to publish a null in place of a missing one.

    The first version of this export used ``.get()`` for these and shipped four
    splits whose partition counts were all ``{}`` and two arm sections that were
    ``null``, because the key names it guessed were not the ones the receipts
    use. A page that renders that says "not measured" about numbers that were
    measured, which is the same class of error as reporting a measurement that
    was not taken. Absence is now a build failure, not a value.
    """
    if key not in doc:
        raise KeyError(
            f"receipt has no {key!r}; present keys are {sorted(doc)}. "
            "The export must not substitute null for a field it failed to find."
        )
    value = doc[key]
    # Zero and False are measurements and must pass. An empty container or an
    # empty string is the shape the defect took: present, and saying nothing.
    if value is None or (isinstance(value, list | dict | str) and not value):
        raise ValueError(
            f"receipt field {key!r} is empty ({value!r}). Publishing it would "
            "show an absent measurement where one exists."
        )
    return value


def _channel_mean_grey(rgb: np.ndarray) -> Image.Image:
    """8-bit greyscale of the unweighted channel mean.

    The same quantity ``corridor_fit.normalised_rows`` operates on. Rounded rather
    than truncated, so the mapping is symmetric about each integer level.
    """
    mean = rgb[:, :, :3].astype(np.float32).mean(axis=2)
    return Image.fromarray(np.rint(mean).clip(0, 255).astype(np.uint8), mode="L")


def _pass_duration_s(record: dict[str, Any]) -> float | None:
    try:
        start = datetime.datetime.fromisoformat(record["start"].replace("Z", "+00:00"))
        end = datetime.datetime.fromisoformat(record["end"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return (end - start).total_seconds()


def export_observation(
    obs_id: int,
    record: dict[str, Any],
    corridor_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Imagery and overlay geometry for one observation.

    Returns a record whose ``degraded`` field names the reason when the
    observation cannot be shown, rather than omitting it. A missing card and a
    card that could not be built look identical to a reader otherwise.
    """
    source = _WATERFALL_DIR / f"waterfall_{obs_id}.png"
    if not source.exists():
        return {"obs_id": obs_id, "degraded": f"No waterfall image at {source.name}."}

    with Image.open(source) as image:
        rgb = np.asarray(image.convert("RGB"))

    rx_freq = record.get("center_frequency") or record.get("observation_frequency")
    geometry = parse_waterfall(
        source,
        obs_id,
        pass_duration_s=_pass_duration_s(record),
        rx_freq_hz=rx_freq,
        observation_freq_hz=record.get("observation_frequency"),
    )
    if geometry.degraded or geometry.crop_box is None:
        return {
            "obs_id": obs_id,
            "degraded": (
                f"Waterfall geometry could not be derived: "
                f"{geometry.degraded or 'no crop box'}."
            ),
        }

    box = geometry.crop_box
    cropped = rgb[box.y0: box.y1, box.x0: box.x1]
    grey = _channel_mean_grey(cropped)

    _IMG_DIR.mkdir(parents=True, exist_ok=True)
    full_path = _IMG_DIR / f"{obs_id}.webp"
    grey.save(full_path, format="WEBP", quality=_WEBP_QUALITY, method=6)

    thumb_height = max(1, round(grey.height * _THUMB_WIDTH / grey.width))
    thumb = grey.resize((_THUMB_WIDTH, thumb_height), Image.LANCZOS)
    thumb_path = _IMG_DIR / f"{obs_id}_thumb.webp"
    thumb.save(thumb_path, format="WEBP", quality=74, method=6)

    out: dict[str, Any] = {
        "obs_id": obs_id,
        "degraded": None,
        "image": f"/waterfalls/{obs_id}.webp",
        "thumb": f"/waterfalls/{obs_id}_thumb.webp",
        "width": grey.width,
        "height": grey.height,
        "bytes": full_path.stat().st_size,
        "source_sha256": _digest(source),
        "intensity": "unweighted mean of the R, G and B channels, 8-bit",
        "hz_per_px": geometry.hz_per_px,
        "seconds_per_px": geometry.seconds_per_px,
        "centre_px": geometry.centre_px,
        "derivation": geometry.derivation,
        "derivation_confidence": geometry.derivation_confidence,
        "rx_freq_hz": rx_freq,
        "start": record.get("start"),
        "end": record.get("end"),
        "ground_station": record.get("ground_station"),
        "station_name": record.get("station_name"),
        "norad_cat_id": record.get("norad_cat_id"),
        "transmitter_uuid": record.get("transmitter_uuid"),
        "transmitter_mode": record.get("transmitter_mode"),
        "waterfall_status": record.get("waterfall_status"),
        "corridor": None,
        "corridor_note": None,
    }

    # The overlay: the predicted Doppler curve at the fitted offset, mapped to
    # columns by the pipeline's own function so the console draws what the
    # matched filter scored rather than its own idea of the same curve.
    if geometry.centre_px is None:
        out["corridor_note"] = (
            "No centre pixel could be derived for this image, so the corridor "
            "cannot be placed on the frequency axis. About 6% of records lack the "
            "frequency information this needs."
        )
        return out

    physics = corridor_for_obs(record)
    if physics.degraded or physics.uncorrected is None:
        out["corridor_note"] = f"Physics corridor degraded: {physics.degraded}."
        return out

    offset_hz = (corridor_row or {}).get("fitted_offset_hz") or 0.0
    fitted = corridor_columns(
        physics.uncorrected,
        hz_per_px=geometry.hz_per_px,
        centre_px=geometry.centre_px,
        image_height=grey.height,
        freq_offset_hz=offset_hz,
    )
    unshifted = corridor_columns(
        physics.uncorrected,
        hz_per_px=geometry.hz_per_px,
        centre_px=geometry.centre_px,
        image_height=grey.height,
        freq_offset_hz=0.0,
    )

    half_width_px = physics.uncorrected.half_width_hz / geometry.hz_per_px
    # Subsample the path: 1540 rows is more precision than an SVG polyline needs,
    # and the curve is smooth. Endpoints are always kept.
    step = max(1, grey.height // 240)
    rows = list(range(0, grey.height, step))
    if rows[-1] != grey.height - 1:
        rows.append(grey.height - 1)

    out["corridor"] = {
        "fitted_offset_hz": offset_hz,
        "fitted_offset_ppm": (corridor_row or {}).get("fitted_offset_ppm"),
        "offset_at_bound": (corridor_row or {}).get("offset_at_bound"),
        "half_width_px": half_width_px,
        "half_width_hz": physics.uncorrected.half_width_hz,
        "max_elevation_deg": physics.uncorrected.max_elevation_deg,
        "tca_frac": physics.uncorrected.tca_frac,
        "rows": rows,
        "fitted_px": [round(float(fitted[r]), 2) for r in rows],
        "predicted_px": [round(float(unshifted[r]), 2) for r in rows],
        "vertical_px": geometry.centre_px,
        "sigma_curved": (corridor_row or {}).get("sigma_curved"),
        "sigma_vertical": (corridor_row or {}).get("sigma_vertical"),
        "note": (
            "fitted_px is the predicted Doppler curve shifted by the fitted "
            "frequency offset, which is the path the matched filter scored. "
            "predicted_px is the same curve at zero offset, so the gap between "
            "them is the measurement. Time runs bottom to top: row 0 is the end "
            "of the pass. The frequency axis runs against the Doppler sign."
        ),
    }
    return out


def trim_queue_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "obs_id": entry["obs_id"],
        "rank": entry["rank"],
        "score": round(entry["score"], 6),
        "reasons": entry["reasons"],
        "is_conflict": entry["is_conflict"],
        "within_budget": entry.get("within_budget"),
        "displaced_by_cap": entry.get("displaced_by_cap"),
        "waterfall_status": entry["waterfall_status"],
        "model_prob": entry["model_prob"],
        "fitted_offset_ppm": entry["fitted_offset_ppm"],
        "offset_at_bound": entry["offset_at_bound"],
        "flat_row_frac": entry["flat_row_frac"],
        "ensemble_uncertainty": entry["ensemble_uncertainty"],
        "episode_key": entry["episode_key"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showcase", type=int, default=DEFAULT_SHOWCASE)
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help="rebuild the JSON only, leaving existing imagery in place",
    )
    args = parser.parse_args(argv)

    queue = _load("QUEUE_RECEIPT.json")
    fusion = _load("FUSION_RECEIPT.json")
    manifest = _load("SPLIT_MANIFEST.json")
    corridor = _load("corridor_features.json")
    corridor_by_obs = {r["obs_id"]: r for r in corridor["rows"]}

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ---- queue -----------------------------------------------------------
    entries = [trim_queue_entry(e) for e in queue["queue"]]
    (_DATA_DIR / "queue.json").write_text(
        json.dumps(
            {
                "generated_at": queue["generated_at"],
                "seed": queue["seed"],
                "review_budget": queue["review_budget"],
                "conflict_definition": queue["conflict_definition"],
                "deduplication": queue["deduplication"],
                "per_split_summaries": queue["per_split_summaries"],
                "entries": entries,
                "receipt_sha256": _digest(_ARTIFACTS / "QUEUE_RECEIPT.json"),
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    # ---- evaluation ------------------------------------------------------
    (_DATA_DIR / "evaluation.json").write_text(
        json.dumps(
            {
                "gate6": queue["gate6"],
                "gate5": _require(fusion, "gate5"),
                "ablation_conclusion": _require(fusion, "ablation_conclusion"),
                "arm_ladder": _require(fusion, "arm_ladder"),
                "size_matched_control": _require(fusion, "size_matched_control"),
                # Per-split arm metrics, comparisons and the selective-rejection
                # curve all live inside the split records rather than at the root.
                "fusion_splits": [
                    {
                        "split": s["split"],
                        "degraded": s.get("degraded"),
                        "counts": s.get("counts"),
                        "test_positive_rate": s.get("test_positive_rate"),
                        "arms": s.get("arms"),
                        "comparisons": s.get("comparisons"),
                        "multiplicity_adjusted": s.get("multiplicity_adjusted"),
                        "ensemble": s.get("ensemble"),
                        "selective": s.get("selective"),
                        "ood": s.get("ood"),
                    }
                    for s in _require(fusion, "splits")
                ],
                "receipt_sha256": {
                    "queue": _digest(_ARTIFACTS / "QUEUE_RECEIPT.json"),
                    "fusion": _digest(_ARTIFACTS / "FUSION_RECEIPT.json"),
                },
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    # ---- provenance ------------------------------------------------------
    split_counts = [
        {
            "name": name,
            "counts": {
                partition: len(ids)
                for partition, ids in split.items()
                if isinstance(ids, list)
            },
        }
        for name, split in _require(manifest, "splits").items()
    ]
    for record in split_counts:
        if not record["counts"]:
            raise ValueError(
                f"split {record['name']!r} exported zero partition counts. The "
                "manifest stores partitions as the split's own list-valued keys; "
                "an empty result means that shape changed."
            )

    receipts = sorted(p for p in _ARTIFACTS.glob("*.json"))
    (_DATA_DIR / "provenance.json").write_text(
        json.dumps(
            {
                "snapshot_id": queue["snapshot_id"],
                "split_manifest_sha256": queue["split_manifest_sha256"],
                "splits": split_counts,
                "receipts": [
                    {
                        "name": p.name,
                        "sha256": _digest(p),
                        "bytes": p.stat().st_size,
                    }
                    for p in receipts
                ],
                "contracts": [
                    {
                        "name": p.name,
                        "version": json.loads(p.read_text(encoding="utf-8")).get(
                            "schema_version"
                        ),
                        "status": json.loads(p.read_text(encoding="utf-8")).get(
                            "status"
                        ),
                        "sha256": _digest(p),
                    }
                    for p in sorted((_REPO / "contracts").glob("*.schema.json"))
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    # ---- documents rendered in the console -------------------------------
    for name in ("KILL_GATE.md", "CLAIM_REGISTER.md", "C2_PREREGISTRATION.md"):
        source = _REPO / "docs" / name
        if source.exists():
            shutil.copyfile(source, _DATA_DIR / name)

    # ---- observation cards ----------------------------------------------
    if args.skip_images:
        print("skipping imagery, JSON only")
        return 0

    raw = _load_raw_pages(_PAGES_DIR)
    wanted: list[int] = []
    for entry in entries:
        if len(wanted) >= args.showcase:
            break
        wanted.append(entry["obs_id"])
    for obs_id in NAMED_OBSERVATIONS:
        if obs_id not in wanted:
            wanted.append(obs_id)

    cards: list[dict[str, Any]] = []
    for index, obs_id in enumerate(wanted, start=1):
        record = raw.get(obs_id)
        if record is None:
            cards.append(
                {"obs_id": obs_id, "degraded": "Observation not in the snapshot."}
            )
            continue
        card = export_observation(obs_id, record, corridor_by_obs.get(obs_id))
        cards.append(card)
        state = card.get("degraded") or f"{card['bytes'] // 1024} KB"
        print(f"  [{index}/{len(wanted)}] {obs_id}: {state}")

    built = [c for c in cards if not c.get("degraded")]
    (_DATA_DIR / "cards.json").write_text(
        json.dumps(
            {
                "n_requested": len(wanted),
                "n_built": len(built),
                "n_degraded": len(cards) - len(built),
                "named_observations": NAMED_OBSERVATIONS,
                "intensity_note": (
                    "Waterfall imagery is the unweighted mean of the R, G and B "
                    "channels, which is the quantity the corridor fit operates on. "
                    "A SatNOGS waterfall is false coloured, so its luma is not its "
                    "intensity and two different intensities can share a luma."
                ),
                "attribution": (
                    "Waterfall imagery from the SatNOGS Network, contributed by "
                    "volunteer ground stations, under CC BY-SA 4.0. See "
                    "DATA_LICENSE.md."
                ),
                "cards": cards,
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    total_kb = sum(c.get("bytes", 0) for c in built) // 1024
    print(f"\n{len(built)} cards built, {len(cards) - len(built)} degraded")
    print(f"imagery total {total_kb} KB")
    print(f"data written to {_DATA_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
