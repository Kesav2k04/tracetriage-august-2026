"""Measure one SatNOGS observation that is not in the snapshot, including one from today.

Everything else in this package reads the frozen snapshot: 2,727 observations taken on
2026-08-17, with every waterfall on disk and every number in a receipt. That is the right
shape for a claim, because a measurement nobody can re-run is not evidence. It is the
wrong shape for a person. A station operator wondering whether last night's pass was off
frequency, or a researcher pointing an agent at a satellite, has an observation id and no
snapshot, and nothing in this repository could take one.

This module takes one. Given an observation id it fetches the record and the waterfall
from the public SatNOGS API, propagates the pass from the TLE the observation itself
carries, derives the frequency axis from the image's own rendered ticks, and runs the same
bounded offset fit and the same own-Doppler null distribution that gate 3 is scored with.

**It reuses the measurement rather than reimplementing it.** `physics.corridor_for_obs`,
`waterfall.parse_waterfall`, `corridor_fit.normalised_rows`, `corridor_fit.fit_offset` and
`corridor_fit.calibrate_against_nulls` are the same functions `scripts/run_gate3.py` calls,
in the same order, with the same thresholds. A second implementation of a measurement is
two measurements, and the whole point of this project is that there is one.

**No credential, ever.** The SatNOGS read API is public and this was verified rather than
assumed: `docs/SATNOGS_API_RECON.md` carries the recon, and `.env.example` says there is no
key here and there must never be one. The only thing sent is a User-Agent naming the
project and a contact address, and a courtesy interval between requests.

**What it refuses to do.** Every failure is a named reason code and never a substituted
default, because a triage tool that guesses is worse than one that declines:

* `NOT_FOUND` the API has no such observation.
* `NO_WATERFALL` the observation has no waterfall image. Nothing here can be measured
  from metadata alone, and an observation without an image is most of what the network
  produces.
* `PHYSICS_*` `corridor_for_obs` declined, carrying its own reason: no TLE, an
  unusable TLE, no station position, no receive frequency.
* `NO_AXIS` the frequency axis could not be derived from the image. This is a hard stop
  rather than a fallback: the corridor is placed in Hz and converted to columns, so
  without Hz per pixel there is no position to score, and the waterfall does not span
  the client's sample rate, so metadata cannot supply one either. That was measured, not
  supposed.
* `NO_CENTRE` the receive frequency is missing, so the axis has no origin.
* `NO_FIT` no candidate offset inside the bound kept the path on the plot.

**What the number means, and what it does not.** The offset is how far the trace sits from
where this satellite's orbit says it should be, in Hz and in parts per million of the
downlink. It is not a calibration certificate for a station: it carries the TLE's own error,
the axis derivation's error, and the fit's. The sigma is only comparable against the null
sigmas returned beside it, computed by the same estimator on the same rows, which is why
they are returned together and never separately.
"""

from __future__ import annotations

import dataclasses
import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import numpy as np

from . import corridor_fit as cf
from . import doppler_mode as dm
from . import snapshot
from .physics import corridor_for_obs, rx_freq_of
from .snapshot import normalise_client_family
from .waterfall import parse_waterfall

#: The public read API. No key, no account, no write verb anywhere in this module.
API_ROOT = "https://network.satnogs.org/api"

#: Seconds between requests. The snapshot builder uses the same figure and the reason is
#: the same: the network is volunteers' hardware and their bandwidth.
REQUEST_INTERVAL_S = 0.4

#: A TLE older than this at the pass midpoint is reported, not rejected. Nothing here
#: knows what "too old" is for an arbitrary orbit, so the age is published and the caller
#: decides. Stated because silently dropping stale-TLE observations would bias any
#: aggregate computed from what survives.
TLE_AGE_NOTE_DAYS = 7.0


