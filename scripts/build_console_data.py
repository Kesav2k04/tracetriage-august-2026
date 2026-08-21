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
    C_M_PER_S,
    corridor_columns,
    corridor_for_obs,
    geodetic_normal,
    pass_geometry,
    rx_freq_of,
    station_ecef,
)
from pipeline.tracetriage.splits import (  # noqa: E402
    _default_pages_dir,
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


def _require_present(doc: dict[str, Any], key: str) -> Any:
    """Fetch a field that must exist but whose measured value may be null.

    ``degraded`` is the case this exists for: null means the split ran, and a string
    names why it did not. Both are measurements, so ``_require`` would reject the good
    one, and ``.get()`` cannot tell "ran cleanly" from "the key was renamed".
    """
    if key not in doc:
        raise KeyError(
            f"receipt has no {key!r}; present keys are {sorted(doc)}. "
            "The export must not read an absent field as a null measurement."
        )
    return doc[key]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


#: The two halves of the precedent study. The warm half allows a neighbour from the query's
#: own station and the cold half forbids it, and only the second says whether similarity
#: carries an outcome across entities. Publishing one without the other would leave the
#: flattering number standing alone.
_PRECEDENT_CONDITIONS = ("warm", "cold")


def _precedent_conditions(receipt: dict[str, Any]) -> dict[str, Any]:
    """Fetch both study conditions, refusing a receipt that carries only one.

    The console page reads ``conditions.warm`` and ``conditions.cold`` by name and its
    types declare both, so a receipt missing one would render an empty column rather than
    an absence: the same defect as publishing a null in place of a measurement.
    """
    conditions = _require(receipt, "conditions")
    for name in _PRECEDENT_CONDITIONS:
        if name not in conditions:
            raise KeyError(
                f"precedent receipt has no {name!r} condition; present are "
                f"{sorted(conditions)}. The console declares both by name, so a missing "
                "one would render as an empty column instead of as an absence."
            )
        _require(conditions, name)
    return conditions


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

    out["geometry"] = build_pass_geometry(record)

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

    # A missing corridor fit must not be published as a measured zero offset.
    # corridor_features.json is built over decisive observations only (743 of
    # 2,500), so any queue entry ranked below the decisive pool has no corridor
    # row.  Showing fitted_px == predicted_px with a zero offset and the caption
    # "the gap between them is the measurement" fabricates a zero measurement.
    # Return a named absence instead so the console can render a stated reason.
    if corridor_row is None or corridor_row.get("fitted_offset_hz") is None:
        out["corridor_note"] = (
            "No corridor fit exists for this observation: it is outside the "
            "decisive pool corridor_features.json was built over, so there is "
            "no fitted offset to draw. The predicted curve is not shown alone, "
            "because one curve under this caption reads as a measured zero."
        )
        return out

    offset_hz = float(corridor_row["fitted_offset_hz"])
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
        "fitted_offset_ppm": corridor_row.get("fitted_offset_ppm"),
        "offset_at_bound": corridor_row.get("offset_at_bound"),
        "half_width_px": half_width_px,
        "half_width_hz": physics.uncorrected.half_width_hz,
        "max_elevation_deg": physics.uncorrected.max_elevation_deg,
        "tca_frac": physics.uncorrected.tca_frac,
        "rows": rows,
        "fitted_px": [round(float(fitted[r]), 2) for r in rows],
        "predicted_px": [round(float(unshifted[r]), 2) for r in rows],
        "vertical_px": geometry.centre_px,
        "sigma_curved": corridor_row.get("sigma_curved"),
        "sigma_vertical": corridor_row.get("sigma_vertical"),
        "note": (
            "fitted_px is the predicted Doppler curve shifted by the fitted "
            "frequency offset, which is the path the matched filter scored. "
            "predicted_px is the same curve at zero offset, so the gap between "
            "them is the measurement. Time runs bottom to top: row 0 is the end "
            "of the pass. The frequency axis runs against the Doppler sign."
        ),
    }
    return out