class LiveRefusal(Exception):
    """A named reason this observation cannot be measured.

    Carries the code rather than a message so a caller can branch on it, and an agent
    can report it as a state of the world instead of as a tool failure.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# What it means when the null test did not run. The four keys are the four branches
# in `corridor_fit.calibrate_against_nulls` that return zero nulls, and they carry
# different weight: two are refusals the method makes on purpose and two are
# failures to measure. Folding them together would let a caller read a refusal as a
# breakage, or quote a sigma with no p-value and no reason for its absence.
_NOT_TESTED_READING = {
    "flat_corridor": (
        "No null test is possible here and none is missing. The station "
        "Doppler-corrected this capture, so the predicted corridor is 0 Hz across the "
        "whole pass, and permuting a flat curve in time reproduces it exactly: every "
        "null would equal the hypothesis. The offset is still measured, and for a "
        "station operator it is the more useful number, because the orbit is already "
        "taken out of it."
    ),
    "swing_below_floor": (
        "The null test was refused, not attempted. This pass swings less than the "
        "3 kHz floor, and a permutation of nearly-equal Doppler values is nearly the "
        "same path, so truth and null both collapse into noise and a significant "
        "p-value can come out of pixel quantisation alone. Treat the sigma as "
        "uncalibrated."
    ),
    "no_offset_fit": (
        "The null test could not run because the true corridor itself did not fit: no "
        "offset inside the bound produced a finite score. This is a measurement "
        "failure rather than a negative result, and nothing here should be read as "
        "evidence either way."
    ),
    "no_null_scored": (
        "The null test could not run because no scrambled corridor produced a finite "
        "score, so there is no distribution to compare against. A measurement failure, "
        "not a negative result."
    ),
    "mode_unresolved": (
        "No null test was reached. The corrected and uncorrected hypotheses were not "
        "separated by the required margin, so no corridor was selected to test, and "
        "fitting one of them anyway would be choosing the answer before measuring it."
    ),
}


@dataclass(frozen=True)
class LiveMeasurement:
    """One observation, measured now, with everything needed to re-derive it."""

    observation_id: int
    norad_cat_id: int | None
    satellite: str | None
    station: int | None
    station_name: str | None
    start: str | None
    end: str | None
    status: str | None
    waterfall_status: str | None
    client_family: str | None

    rx_freq_hz: float | None
    max_elevation_deg: float | None
    tle_epoch_age_days: float | None
    pass_duration_s: float | None

    hz_per_px: float | None
    axis_derivation: str | None
    axis_confidence: float | None

    mode: str
    mode_reason: str
    sigma_curved: float | None
    sigma_vertical: float | None
    frequency_axis_sign: int | None
    corridor_type: str | None

    offset_hz: float | None
    offset_ppm: float | None
    offset_px: float | None
    at_bound: bool | None
    bound_hz: float | None
    sigma: float | None

    n_nulls: int | None
    null_median: float | None
    null_p95: float | None
    null_max: float | None
    n_nulls_at_least: int | None
    p_value: float | None
    # Which of the ways a null test can fail to run happened, or None when it ran.
    # `n_nulls == 0` alone does not say whether the test was refused or broke.
    nulls_not_tested: str | None

    doppler_swing_hz: float | None
    fit_detail: dict[str, Any] | None
    null_detail: dict[str, Any] | None
    second_trace: dict[str, Any] | None
    provenance: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "LIVE_MEASUREMENT",
            "schema_version": 1,
            "observation": {
                "id": self.observation_id,
                "norad_cat_id": self.norad_cat_id,
                "satellite": self.satellite,
                "station": self.station,
                "station_name": self.station_name,
                "start": self.start,
                "end": self.end,
                "status": self.status,
                "waterfall_status": self.waterfall_status,
                "client_family": self.client_family,
            },
            "pass": {
                "rx_freq_hz": self.rx_freq_hz,
                "max_elevation_deg": self.max_elevation_deg,
                "tle_epoch_age_days": self.tle_epoch_age_days,
                "duration_s": self.pass_duration_s,
                "doppler_swing_hz": self.doppler_swing_hz,
                "swing_reading": (
                    "The pass's own predicted Doppler swing, 5th to 95th percentile so "
                    "one propagation outlier at the horizon cannot make a grazing pass "
                    "look testable. Below {} Hz the two shapes are not "
                    "distinguishable and the verdict above is UNRESOLVED for that reason "
                    "alone. Always the uncorrected curve's swing, whichever corridor was "
                    "scored: this describes the pass, not the hypothesis."
                ).format(f"{dm.MIN_PREDICTED_SWING_HZ:,.0f}"),
            },
            "axis": {
                "hz_per_px": self.hz_per_px,
                "derivation": self.axis_derivation,
                "confidence": self.axis_confidence,
            },
            "mode": {
                "verdict": self.mode,
                "why": self.mode_reason,
                "sigma_curved": self.sigma_curved,
                "sigma_vertical": self.sigma_vertical,
                "frequency_axis_sign": self.frequency_axis_sign,
                "corridor_scored": self.corridor_type,
                "reading": (
                    "Whether this station Doppler-corrected the capture, measured rather "
                    "than looked up. An uncorrected capture draws the pass's whole "
                    "S-curve and a corrected one draws a near-vertical line, so the two "
                    "shapes are scored against each other at three filter widths and a "
                    "verdict is only given when all three agree and one leads by "
                    f"{dm.SIGMA_MARGIN:.0f} sigma. UNRESOLVED means the image does not "
                    "settle it, which on a real queue is the common case and is the "
                    "answer that says skip this one."
                ),
            },
            "measurement": {
                "offset_hz": self.offset_hz,
                "offset_ppm": self.offset_ppm,
                "offset_px": self.offset_px,
                "at_search_bound": self.at_bound,
                "search_bound_hz": self.bound_hz,
                "sigma": self.sigma,
                "fit": self.fit_detail,
                "reading": (
                    "How far the trace sits from where this satellite's orbit says it "
                    "should be. The sigma is in units of this estimator's own null "
                    "spread and is comparable only against the null figures below."
                ),
            },
            "nulls": {
                "n": self.n_nulls,
                "median": self.null_median,
                "p95": self.null_p95,
                "max": self.null_max,
                "n_at_least_true": self.n_nulls_at_least,
                "p_value": self.p_value,
                "not_tested": self.nulls_not_tested,
                "detail": self.null_detail,
                "reading": (
                    "Each null keeps every Doppler value and the whole swing of this "
                    "pass and destroys only the time order, then gets the same bounded "
                    "offset search the true corridor gets. So the margin is over curves "
                    "built from this observation's own physics, not over noise."
                    if self.nulls_not_tested is None
                    else _NOT_TESTED_READING[self.nulls_not_tested]
                ),
            },
            "second_trace": self.second_trace,
            "provenance": self.provenance,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def make_client(timeout: float = 30.0):
    """The snapshot builder's own client: its User-Agent, its redirects, its timeout."""
    return snapshot.make_client(timeout)


def fetch_observation(obs_id: int, client, *, interval_s: float = REQUEST_INTERVAL_S) -> dict:
    """One observation record from the public API.

    The `id=` filter is used rather than the detail route because the list route is what
    `docs/SATNOGS_API_RECON.md` measured, and it returns the same record shape the
    snapshot builder stored, which is the shape every function downstream expects.
    """
    url = f"{API_ROOT}/observations/?format=json&id={int(obs_id)}"
    resp = snapshot.get_with_retry(client, url, timeout=30.0)
    if resp.status_code == 404:
        raise LiveRefusal("NOT_FOUND", f"observation {obs_id}")
    resp.raise_for_status()
    payload = resp.json()
    records = payload if isinstance(payload, list) else payload.get("results", [])
    match = [r for r in records if int(r.get("id", -1)) == int(obs_id)]
    if not match:
        raise LiveRefusal("NOT_FOUND", f"observation {obs_id}")
    time.sleep(interval_s)
    return match[0]


def fetch_waterfall(url: str, client) -> bytes:
    """The waterfall image, from wherever the network stored it.

    The URL comes out of the record rather than being constructed, because the storage
    host has changed at least once in the network's history and a constructed URL would
    be a second source of truth for where an image lives.
    """
    resp = snapshot.get_with_retry(client, url, timeout=60.0)
    if resp.status_code == 404:
        raise LiveRefusal("NO_WATERFALL", "the stored image is gone")
    resp.raise_for_status()
    if not resp.content:
        raise LiveRefusal("NO_WATERFALL", "the stored image is empty")
    return resp.content