def build_pass_geometry(record: dict[str, Any]) -> dict[str, Any] | None:
    """The pass as a sky track and a ground track, or a named reason it is absent.

    Returned separately from the corridor because the two need different things.
    The corridor needs a frequency axis, which about 6% of records cannot supply;
    the sky track needs only a station and a TLE. Withholding the sky plot for a
    missing centre pixel would hide geometry that was computed successfully.

    The series are subsampled to roughly 90 points. A polyline drawn at 512
    samples and a polyline drawn at 90 are the same curve on a 400 px plot, and
    the difference is 8 kB per card over the wire.
    """
    tle1, tle2 = record.get("tle1"), record.get("tle2")
    lat, lon = record.get("station_lat"), record.get("station_lng")
    if not tle1 or not tle2:
        return {"degraded": "no TLE on the record, so the pass cannot be propagated"}
    if lat is None or lon is None:
        return {"degraded": "no station coordinates, so there is no local horizon"}

    try:
        start_dt = datetime.datetime.fromisoformat(str(record["start"]).replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(str(record["end"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return {"degraded": "the pass window could not be parsed"}
    if end_dt <= start_dt:
        return {"degraded": "the pass window is not ordered"}

    alt_m = float(record.get("station_alt") or 0.0)
    try:
        geom = pass_geometry(
            tle1, tle2, start_dt, end_dt,
            station_ecef(float(lat), float(lon), alt_m),
            geodetic_normal(float(lat), float(lon)),
        )
    except Exception as exc:                      # noqa: BLE001 - reported, not raised
        return {"degraded": f"propagation failed: {type(exc).__name__}"}

    if len(geom.fracs) < 8:
        return {
            "degraded": (
                f"only {len(geom.fracs)} of the samples propagated, which is too "
                "few to draw a track"
            )
        }

    step = max(1, len(geom.fracs) // 90)
    keep = list(range(0, len(geom.fracs), step))
    if keep[-1] != len(geom.fracs) - 1:
        keep.append(len(geom.fracs) - 1)

    def take(series: list[float], nd: int) -> list[float]:
        return [round(float(series[i]), nd) for i in keep]

    # The Doppler shift at each sample, from the same range rate the pipeline
    # negates. Withheld rather than zeroed when the record has no receive
    # frequency: a Doppler curve of zeros is a measurement that says the satellite
    # never moved, and about 6% of records genuinely cannot supply the frequency.
    rx_freq = rx_freq_of(record)
    if rx_freq is None or rx_freq <= 0.0:
        doppler = None
    else:
        doppler = [
            round(-geom.range_rate_km_s[i] * 1_000.0 / C_M_PER_S * rx_freq, 1)
            for i in keep
        ]

    i_tca = int(max(range(len(geom.elevation_deg)), key=lambda i: geom.elevation_deg[i]))
    return {
        "degraded": None,
        "station_lat": round(float(lat), 4),
        "station_lon": round(float(lon), 4),
        "station_alt_m": alt_m,
        "fracs": take(geom.fracs, 4),
        "azimuth_deg": take(geom.azimuth_deg, 2),
        "elevation_deg": take(geom.elevation_deg, 3),
        "sub_lat_deg": take(geom.sub_lat_deg, 4),
        "sub_lon_deg": take(geom.sub_lon_deg, 4),
        "altitude_km": take(geom.altitude_km, 1),
        "range_km": take(geom.range_km, 1),
        "doppler_hz": doppler,
        "max_elevation_deg": round(float(geom.elevation_deg[i_tca]), 3),
        "tca_frac": round(float(geom.fracs[i_tca]), 4),
        "tca_azimuth_deg": round(float(geom.azimuth_deg[i_tca]), 2),
        "min_range_km": round(float(min(geom.range_km)), 1),
        "n_samples_propagated": len(geom.fracs),
        "n_sgp4_errors": len(geom.error_codes),
        "doppler_note": (
            "doppler_hz is null when the record carries no receive frequency, which "
            "is the same reason the corridor overlay is withheld on those records. "
            "It is not zero, because zero would be a claim."
        ),
        "note": (
            "Elevation is measured from the WGS-84 geodetic normal at the station, "
            "which is the same reference the corridor was scored against. Azimuth "
            "runs clockwise from true north. The subsatellite point is a geodetic "
            "latitude, not a geocentric one."
        ),
    }


# Gate 1 and gate 2 were decided in a document rather than in a machine-readable
# receipt, on feasibility counts, so their statuses are declared here with the
# document that decided each one named beside it.
#
# Gates 3, 4, 5 and 6 are not declared. Gate 4 was, as a literal `OPEN`, until a
# review pointed out what that costs: its receipt has existed since the blinded
# worksheet was built, so answering the worksheet would have changed the receipt and
# changed nothing any reader sees, and someone would have had to notice and edit this
# file, `sync_kill_gate.py` and a paragraph of `sync_for_judges.py` by hand. That is
# the same defect this file already carries a comment about for gate 3.
#
# Gates 5 and 6 are not declared. They are read from the receipts, and
# ``build_gate_summary`` refuses to run if a receipt's verdict is not one of the
# four the rest of the console knows how to render. That keeps the tally the rail
# shows from drifting away from the receipts the way a hand-typed count would: the
# only way to change "3 of 6" is to change a gate.
_DECIDED_IN_DOCS: list[dict[str, Any]] = [
    {
        "gate": 1,
        "title": "Dataset volume and entity spread",
        "verdict": "PRE_PASSED",
        "decided_in": "docs/KILL_GATE.md",
    },
    {
        "gate": 2,
        "title": "Metadata coverage for the corridor",
        "verdict": "PRE_PASSED",
        "decided_in": "docs/KILL_GATE.md",
    },
]

# The receipt's word for "the instrument exists and nobody has used it" is NOT_RUN, and
# the console's word for the same state is OPEN. One mapping, declared once, rather than
# three files that happen to agree. Every other verdict passes through unchanged, so the
# day the worksheet is answered this file needs no edit at all.
_RECEIPT_TO_CONSOLE = {"NOT_RUN": "OPEN"}

_MET = frozenset({"PASSED", "PRE_PASSED"})
_KNOWN_VERDICTS = _MET | {"NOT_ESTABLISHED", "FAILED", "NOT_MEASURABLE", "OPEN"}


def _gate4_arm() -> dict[str, Any] | None:
    """What gate 4's receipt measured, if anything, with who measured it attached.

    Returns None while the worksheet is unanswered, so the page renders nothing rather
    than a section full of zeros. The reviewer travels with the numbers on purpose: these
    two are one fact, and a rate whose reviewer is one import away is a rate that gets
    quoted without them.
    """
    receipt = json.loads(
        (_ARTIFACTS / "GATE4_RECEIPT.json").read_text(encoding="utf-8")
    )
    arm = receipt.get("arm")
    if not arm:
        return None
    axes = arm["network_label_agreement"]["by_axis"]
    return {
        "verdict": arm["verdict"],
        "observations_scored": arm["observations_scored"],
        "decisive": arm["decisive"],
        "rate": arm["rate"],
        "rate_lower_bound_95": arm["rate_lower_bound_95"],
        "rate_upper_bound_95": arm["rate_upper_bound_95"],
        "not_decisive_items": arm["not_decisive_items"],
        "intra_rater": arm["intra_rater"],
        "label_agreement": {
            "neither_axis_asks_the_network_question": arm["network_label_agreement"][
                "neither_axis_asks_the_network_question"
            ],
            "by_axis": axes,
        },
        "reviewer": arm["reviewer"],
        "gate_verdict_is_not_this": receipt["verdict"],
        "why_the_gate_is_still_open": receipt["why"],
    }


def _load_receipt_verdict(path: Path, *, gate: int, title: str) -> dict[str, Any]:
    """One gate's verdict, read from its own receipt rather than typed here.

    Gate 3's receipt carries a verdict of NOT_ESTABLISHED: every one of its three
    testable observations discriminates, and three successes in three trials cannot
    establish the 70 percent rate the gate asked for, because the exact one-sided
    95 percent lower bound is 0.368. The point estimate and the bound are both
    published so a reader can see that the per-observation evidence is strong and
    the rate claim is what failed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"gate {gate} receipt missing at {path}. A gate with a receipt must not "
            f"be published from a literal in this file."
        )
    receipt = json.loads(path.read_text(encoding="utf-8"))
    recorded = _require(receipt, "verdict")
    verdict = _RECEIPT_TO_CONSOLE.get(recorded, recorded)
    if verdict not in _KNOWN_VERDICTS:
        raise ValueError(
            f"gate {gate} carries verdict {verdict!r}, which the console does not "
            f"know how to count. Known verdicts: {sorted(_KNOWN_VERDICTS)}."
        )
    return {
        "gate": gate,
        "title": title,
        "verdict": verdict,
        "decided_in": str(path.relative_to(_REPO)).replace("\\", "/"),
    }


def build_gate_summary(queue: dict[str, Any], fusion: dict[str, Any]) -> dict[str, Any]:
    """The gate tally, with gates 5 and 6 taken from their receipts.

    A count of gates met is the single most quotable number on this console, which
    is exactly why it is not typed anywhere. Two of the six come straight from the
    receipts; an unrecognised verdict raises rather than being quietly counted as
    not met, because silently reading a new verdict as a failure would let the
    console understate its own result without anyone noticing.
    """
    gates = list(_DECIDED_IN_DOCS)

    # Gate 3 has a receipt and was still being published from a string typed into
    # this file. That is the failure mode the whole project is built against: the
    # console said PASSED because a literal here said PASSED, not because anything
    # read the measurement. When gate 3's verdict changed to NOT_ESTABLISHED in the
    # receipt, this file kept publishing PASSED and the gate tally kept counting it
    # as met. Read from the receipt like gates 5 and 6, and insert it in order.
    gate3 = _load_receipt_verdict(
        _REPO / "artifacts/GATE3_RECEIPT.json",
        gate=3,
        title="Corridor intersects a visible trace",
    )
    gates.append(gate3)

    # Gate 4 the same way. Its receipt is written by `scripts/score_gate4.py`, which
    # refuses to write anything at all unless every image on disk re-hashes to the
    # digest its commitment was taken over, so a verdict here is one that was scored
    # against the sample that was committed to.
    gates.append(
        _load_receipt_verdict(
            _REPO / "artifacts/GATE4_RECEIPT.json",
            gate=4,
            title="Blinded human decidability",
        )
    )
    gates.sort(key=lambda g: g["gate"])

    for number, receipt, key, title in (
        (5, fusion, "gate5", "Physics beats image-only on Brier"),
        (6, queue, "gate6", "Queue lift over random"),
    ):
        block = _require(receipt, key)
        verdict = block.get("verdict")
        if verdict not in _KNOWN_VERDICTS:
            raise ValueError(
                f"gate {number} carries verdict {verdict!r}, which the console does "
                f"not know how to count. Known verdicts: {sorted(_KNOWN_VERDICTS)}."
            )
        gates.append({
            "gate": number,
            "title": title,
            "verdict": verdict,
            "decided_in": f"artifacts/{'FUSION' if number == 5 else 'QUEUE'}_RECEIPT.json",
        })

    for gate in gates:
        if gate["verdict"] not in _KNOWN_VERDICTS:
            raise ValueError(f"gate {gate['gate']} has an unknown verdict")

    return {
        "gates": gates,
        "n_gates": len(gates),
        "n_met": sum(1 for g in gates if g["verdict"] in _MET),
        "note": (
            "Met counts a gate that was passed or pre-passed. It deliberately does "
            "not count NOT_ESTABLISHED, which is a measurement that came back "
            "inconclusive rather than a threshold that was cleared, and it does not "
            "count OPEN, which is a study that was never run."
        ),
    }


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


def _split_for_console(split: dict[str, Any]) -> dict[str, Any]:
    """Project one fusion split for the console, mirroring the contract's conditional.

    ``contracts/fusion_receipt.schema.json`` requires ``split``, ``degraded`` and
    ``counts`` outright, and adds ``arms`` and ``comparisons`` when ``degraded`` is
    null. The four remaining measured blocks are optional in the contract because a
    degraded split cannot have them, not because a clean split may drop them: all
    five shipped splits carry every one. So a clean split is required to carry them
    here, and a rename in the receipt becomes a failed build rather than a page
    section that quietly disappears.
    """
    degraded = _require_present(split, "degraded")
    clean = degraded is None

    def strict(key: str) -> Any:
        """Present and non-empty on a clean split."""
        return _require(split, key) if clean else split.get(key)

    def present(key: str) -> Any:
        """Present on a clean split, where empty is itself the measurement.

        multiplicity_adjusted is measured-and-empty in two of the five splits, and
        the empty map is the result: run_fusion.py adds an entry only for a
        comparison whose nominal interval cleared zero in either direction, so {}
        means no comparison in that split needed correcting. _require would read
        that as an absence and fail the build over a real measurement, which is the
        same error pointing the other way.
        """
        return _require_present(split, key) if clean else split.get(key)

    # Key order matches what this export has always written, so the diff on
    # evaluation.json shows the change in policy and not a reshuffle.
    return {
        "split": _require(split, "split"),
        "degraded": degraded,
        "counts": _require(split, "counts"),
        "test_positive_rate": strict("test_positive_rate"),
        "arms": strict("arms"),
        "comparisons": strict("comparisons"),
        "multiplicity_adjusted": present("multiplicity_adjusted"),
        # Optional in the contract and present in every split we ship. Read with
        # .get() because a future arm could legitimately have no ensemble to report,
        # and because neither is load-bearing for a section of the page.
        "ensemble": split.get("ensemble"),
        "selective": strict("selective"),
        "ood": split.get("ood"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--showcase", type=int, default=DEFAULT_SHOWCASE)
    parser.add_argument(
        "--skip-images",
        action="store_true",
        help=(
            "rebuild every JSON except cards.json, leaving existing imagery in "
            "place. cards.json is not JSON-only: export_observation parses each "
            "waterfall PNG for its geometry, so it needs the snapshot images."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="write the JSON somewhere other than apps/web/public/data",
    )
    args = parser.parse_args(argv)

    # Where the JSON lands. It is an argument so the freshness check can rebuild the
    # published data into a scratch directory and diff it, which is how a stale
    # published copy is caught: apps/web/public/data/hero_nulls.json stayed three
    # times too heavy for a commit after artifacts/HERO_NULLS.json was corrected,
    # because nothing compared the copy against its source.
    data_dir = args.data_dir or _DATA_DIR

    queue = _load("QUEUE_RECEIPT.json")
    fusion = _load("FUSION_RECEIPT.json")
    circularity = _load("CIRCULARITY_RECEIPT.json")
    manifest = _load("SPLIT_MANIFEST.json")
    corridor = _load("corridor_features.json")
    corridor_by_obs = {r["obs_id"]: r for r in corridor["rows"]}

    data_dir.mkdir(parents=True, exist_ok=True)

    # ---- queue -----------------------------------------------------------
    entries = [trim_queue_entry(e) for e in queue["queue"]]
    (data_dir / "queue.json").write_text(
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
        newline="\n",
    )

    # ---- evaluation ------------------------------------------------------
    (data_dir / "evaluation.json").write_text(
        json.dumps(
            {
                "gate6": queue["gate6"],
                # The bound on gate 6, shipped alongside it rather than a click away.
                # A lift measured on a ranking built from the quantities that define
                # the target needs its ceiling and its permutation test on the same
                # page as the lift, or the page is publishing the flattering half.
                "circularity": {
                    # The population, the conflicts and the budget the bound is
                    # computed over. Without them the console had no field holding 87
                    # and the lede reached for the review budget instead, printing "a
                    # budget of 50 over 50 caps every possible ordering at 1.740x",
                    # which is arithmetically impossible and sat on the landing page.
                    "reproduction": circularity["reproduction"],
                    "ceiling": circularity["ceiling"],
                    "ceilings_by_split": circularity["ceilings_by_split"],
                    "targets": circularity["targets"],
                    "targets_note": circularity["targets_note"],
                    "shared_signals": circularity["shared_signals"],
                    "random_ordering_control": circularity["random_ordering_control"],
                    "what_this_does_not_establish": circularity[
                        "what_this_does_not_establish"
                    ],
                    "receipt_sha256": _digest(
                        _ARTIFACTS / "CIRCULARITY_RECEIPT.json"
                    ),
                },
                "gate5": _require(fusion, "gate5"),
                "ablation_conclusion": _require(fusion, "ablation_conclusion"),
                "arm_ladder": _require(fusion, "arm_ladder"),
                "size_matched_control": _require(fusion, "size_matched_control"),
                # Per-split arm metrics, comparisons and the selective-rejection
                # curve all live inside the split records rather than at the root.
                # Every field here was read with .get(), so the contract's own
                # conditional was not mirrored: five measured blocks could be
                # renamed in the receipt, validate, and be published as null. The
                # page then differed by field. A missing selective curve removed
                # the whole risk and coverage section with no note and no warning
                # tone, while a missing arms block threw during the export, which
                # is at least loud. The rule below is the contract's rule: a split
                # that is not degraded must carry its results, and only ensemble
                # and ood are genuinely optional.
                "fusion_splits": [_split_for_console(s) for s in _require(fusion, "splits")],
                # Gate 4's arm, or null while nobody has answered the worksheet. The
                # gate's own verdict is not here and is not derived from this: it comes
                # from `gate_summary` like every other gate, which is what keeps a review
                # by something that is not a person from being published as the gate.
                "gate4_arm": _gate4_arm(),
                "receipt_sha256": {
                    "queue": _digest(_ARTIFACTS / "QUEUE_RECEIPT.json"),
                    "fusion": _digest(_ARTIFACTS / "FUSION_RECEIPT.json"),
                    "gate4": _digest(_ARTIFACTS / "GATE4_RECEIPT.json"),
                },
            },
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
    )

    # ---- agent study -----------------------------------------------------
    #
    # The pairing is joined here rather than in the console. A page that matched the two arms
    # by index, or by re-sorting them, would be a second implementation of the study's own
    # design, and the receipt already did it: every question carries both answers and the
    # grades that go with them.
    agent = _load("AGENT_RECEIPT.json")
    agent_by_arm: dict[str, dict[str, Any]] = {"tools": {}, "control": {}}
    for row in agent["per_run"]:
        agent_by_arm[row["arm"]][row["task_id"]] = row
    if set(agent_by_arm["tools"]) != set(agent_by_arm["control"]):
        raise SystemExit(
            "the agent receipt has a question in one arm and not the other, so the pairing it "
            "reports cannot be published"
        )
    questions = []
    for task in sorted(agent_by_arm["tools"]):
        tools_row = agent_by_arm["tools"][task]
        control_row = agent_by_arm["control"][task]
        questions.append(
            {
                "task_id": task,
                "question": tools_row["question"],
                "expected": tools_row["expected"],
                "tools_answer": tools_row["answer"],
                "tools_correct": tools_row["correct"],
                "tools_grounded": tools_row["grounded"],
                "tools_calls": tools_row["tool_calls"],
                "tools_fetched_the_answer": tools_row["answer_was_in_what_it_read"],
                "control_answer": control_row["answer"],
                "control_correct": control_row["correct"],
                "control_grounded": control_row["grounded"],
            }
        )
    (data_dir / "agent.json").write_text(
        json.dumps(
            {
                "design": agent["design"],
                "model": agent["model"],
                "tasks": agent["tasks"],
                "max_steps": agent["max_steps"],
                "arms": agent["arms"],
                "paired": agent["paired"],
                "questions": questions,
                "what_this_does_not_measure": agent["what_this_does_not_measure"],
                "receipt_sha256": _digest(_ARTIFACTS / "AGENT_RECEIPT.json"),
            },
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
    )

    # ---- precedent -------------------------------------------------------
    #
    # Two things in one file, because they are two views of one study: the arm and condition
    # table a reader checks, and the neighbour lists a reviewer looks at on an observation. The
    # lists are read from the frozen retrievals rather than recomputed, so the console needs no
    # index, no model and no snapshot, and the page cannot show a neighbour the receipt did not
    # score.
    precedent = _load("PRECEDENT_RECEIPT.json")
    retrievals = json.loads(
        (_REPO / "tests" / "fixtures" / "precedent_retrievals.json").read_text(encoding="utf-8")
    )
    console_precedent = retrievals.get("console_precedent") or {}
    # The shipped ids come from the cards file on disk rather than from a local variable,
    # because this block runs before the cards are rebuilt and does not run at all under
    # --skip-images. Reading the committed file is the same set either way.
    shipped_path = data_dir / "cards.json"
    shipped = (
        {
            str(int(card["obs_id"]))
            for card in json.loads(shipped_path.read_text(encoding="utf-8"))["cards"]
        }
        if shipped_path.exists()
        else set(console_precedent)
    )
    missing = sorted(shipped - set(console_precedent))
    conditions = _precedent_conditions(precedent)
    (data_dir / "precedent.json").write_text(
        json.dumps(
            {
                "question": _require(precedent, "question"),
                "design": _require(precedent, "design"),
                "embedding_model": _require(precedent, "embedding_model"),
                "top_k": _require(precedent, "top_k"),
                "feature_names": _require(precedent, "feature_names"),
                "vector_index": _require(precedent, "vector_index"),
                "candidate_pool": _require(precedent, "candidate_pool"),
                "conditions": conditions,
                "what_this_does_not_measure": _require(
                    precedent, "what_this_does_not_measure"
                ),
                "neighbours": console_precedent,
                "observations_without_neighbours": missing,
                "why_some_have_none": (
                    "A shipped observation only has neighbours here if the snapshot gave it a "
                    "decisive network label, because the study measures agreement with that "
                    "label and an unknown one cannot be agreed with. The ids are listed rather "
                    "than dropped."
                ),
                "receipt_sha256": _digest(_ARTIFACTS / "PRECEDENT_RECEIPT.json"),
            },
            indent=1,
        ),
        encoding="utf-8",
        newline="\n",
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

    # The dataset manifest, for the licence terms it recorded at snapshot time. Read
    # here rather than typed, because the licence a snapshot was taken under is a
    # property of that snapshot.
    dataset_manifest = json.loads(
        (_ARTIFACTS / "DATASET_MANIFEST.json").read_text(encoding="utf-8")
    )

    # Keyed on the POSIX string: sorting Path objects is case-insensitive on Windows and
    # case-sensitive on POSIX, and this list is written into the committed provenance.json,
    # so without the key the file's row order depended on which machine built it.
    receipts = sorted(_ARTIFACTS.glob("*.json"), key=lambda p: p.as_posix())
    (data_dir / "provenance.json").write_text(
        json.dumps(
            {
                "snapshot_id": queue["snapshot_id"],
                "split_manifest_sha256": queue["split_manifest_sha256"],
                # The data licence, read from the snapshot manifest rather than typed.
                # The console's own colophon already credits SatNOGS and links the
                # licence, so this is not the only place a reader can find it. It is here
                # because the attribution audit reads the receipts, and an obligation
                # that lives only in rendered markup cannot be checked by a script.
                "data_licence": {
                    "name": _require(dataset_manifest, "license"),
                    "url": _require(dataset_manifest, "license_url"),
                    "attribution": (
                        "Contains data from the SatNOGS Network "
                        "(https://network.satnogs.org), (c) SatNOGS contributors, "
                        "licensed CC BY-SA 4.0."
                    ),
                    "obligations": "DATA_LICENSE.md",
                },
                "gate_summary": build_gate_summary(queue, fusion),
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
        newline="\n",
    )

    # ---- documents rendered in the console -------------------------------
    for name in ("KILL_GATE.md", "CLAIM_REGISTER.md", "C2_PREREGISTRATION.md"):
        source = _REPO / "docs" / name
        if source.exists():
            shutil.copyfile(source, data_dir / name)

    # ---- the opening frame's null corridors -------------------------------
    # Copied rather than recomputed. scripts/export_hero_nulls.py re-runs gate 3's
    # own fit and refuses to write unless seven statistics of the null distribution
    # reproduce GATE3_RECEIPT.json exactly, so the paths in this file are the paths
    # that were scored. Recomputing them here would be a second implementation of a
    # measurement, which is the thing this console exists to argue against.
    hero_nulls = _REPO / "artifacts/HERO_NULLS.json"
    if not hero_nulls.exists():
        raise FileNotFoundError(
            f"{hero_nulls} is missing. Run scripts/export_hero_nulls.py. The opening "
            f"frame draws measured null corridors and there is no fallback that "
            f"would still be a measurement."
        )
    shutil.copyfile(hero_nulls, data_dir / "hero_nulls.json")

    # ---- observation cards ----------------------------------------------
    if args.skip_images:
        print("skipping imagery and cards.json (it needs the waterfall PNGs)")
        return 0

    raw = _load_raw_pages(_default_pages_dir())
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
    (data_dir / "cards.json").write_text(
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
        newline="\n",
    )

    total_kb = sum(c.get("bytes", 0) for c in built) // 1024
    print(f"\n{len(built)} cards built, {len(cards) - len(built)} degraded")
    print(f"imagery total {total_kb} KB")
    print(f"data written to {data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