def list_observations(
    client,
    *,
    norad_cat_id: int | None = None,
    ground_station: int | None = None,
    status: str | None = None,
    start_after: datetime | None = None,
    limit: int = 50,
    require_waterfall: bool = False,
    max_pages: int = 12,
    interval_s: float = REQUEST_INTERVAL_S,
) -> list[dict]:
    """Recent observations matching a filter, newest first, capped at `limit`.

    Two of the API's filters were measured to be unreliable and are therefore applied here
    as well as being asked for: `docs/SATNOGS_API_RECON.md` records that a filtered query
    can return records that do not match the filter. Asking the server narrows the
    transfer; checking locally is what makes the result mean what it says.

    **`require_waterfall` is not a convenience.** "Newest first" includes passes that have
    not happened yet. Measured on station 1696: every one of the first eighteen records was
    `status: future` with no image, so a caller that asked for six and over-fetched to
    eighteen got nothing to measure and no reason why. A future pass is not a failed
    observation and must not be reported as one, so it is skipped here rather than refused
    downstream, and paging continues until `limit` records that can actually be measured
    have been found or `max_pages` is reached.

    `max_pages` bounds that walk. Without it a filter matching only scheduled passes would
    page through a volunteer-run API until it ran out of observations.
    """
    params = ["format=json"]
    if norad_cat_id is not None:
        params.append(f"satellite__norad_cat_id={int(norad_cat_id)}")
    if ground_station is not None:
        params.append(f"ground_station={int(ground_station)}")
    if status is not None:
        params.append(f"status={status}")
    if start_after is not None:
        params.append(f"start={start_after.strftime('%Y-%m-%dT%H:%M:%SZ')}")

    # `extract_next_cursor` returns the cursor VALUE and not a URL, deliberately, so that a
    # stale parameter in the Link header cannot be followed blindly. The next URL therefore
    # has to be rebuilt from the same base and the same filters, which is what
    # `snapshot.py` does. Passing the bare cursor to `client.get` raises UnsupportedProtocol
    # ("Request URL is missing an 'http://' or 'https://' protocol"), and this loop only
    # ever reached the second page once `require_waterfall` made it page at all: before
    # that the first page always satisfied the limit and the bug was unreachable.
    base = f"{API_ROOT}/observations/?" + "&".join(params)
    out: list[dict] = []
    url: str | None = base
    pages = 0
    while url and len(out) < limit and pages < max_pages:
        pages += 1
        resp = snapshot.get_with_retry(client, url, timeout=30.0)
        resp.raise_for_status()
        payload = resp.json()
        page = payload if isinstance(payload, list) else payload.get("results", [])
        for rec in page:
            if norad_cat_id is not None and rec.get("norad_cat_id") != norad_cat_id:
                continue
            if ground_station is not None and rec.get("ground_station") != ground_station:
                continue
            if status is not None and rec.get("status") != status:
                continue
            if require_waterfall and not rec.get("waterfall"):
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        cursor = snapshot.extract_next_cursor(resp.headers.get("link"))
        url = f"{base}&cursor={quote(cursor, safe='')}" if cursor else None
        if url:
            time.sleep(interval_s)
    return out


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _provenance(obs_id: int, obs: dict, image_bytes: bytes) -> dict[str, Any]:
    """Everything needed to recompute this result without trusting it.

    Shared by both result paths on purpose. An UNRESOLVED reading is a published number
    too, in the sense that it says skip this observation, and a reader has the same right
    to re-derive it as they do a detection.
    """
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "observation_api": f"{API_ROOT}/observations/?format=json&id={obs_id}",
        "waterfall_url": obs.get("waterfall"),
        "waterfall_sha256": _sha256(image_bytes),
        "waterfall_bytes": len(image_bytes),
        "tle_source": obs.get("tle_source"),
        "tle1": obs.get("tle1"),
        "tle2": obs.get("tle2"),
        "code": {
            "physics": "pipeline/tracetriage/physics.py:corridor_for_obs",
            "axis": "pipeline/tracetriage/waterfall.py:parse_waterfall",
            "mode": "pipeline/tracetriage/doppler_mode.py:verdict_from_scores",
            "fit": "pipeline/tracetriage/corridor_fit.py:fit_offset",
            "nulls": "pipeline/tracetriage/corridor_fit.py:calibrate_against_nulls",
        },
        "reading": (
            "Every input is named so this can be recomputed by someone who does not "
            "trust it: the record comes from the URL above, the image hashes to the "
            "digest above, the orbit is the two lines above, and the five functions are "
            "the ones gate 3 is scored with rather than a second copy of them."
        ),
        "licence": (
            "Observation metadata and waterfall imagery are SatNOGS community data, "
            "CC BY-SA 4.0. Attribution and obligations: see DATA_LICENSE.md."
        ),
    }


def _identity(obs: dict, obs_id: int, phys: Any, geom: Any, rx_hz: float | None,
              corridor: Any) -> dict[str, Any]:
    """The fields that describe the observation rather than the measurement."""
    return {
        "observation_id": obs_id,
        "norad_cat_id": obs.get("norad_cat_id"),
        "satellite": obs.get("tle0"),
        "station": obs.get("ground_station"),
        "station_name": obs.get("station_name"),
        "start": obs.get("start"),
        "end": obs.get("end"),
        "status": obs.get("status"),
        "waterfall_status": obs.get("waterfall_status"),
        "client_family": normalise_client_family(obs.get("client_version")),
        "rx_freq_hz": rx_hz,
        "max_elevation_deg": getattr(corridor, "max_elevation_deg", None),
        "tle_epoch_age_days": phys.tle_epoch_age_days,
        "pass_duration_s": phys.pass_duration_s,
        "hz_per_px": geom.hz_per_px,
        "axis_derivation": geom.derivation,
        "axis_confidence": geom.derivation_confidence,
    }


def _mode_fields(mode: str, reason: str, summary: dict, corridor_type: str | None
                 ) -> dict[str, Any]:
    return {
        "mode": mode,
        "mode_reason": reason,
        "sigma_curved": summary.get("sigma_curved"),
        "sigma_vertical": summary.get("sigma_vertical"),
        "frequency_axis_sign": summary.get("frequency_axis_sign"),
        "corridor_type": corridor_type,
    }


def _unresolved(obs: dict, phys: Any, geom: Any, rx_hz: float | None, reason: str,
                summary: dict, swing_hz: float, image_bytes: bytes, notes: list[str],
                corridor: Any) -> LiveMeasurement:
    """A readable no, with the numbers that make it checkable.

    Every measurement field is None rather than zero. A zero offset and a null p-value
    read as a confident measurement of no error, which is the opposite of what happened:
    the image did not settle which shape it holds, so there is no line to measure from.
    """
    obs_id = int(obs["id"])
    return LiveMeasurement(
        **_identity(obs, obs_id, phys, geom, rx_hz, corridor),
        **_mode_fields("UNRESOLVED", reason, summary, None),
        offset_hz=None, offset_ppm=None, offset_px=None, at_bound=None, bound_hz=None,
        sigma=None, fit_detail=None, null_detail=None,
        n_nulls=None, null_median=None, null_p95=None, null_max=None,
        n_nulls_at_least=None, p_value=None, nulls_not_tested="mode_unresolved",
        doppler_swing_hz=swing_hz,
        second_trace=None,
        provenance=_provenance(obs_id, obs, image_bytes),
        notes=notes,
    )


def measure(
    obs: dict,
    image_bytes: bytes,
    *,
    ocr_results: list[tuple[float, str, float]] | None = None,
    n_nulls: int | None = None,
    label_reader: str = "auto",
) -> LiveMeasurement:
    """Measure one observation from its record and its waterfall.

    Separated from fetching on purpose: the same function measures a live record and a
    record already on disk, so a test can drive the whole measurement with no network at
    all, which is what `tests/test_live.py` does with the committed fixture images.
    """
    obs_id = int(obs["id"])
    notes: list[str] = []

    phys = corridor_for_obs(obs)
    if phys.degraded is not None:
        raise LiveRefusal(f"PHYSICS_{phys.degraded}", "the pass could not be propagated")

    rx_hz = rx_freq_of(obs)
    if rx_hz is None:
        raise LiveRefusal("NO_CENTRE", "no receive frequency, so the axis has no origin")

    duration_s = phys.pass_duration_s or 200.0
    geom = parse_waterfall(
        image_bytes,
        observation_id=obs_id,
        pass_duration_s=duration_s,
        rx_freq_hz=rx_hz,
        observation_freq_hz=obs.get("observation_frequency"),
        ocr_results=ocr_results,
        # "auto" rather than `parse_waterfall`'s own default of "ocr": the template matcher in
        # `glyph_axis` reads the same tick labels with numpy and scipy, and easyocr declares
        # torch, torchvision, opencv and scikit-image as its own dependencies. That is the
        # difference between a 166 MB install and a 4.6 GB one for a stranger who wants an
        # answer in Hz, and easyocr is still the fallback when the matcher finds too few labels
        # to fit an axis through.
        #
        # It is exposed rather than hardcoded because it changes the axis, and therefore every
        # frequency derived from it. Gate 3's receipt was produced through easyocr, so
        # reproducing that receipt to the digit means asking for easyocr, which is what
        # `tests/test_live.py` does. The two readers do not always agree, and on at least one
        # observation the disagreement is easyocr's fault: on 14736773 it read the centre tick
        # as 562 kHz, and the committed axis for that image was derived through that value.
        label_reader=label_reader,
    )
    if geom.degraded is not None or geom.hz_per_px is None:
        raise LiveRefusal("NO_AXIS", geom.degraded or "no Hz per pixel was derived")
    if geom.centre_px is None:
        raise LiveRefusal("NO_CENTRE", "the axis origin could not be placed")

    if phys.tle_epoch_age_days is not None and phys.tle_epoch_age_days > TLE_AGE_NOTE_DAYS:
        notes.append(
            f"The TLE is {phys.tle_epoch_age_days:.1f} days from the pass midpoint. "
            f"Its own propagation error is inside the offset reported here and nothing "
            f"in this measurement separates the two."
        )

    from io import BytesIO

    from PIL import Image  # deferred: keeps the module importable without an image stack

    with Image.open(BytesIO(image_bytes)) as im:
        rgb = np.asarray(im.convert("RGB"))
    zs = cf.normalised_rows(rgb, geom.crop_box)

    # Which corridor to score is a measurement, not a setting. Gate 3 reads the answer
    # from A3's annotation file, which works for 2,727 frozen observations and not at all
    # for one recorded an hour ago. So the two shapes are scored against each other here,
    # by the rule that produced those annotations, now in `doppler_mode`.
    #
    # Getting this wrong is silent rather than loud, and it was wrong in the first draft
    # of this file, which scored `phys.corrected` unconditionally. `physics.py` sets the
    # corrected corridor's Doppler to zeros, `calibrate_against_nulls` refuses to build
    # nulls for a corridor with no swing to scramble, and the result came back with a
    # plausible offset, a sigma of 0.35 and n=0 nulls. Nothing raised. A caller reading
    # the offset would have had a number fit to a flat line with no shape evidence
    # behind it and no field saying so.
    curve = phys.uncorrected
    scores = dm.matched_filter(
        zs, geom.centre_px, geom.hz_per_px, curve.fracs, curve.doppler_hz
    )
    swing_hz = dm.predicted_swing_hz(curve.doppler_hz)
    mode, mode_reason, mode_summary = dm.verdict_from_scores(scores, swing_hz)

    # UNRESOLVED returns rather than raises, and that is the load-bearing choice in this
    # function. Most observations on a real queue have nothing in them: no signal above
    # the floor, or two shapes inside the margin. A tool that throws on those cannot rank
    # a queue, because the empty ones are most of the queue and ranking needs a value for
    # each. The sigmas come back either way, so "3.1 curved against 2.9 vertical, both
    # under the 8 sigma floor" is readable as a reason to skip rather than as an error.
    corridor = phys.uncorrected if mode == "UNCORRECTED" else phys.corrected

    if mode == "UNRESOLVED":
        return _unresolved(
            obs, phys, geom, rx_hz, mode_reason, mode_summary, swing_hz,
            image_bytes, notes, corridor,
        )

    # `fit_corridor` rather than `fit_offset`, which is what this called first. Both
    # return the same offset; only the full fitter also returns how much of the image
    # supported it. On two of gate 3's three uncorrected observations the receipt reads
    # `detect_frac: 0.0` and `degraded: TRACE_NOT_MEASURABLE` beside a p-value of 0.005,
    # because the null comparison scores a path's mean brightness and does not need any
    # single pixel to clear a detection floor. Reporting the offset and the p-value while
    # dropping those two fields would publish the gate's number without the gate's
    # caveat, and this is the tool a stranger points at their own station.
    fit = cf.fit_corridor(
        zs,
        corridor,
        "uncorrected" if mode == "UNCORRECTED" else "corrected",
        geom.hz_per_px,
        geom.centre_px,
        rx_hz,
        obs_id=obs_id,
    )
    offset_hz = fit.fitted_offset_hz
    at_bound = fit.offset_at_bound
    bound_hz = fit.offset_bound_hz
    if offset_hz is None:
        raise LiveRefusal("NO_FIT", "no offset inside the bound kept the path on the plot")
    if fit.degraded is not None:
        notes.append(
            f"The fit is flagged {fit.degraded}: {fit.rows_detected} of {fit.rows_total} "
            f"rows carried a pixel above the detection floor "
            f"({fit.detect_frac * 100:.1f} percent). The offset and any p-value below "
            f"still stand, because both score a whole path's mean brightness rather than "
            f"counting detected pixels, but a residual spread cannot be measured from "
            f"rows that were never detected and is reported as null."
        )

    if mode == "CORRECTED":
        # A corrected capture has no S-curve to score, so there is no shape evidence to
        # be had and the null test below is vacuous by construction, not by accident:
        # `calibrate_against_nulls` returns n=0 for a corridor whose swing is zero and
        # says why in its own source. The offset is still the useful number, and for a
        # station operator it is arguably the more useful one, because a corrected
        # capture's residual is the receiver's own frequency error with the orbit
        # already taken out.
        notes.append(
            "This capture was Doppler-corrected at the station, so the trace is a "
            "near-vertical line and there is no curve shape to test. The offset is the "
            "line's distance from axis zero. No p-value is reported and none is "
            "available: a flat corridor is unchanged by permuting it in time, so every "
            "null reproduces the hypothesis and the comparison would be vacuous."
        )

    # `n_nulls` is the one threshold a caller may lower, and only to trade evidence for
    # latency: the p-value's floor is 1/(n+1), so 25 nulls cannot report anything below
    # 0.038 no matter what the fit does. Every other threshold is the gate's and is not
    # exposed, because a tool whose caller can move the bar is not measuring anything.
    thresholds = cf.DEFAULT_THRESHOLDS
    if n_nulls is not None:
        thresholds = dataclasses.replace(thresholds, n_nulls=int(n_nulls))
        notes.append(
            f"Scored against {n_nulls} nulls rather than the gate's "
            f"{cf.DEFAULT_THRESHOLDS.n_nulls}, so the smallest p-value reachable here is "
            f"{1 / (int(n_nulls) + 1):.3f}."
        )
    cal = cf.calibrate_against_nulls(
        zs, corridor, geom.hz_per_px, geom.centre_px, rx_hz, thresholds=thresholds
    )

    # The second-trace survey needs two numbers derived from this image and this pass:
    # the fitter's own per-row search window, so a peak the fit is already following is
    # not counted as a second trace, and the largest column jump Doppler can produce
    # between adjacent rows. Both come from the same places `scripts/measure_second_trace.py`
    # takes them, so the survey here and the survey in the receipt are the same survey.
    second: dict[str, Any] | None
    half_width_hz = corridor.half_width_hz
    n_image_rows = geom.crop_box.height() if geom.crop_box is not None else 0
    if not half_width_hz or half_width_hz <= 0 or n_image_rows <= 0:
        second = {"measurable": False, "why_not": "NO_WINDOW"}
    else:
        window_px = thresholds.search_window_factor * (half_width_hz / geom.hz_per_px)
        max_jump_px = cf.max_coherent_jump_px(
            geom.hz_per_px, (phys.pass_duration_s or duration_s) / n_image_rows
        )
        try:
            second = cf.second_trace_evidence(
                rgb, geom.crop_box, window_px=window_px, max_jump_px=max_jump_px
            )
        except Exception as exc:  # a survey that fails is a missing survey, not a failed run
            second = {"measurable": False, "why_not": f"ERROR_{type(exc).__name__}"}
            notes.append(
                "The second-trace survey did not complete, so it is reported as not "
                "measurable rather than as no second trace."
            )

    return LiveMeasurement(
        **_identity(obs, obs_id, phys, geom, rx_hz, corridor),
        **_mode_fields(
            mode, mode_reason, mode_summary,
            "uncorrected" if mode == "UNCORRECTED" else "corrected",
        ),
        offset_hz=offset_hz,
        offset_ppm=(offset_hz / rx_hz * 1e6) if rx_hz else None,
        offset_px=(offset_hz / geom.hz_per_px) if geom.hz_per_px else None,
        at_bound=at_bound,
        bound_hz=bound_hz,
        sigma=cal.true_sigma,
        fit_detail=fit.summary(),
        null_detail=cal.summary(),
        n_nulls=cal.n_nulls,
        null_median=cal.null_median,
        null_p95=cal.null_p95,
        null_max=cal.null_max,
        n_nulls_at_least=cal.n_at_least,
        p_value=cal.p_value,
        nulls_not_tested=cal.not_tested_reason,
        doppler_swing_hz=swing_hz,
        second_trace=second,
        provenance=_provenance(obs_id, obs, image_bytes),
        notes=notes,
    )


def triage(
    obs_id: int,
    *,
    client=None,
    ocr_results: list[tuple[float, str, float]] | None = None,
    n_nulls: int | None = None,
    label_reader: str = "auto",
) -> LiveMeasurement:
    """Fetch and measure one observation. Raises `LiveRefusal` with a named code."""
    own_client = client is None
    client = client or make_client()
    try:
        obs = fetch_observation(obs_id, client)
        url = obs.get("waterfall")
        if not url:
            raise LiveRefusal(
                "NO_WATERFALL",
                f"observation {obs_id} has no waterfall image "
                f"(waterfall_status={obs.get('waterfall_status')!r})",
            )
        image = fetch_waterfall(url, client)
        return measure(
            obs, image, ocr_results=ocr_results, n_nulls=n_nulls,
            label_reader=label_reader,
        )
    finally:
        if own_client:
            client.close()
