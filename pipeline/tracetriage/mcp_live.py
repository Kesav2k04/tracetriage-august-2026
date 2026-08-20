"""An MCP server that measures observations recorded today, over the public SatNOGS API.

    tracetriage mcp-live                       # from an install
    python -m pipeline.tracetriage.mcp_live     # from a checkout

**Why this lives in the package and the offline server does not.** A `pip install
tracetriage` ships `pipeline/tracetriage` and not `scripts/`. The offline server serves
committed files under `artifacts/` and `apps/web/public/data/`, so it needs a checkout no
matter where its code sits. This one needs nothing but this package and the network, so it
has to be importable from a wheel or `tracetriage mcp-live` would be an entry point to a
file that is not there.

**Why this is a second server and not four more tools in the first one.**
`scripts/mcp_server.py` advertises five properties and each one is a test: read-only,
offline, no invented numbers, every error a named reason, bounded output. The second of
those is checked by parsing that file's imports and refusing `httpx`. Adding a network tool
to it would not weaken the claim by degrees, it would delete it, and the honest place for
that boundary is the client's own configuration: a reader of `USE_WITH_YOUR_AGENT.md`
registers `tracetriage` and gets nothing but committed receipts, or registers
`tracetriage-live` as well and knows exactly which tools reach the network.

The transport is imported rather than copied. `mcp_server.handle` takes a tool registry
now, so the batch handling, the notification rule and the six named error paths exist once.
Every one of those exists because an input ended a session once.

**What this server keeps from the offline one.** Read-only, still: nothing here holds a
credential, TraceTriage has none, and the SatNOGS write API is not reachable from any code
path in this repository. Named reasons, still: a refusal carries a code. Bounded output,
still: `live_rank_observations` caps its budget, and a measurement is returned as its
summary blocks rather than with the residual series attached.

**What it cannot keep.** Determinism. The offline server answers from a file whose sha256 is
published; this one answers from whatever the API served, so every result carries the
measured-at time, the waterfall's own sha256 and the two TLE lines used. That is what makes
a live number checkable later, and it is why no tool here reports a value without a
`provenance` block beside it.

**The axis is the precondition, not the network.** Frequency per pixel is read from the
rendered tick labels, and `glyph_axis.py` does that with a template matcher rather than a
neural model, so it needs no extra and no model weights: what it needs is the template file
that ships inside the package. Without an axis every tool returns `NO_AXIS`, and refusing is
correct, because nothing in an observation's metadata gives frequency per pixel (the
waterfall does not span `samp_rate_rx`, measured, in `docs/SATNOGS_API_RECON.md`), so a
fallback would be an invented number. The preflight says so at startup rather than letting a
client complete a handshake and then fail every call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .mcp_transport import ToolError, serve

SERVER_NAME = "tracetriage-live"
SERVER_VERSION = "0.2.0"

#: How many observations one call may measure. Each one is an HTTP fetch of a record and a
#: waterfall plus an axis read, so a caller asking for a hundred would hold an agent for
#: several minutes and put a hundred requests through a volunteer-run API. Ten is a working
#: session's worth. A request above it is refused rather than truncated, so a validating
#: client and this handler agree about what is legal.
MAX_BUDGET = 10

#: Nulls per measurement when a caller does not say. The gate uses 200 and the p-value's
#: floor is 1/(n+1), so this cannot report below 0.01. Chosen for latency: 200 nulls is
#: about eight seconds per observation and an agent waiting on ten of those has stopped
#: being interactive. Any caller who wants the gate's own figure passes n_nulls=200.
DEFAULT_NULLS = 99


def _live():
    """Import the measurement module, or say which extra is missing.

    Deferred rather than imported at the top so that `tools/list` and the handshake work on
    an install without the imaging stack. A client that can see the tool list and read the
    reason gets further than one that watched the process exit.
    """
    try:
        from . import live
    except ImportError as exc:  # pragma: no cover - exercised by the preflight test
        first_party = (getattr(exc, "name", None) or "").split(".")[0] in (
            "pipeline",
            "tracetriage",
        )
        raise ToolError(
            "BUILD_BROKEN" if first_party else "DEPENDENCY_MISSING",
            (
                f"this build cannot import its own module `{exc.name}`, which is a packaging "
                f"fault and not a missing dependency: installing more packages will not fix "
                f"it, and running from a clone of the repository will."
                if first_party
                else f"the live measurement needs numpy, scipy, pillow, sgp4 and httpx: "
                f"{exc}. All five are base dependencies of this project, so installing it is "
                f"enough; the ocr extra is only for the neural axis reader and is not needed "
                f"for Hz."
            ),
        ) from exc
    return live


def _measurement_payload(m: Any) -> dict[str, Any]:
    """One measurement, as the blocks a reader needs and nothing else.

    The residual series is dropped and the two detail blocks are kept: a client that wants
    to know whether an offset rests on 32 detected rows or on none needs `measurement.fit`,
    and a client that wants the null distribution needs `nulls.detail`. Both are scalars.
    """
    d = m.to_dict()
    return {
        "observation": d["observation"],
        "pass": d["pass"],
        "axis": d["axis"],
        "mode": d["mode"],
        "measurement": d["measurement"],
        "nulls": d["nulls"],
        "second_trace": d["second_trace"],
        "provenance": d["provenance"],
        "notes": d["notes"],
    }


#: The last measurements this process took, keyed by observation id, so that
#: `live_check_claim` can check a sentence against the very numbers the caller was shown
#: rather than against a second measurement of the same observation. Bounded, because a
#: server that ran all afternoon would otherwise hold every waterfall it ever measured.
_RECENT: dict[int, Any] = {}
RECENT_MAX = 32


def _remember(m: Any) -> None:
    """Keep this measurement for `live_check_claim`, oldest out first."""
    _RECENT[int(m.observation_id)] = m
    while len(_RECENT) > RECENT_MAX:
        del _RECENT[next(iter(_RECENT))]


def tool_live_triage_observation(observation_id: int, n_nulls: int | None = None) -> dict:
    """Measure one observation now."""
    live = _live()
    if not isinstance(observation_id, int) or isinstance(observation_id, bool):
        raise ToolError("BAD_ARGUMENTS", "observation_id must be an integer")
    n = DEFAULT_NULLS if n_nulls is None else int(n_nulls)
    if not 1 <= n <= 500:
        raise ToolError("BAD_ARGUMENTS", f"n_nulls must be between 1 and 500, got {n}")
    try:
        m = live.triage(int(observation_id), n_nulls=n)
    except live.LiveRefusal as exc:
        raise ToolError(exc.code, str(exc)) from exc
    _remember(m)
    payload = _measurement_payload(m)
    payload["next"] = (
        "live_check_claim on this same id will check a sentence about this measurement "
        "against these numbers and nothing else. check_claim on the tracetriage-evidence "
        "server answers UNKNOWN_OBSERVATION for this id, correctly: that server serves the "
        "frozen corpus and this observation is not in it."
    )
    return payload


def tool_live_list_observations(
    norad_cat_id: int | None = None,
    ground_station: int | None = None,
    status: str | None = None,
    limit: int = 25,
) -> dict:
    """Recent observations matching a filter. Metadata only, nothing measured."""
    live = _live()
    if not 1 <= int(limit) <= 100:
        raise ToolError("BAD_ARGUMENTS", f"limit must be between 1 and 100, got {limit}")
    with live.make_client() as client:
        rows = live.list_observations(
            client,
            norad_cat_id=norad_cat_id,
            ground_station=ground_station,
            status=status,
            limit=int(limit),
        )
    return {
        "count": len(rows),
        "observations": [
            {
                "id": r.get("id"),
                "norad_cat_id": r.get("norad_cat_id"),
                "satellite": r.get("tle0"),
                "station": r.get("ground_station"),
                "station_name": r.get("station_name"),
                "start": r.get("start"),
                "status": r.get("status"),
                "waterfall_status": r.get("waterfall_status"),
                "has_waterfall": bool(r.get("waterfall")),
            }
            for r in rows
        ],
        "reading": (
            "Nothing here is measured. `waterfall_status` is SatNOGS's own vetting flag "
            "and is not a detection: observation 14745984 is flagged with-signal and this "
            "project's matched filter puts its best path at 2.5 sigma against an 8 sigma "
            "floor. Measure before believing a flag, which is what live_triage_observation "
            "is for. Two of the API's filters were measured to return records that do not "
            "match them, so this list is filtered again locally."
        ),
    }


def tool_live_rank_observations(
    norad_cat_id: int | None = None,
    ground_station: int | None = None,
    budget: int = 5,
    n_nulls: int | None = None,
) -> dict:
    """Measure a handful of recent observations and rank them by what was found.

    The ranking any triage queue actually needs: measured first, and among those the
    largest frequency offset with evidence behind it. An observation that settled nothing
    is kept in the output with its reason, because a queue that silently drops the empty
    ones cannot be audited and the empty ones are most of a real queue.
    """
    live = _live()
    if not 1 <= int(budget) <= MAX_BUDGET:
        raise ToolError(
            "BAD_ARGUMENTS",
            f"budget must be between 1 and {MAX_BUDGET}, got {budget}. Each observation is "
            f"two HTTP fetches against a volunteer-run API plus an axis read.",
        )
    n = DEFAULT_NULLS if n_nulls is None else int(n_nulls)

    measured: list[dict[str, Any]] = []
    with live.make_client() as client:
        rows = live.list_observations(
            client,
            norad_cat_id=norad_cat_id,
            ground_station=ground_station,
            limit=int(budget),
            require_waterfall=True,
        )
        for row in rows:
            if len(measured) >= int(budget):
                break
            obs_id = int(row["id"])
            try:
                image = live.fetch_waterfall(row["waterfall"], client)
                m = live.measure(row, image, n_nulls=n)
            except live.LiveRefusal as exc:
                measured.append({
                    "observation_id": obs_id, "mode": f"REFUSED_{exc.code}",
                    "why": str(exc), "offset_ppm": None, "p_value": None,
                })
                continue
            measured.append({
                "observation_id": obs_id,
                "satellite": m.satellite,
                "station": m.station,
                "mode": m.mode,
                "why": m.mode_reason,
                "offset_hz": m.offset_hz,
                "offset_ppm": m.offset_ppm,
                "sigma": m.sigma,
                "p_value": m.p_value,
                "detect_frac": (m.fit_detail or {}).get("detect_frac"),
                "waterfall_sha256": m.provenance.get("waterfall_sha256"),
            })

    def sort_key(r: dict) -> tuple:
        decided = r["mode"] in ("UNCORRECTED", "CORRECTED")
        return (not decided, -abs(r.get("offset_ppm") or 0.0))

    measured.sort(key=sort_key)
    return {
        "n_measured": len(measured),
        "n_decided": sum(1 for r in measured if r["mode"] in ("UNCORRECTED", "CORRECTED")),
        "ranked": measured,
        "reading": (
            "Ranked by whether the image settled which shape it holds, then by the size of "
            "the frequency offset. Rows that settled nothing keep their place in the list "
            "with a reason, because they are most of any real queue and a ranking that "
            "hides its own denominator cannot be checked. An offset in ppm is comparable "
            "across satellites and bands; the same offset in Hz is not."
        ),
    }


# ---------------------------------------------------------------------------
# The checker, over a measurement taken now
# ---------------------------------------------------------------------------

#: How many places each live field is printed to. The names and the precisions are the
#: offline packet's, from `explain.build_packet`, wherever the quantity is the same one: a
#: sentence about a console card and a sentence about a live measurement then face the same
#: vocabulary and the same rounding, so `check_claim` and `live_check_claim` cannot disagree
#: about whether "6.9 MHz" quotes a 6,904 Hz offset.
_LIVE_NUMBER_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("receiver_frequency_hz", "rx_freq_hz", 0),
    ("pass_duration_s", "pass_duration_s", 0),
    ("max_elevation_deg", "max_elevation_deg", 1),
    ("tle_epoch_age_days", "tle_epoch_age_days", 1),
    ("hz_per_pixel", "hz_per_px", 1),
    ("axis_derivation_confidence", "axis_confidence", 2),
    ("fitted_offset_hz", "offset_hz", 0),
    ("fitted_offset_ppm", "offset_ppm", 1),
    ("fitted_offset_px", "offset_px", 1),
    ("search_bound_hz", "bound_hz", 0),
    ("offset_sigma", "sigma", 2),
    ("sigma_curved", "sigma_curved", 1),
    ("sigma_vertical", "sigma_vertical", 1),
    ("doppler_swing_hz", "doppler_swing_hz", 0),
    ("nulls_n", "n_nulls", 0),
    ("null_median_sigma", "null_median", 2),
    ("null_p95_sigma", "null_p95", 2),
    ("null_max_sigma", "null_max", 2),
    ("null_p_value", "p_value", 4),
)

#: Identity and label fields, printed as strings. Every one of these also enters the
#: packet's vocabulary, because a draft naming this station or this satellite is quoting the
#: measurement rather than inventing an entity.
_LIVE_LABEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("ground_station_id", "station"),
    ("ground_station_name", "station_name"),
    ("norad_catalogue_id", "norad_cat_id"),
    ("satellite", "satellite"),
    ("network_label", "waterfall_status"),
    ("observation_status", "status"),
    ("mode_verdict", "mode"),
    ("corridor_scored", "corridor_type"),
    ("axis_derivation", "axis_derivation"),
    ("axis_reader", "axis_reader"),
    ("nulls_not_tested", "nulls_not_tested"),
)


def live_packet(m: Any):
    """The closed world for one live measurement: every field measured, and nothing else.

    Why this is not `explain.build_packet`. That function takes a console card and a queue
    row, and it requires seven corridor fields plus a queue rank, a model probability and an
    ensemble spread. A live measurement has none of the queue fields, because nothing ranked
    it, and the honest way to give it a rank would be to invent one. Calling `build_packet`
    with placeholders is precisely the defect it was written to refuse: a 0.0 default for
    `fitted_offset_hz` prints "the corridor sits 0 Hz from the catalogue centre" as a
    measurement and the checker grounds it.

    So the packet is assembled from the measurement's own non-null fields and the checker is
    the same function. A field that came back None is absent, not zero, which means an
    UNRESOLVED observation produces a small packet that refuses almost every number, which
    is the correct behaviour and not a degradation.

    One check the offline packet gets and this one cannot: `time_claim_violations` needs
    `closest_approach_fraction`, and a live measurement does not compute closest approach, so
    a draft that points at a moment in the recording is not checked against the geometry
    here. `verify_note` returns no time violations rather than wrong ones, and the tool's
    reading says so.
    """
    from .explain import EvidencePacket  # noqa: PLC0415

    printed: dict[str, str] = {"observation_id": str(int(m.observation_id))}
    exact: dict[str, float] = {"observation_id": float(int(m.observation_id))}
    vocabulary: set[str] = set()

    for name, attr in _LIVE_LABEL_FIELDS:
        value = getattr(m, attr, None)
        if value is None or value == "":
            continue
        printed[name] = str(value)
        vocabulary.add(str(value))
        # A numeric identifier is a number a draft may quote, so it belongs in `exact` too
        # or "station 1696" would be refused as an ungrounded number.
        if isinstance(value, int) and not isinstance(value, bool):
            exact[name] = float(value)

    for name, attr, places in _LIVE_NUMBER_FIELDS:
        value = getattr(m, attr, None)
        if value is None:
            continue
        exact[name] = float(value)
        printed[name] = f"{float(value):.{places}f}"

    # Degrade codes the measurement itself raised. A draft may quote one; it may not invent
    # one, and `verify_note` refuses any other SCREAMING_SNAKE token it finds.
    for note in getattr(m, "notes", None) or []:
        vocabulary.add(str(note))
    printed["measurement_notes"] = ", ".join(getattr(m, "notes", None) or ["none"])
    printed["mode_reason"] = str(getattr(m, "mode_reason", "") or "")

    return EvidencePacket(
        obs_id=int(m.observation_id),
        printed=printed,
        exact=exact,
        vocabulary=frozenset(v for v in vocabulary if v),
    )


def tool_live_check_claim(
    observation_id: int, text: str, n_nulls: int | None = None
) -> dict:
    """Check a sentence against an observation measured now, by the same checker.

    This is the loop the whole live path exists for. `check_claim` on the offline server
    answers `UNKNOWN_OBSERVATION` for an id that is not in the committed corpus, which is
    correct and which also means an agent that has just measured a pass recorded this
    morning has nowhere to send a sentence about it. Two servers that cannot compose leave
    the grounding claim true only about last month's data.

    The checker is `explain.verify_note`, unchanged and not reimplemented: the same function
    that refused fourteen of twenty-five of this project's own generated drafts. What is new
    here is the packet it runs against.

    Cache first. If the caller measured this id in this session, the sentence is checked
    against those exact numbers, and `evidence_packet_sha256` plus `measured_at_utc` say
    which measurement that was. On a miss the observation is measured now, which is two HTTP
    fetches, and `measurement_source` says `measured_now` so nobody reads a verdict as being
    about numbers they were shown earlier.
    """
    if not isinstance(text, str) or not text.strip():
        raise ToolError("EMPTY_CLAIM", "text must be a non-empty string")
    if not isinstance(observation_id, int) or isinstance(observation_id, bool):
        raise ToolError("BAD_ARGUMENTS", "observation_id must be an integer")
    from .explain import verify_note  # noqa: PLC0415

    obs_id = int(observation_id)
    m = _RECENT.get(obs_id)
    source = "cache"
    if m is None:
        live = _live()
        n = DEFAULT_NULLS if n_nulls is None else int(n_nulls)
        if not 1 <= n <= 500:
            raise ToolError("BAD_ARGUMENTS", f"n_nulls must be between 1 and 500, got {n}")
        try:
            m = live.triage(obs_id, n_nulls=n)
        except live.LiveRefusal as exc:
            raise ToolError(
                exc.code,
                f"{exc}. Nothing can be checked against an observation that could not be "
                f"measured: a packet built from a refusal would be an empty closed world, "
                f"and an empty closed world grounds nothing and refuses everything, which "
                f"reads like a verdict about the sentence.",
            ) from exc
        _remember(m)
        source = "measured_now"

    packet = live_packet(m)
    result = verify_note(text, packet)
    return {
        "observation_id": packet.obs_id,
        "verdict": "GROUNDED" if result.ok else "REFUSED",
        "codes": result.codes,
        "violations": result.violations,
        "measurement_source": source,
        "mode_verdict": m.mode,
        "evidence_packet": packet.printed,
        "evidence_packet_sha256": packet.sha256(),
        "n_packet_fields": len(packet.printed),
        "measured_at_utc": (m.provenance or {}).get("measured_at_utc"),
        "waterfall_sha256": (m.provenance or {}).get("waterfall_sha256"),
        "reading": (
            "GROUNDED means every number in the text appears in this measurement's own "
            "fields, in the unit it was written in, and the text asserts nothing the "
            "permission contract forbids. Same checker as check_claim on the "
            "tracetriage-evidence server (pipeline/tracetriage/explain.py:verify_note); "
            "different packet, because this observation has no queue row and inventing one "
            "would be the invented number this project refuses. A measurement that came "
            "back UNRESOLVED yields a small packet, so most numbers are refused: that is "
            "the closed world being small, not the sentence being judged twice. One check "
            "the offline packet gets and this one does not: a claim about WHERE in the "
            "recording to look is not verified here, because closest approach is not "
            "computed live, so no MISLOCATED_TIME_CLAIM can be raised either way."
        ),
    }


# ---------------------------------------------------------------------------
# One station, mode by mode
# ---------------------------------------------------------------------------

#: How many observations `live_station` may measure. Lower than `MAX_BUDGET` on purpose:
#: this tool is auto-approved in `.bob/mcp.json` and `live_rank_observations` is not, so the
#: auto-approved ceiling has to be a number a volunteer-run API can absorb without anybody
#: being asked first.
STATION_MAX_BUDGET = 6
STATION_DEFAULT_BUDGET = 5

#: How many distinct satellites a mode needs before its median is a receiver calibration.
#: A receiver's frequency error is common to everything it hears and an orbit's is not, so
#: agreement ACROSS satellites is the part that points at the receiver. Two can agree by
#: coincidence; this is the number the handover pre-registered and it is not moved after
#: seeing a result.
CALIBRATION_MIN_DISTINCT_NORAD = 3


def _median(values: list[float]) -> float | None:
    n = len(values)
    if n == 0:
        return None
    ordered = sorted(values)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def station_mode_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Split a station's measured rows by correction mode and summarise each side.

    A pure function over the `to_dict()` rows so it can be tested without the network, which
    matters more here than usual: the thing worth testing is the refusal, and a refusal that
    only happens against live data is a refusal nobody checked.

    Three things this does that `tracetriage station` does not.

    It splits by mode. The CLI takes one median over both, and prints the reason that is
    unsound as its third confound. A corrected capture's offset is a residual left after the
    station's own Doppler correction and an uncorrected capture's is the whole offset, so
    they are different quantities and their median is neither.

    It refuses the pooled median rather than printing it with a warning. A warning beside a
    number is read as a number.

    It requires three distinct satellites inside a mode, not two. Two agreeing offsets from
    two orbits is the smallest set that can agree by coincidence, and the CLI's threshold of
    two was chosen before there were two-satellite runs to look at.
    """
    from . import live  # noqa: PLC0415

    decisive = [r for r in rows if live.is_decisive(r)]
    by_mode: dict[str, dict[str, Any]] = {}
    for verdict in ("UNCORRECTED", "CORRECTED"):
        group = [r for r in decisive if r["mode"]["verdict"] == verdict]
        if not group:
            continue
        ppms = sorted(float(r["measurement"]["offset_ppm"]) for r in group)
        norads = sorted({r["observation"]["norad_cat_id"] for r in group})
        enough = len(norads) >= CALIBRATION_MIN_DISTINCT_NORAD
        by_mode[verdict] = {
            "n_decisive": len(group),
            "n_distinct_norad": len(norads),
            "distinct_norad": norads,
            "median_offset_ppm": _median(ppms),
            "min_offset_ppm": ppms[0],
            "max_offset_ppm": ppms[-1],
            "all_offsets_ppm": ppms,
            "observation_ids": [int(r["observation"]["id"]) for r in group],
            "calibration": "CALIBRATION" if enough else "NOT_A_CALIBRATION",
            "why": (
                f"{len(norads)} distinct satellites, at or above the "
                f"{CALIBRATION_MIN_DISTINCT_NORAD} this reading requires, so the agreement "
                f"across orbits is the part that points at the receiver."
                if enough
                else f"NOT a calibration: {len(norads)} distinct satellite"
                f"{'' if len(norads) == 1 else 's'} cannot separate a receiver error from "
                f"those orbits' own propagation error. This reading needs "
                f"{CALIBRATION_MIN_DISTINCT_NORAD}."
            ),
        }

    if len(by_mode) > 1:
        counts = ", ".join(f"{k} {v['n_decisive']}" for k, v in by_mode.items())
        pooled = {
            "median_offset_ppm": None,
            "refused": "MIXED_MODE_MEDIAN",
            "why": (
                f"this station's decisive captures span both correction modes ({counts}), "
                f"and their offsets are different quantities: a corrected capture's is a "
                f"residual after the station's own Doppler correction and an uncorrected "
                f"one's is not. A median over both is neither, so it is refused rather than "
                f"printed with a warning. Read the per-mode medians instead."
            ),
        }
    elif len(by_mode) == 1:
        mode, block = next(iter(by_mode.items()))
        pooled = {
            "median_offset_ppm": block["median_offset_ppm"],
            "refused": None,
            "mode": mode,
            "why": (
                f"every decisive capture here is {mode}, so there is one quantity and no mix "
                f"to refuse. Whether it is a calibration is the per-mode question above."
            ),
        }
    else:
        pooled = {
            "median_offset_ppm": None,
            "refused": "NO_DECISIVE_CAPTURE",
            "why": (
                "no capture settled which shape it holds with an offset off the search "
                "bound, so there is nothing to take a median of. On a real station queue "
                "this is the common outcome and it is not a failure."
            ),
        }

    return {
        "observations_measured": len(rows),
        "observations_decisive": len(decisive),
        "by_mode": by_mode,
        "pooled": pooled,
        "not_decisive": [
            {
                "observation_id": r.get("observation_id")
                or (r.get("observation") or {}).get("id"),
                "mode": (
                    r["mode"]["verdict"] if isinstance(r.get("mode"), dict) else r.get("mode")
                ),
                "why": (
                    r["mode"].get("why") if isinstance(r.get("mode"), dict) else r.get("why")
                ),
            }
            for r in rows
            if not live.is_decisive(r)
        ],
        "confounds": list(live.STATION_CONFOUNDS),
        "reading": (
            "Mode-split, and that is the whole difference from a single median. Read the "
            "block for the mode you care about, its n_distinct_norad, and its calibration "
            "verdict. The pooled median is refused whenever both modes are present, because "
            "a corrected capture's offset and an uncorrected capture's offset are not the "
            "same quantity. Rows that settled nothing are listed with their reason rather "
            "than dropped, because they are most of any real station queue and a summary "
            "that hides its own denominator cannot be checked."
        ),
    }


def tool_live_station(
    ground_station: int, budget: int = STATION_DEFAULT_BUDGET, n_nulls: int | None = None
) -> dict:
    """One station's recent captures, measured now, with the median split by mode.

    The one question a SatNOGS volunteer can act on: is this receiver off frequency, and by
    how much? A single observation cannot answer it, because the offset it measures also
    holds that TLE's propagation error and the pixel quantisation of the axis. Several
    observations of DIFFERENT satellites can, because a receiver's error is the same across
    all of them and an orbit's is not.

    `tracetriage station` is the same measurement from a shell, and the MCP twin exists
    because a shell escape is not a tool call: an agent that has to run a subprocess to
    answer this has left the part of the system anyone can audit.
    """
    live = _live()
    if not isinstance(ground_station, int) or isinstance(ground_station, bool):
        raise ToolError("BAD_ARGUMENTS", "ground_station must be an integer")
    if not 1 <= int(budget) <= STATION_MAX_BUDGET:
        raise ToolError(
            "BAD_ARGUMENTS",
            f"budget must be between 1 and {STATION_MAX_BUDGET}, got {budget}. This tool is "
            f"auto-approved for the demo, so its ceiling is lower than "
            f"live_rank_observations' {MAX_BUDGET}: every observation is two HTTP fetches "
            f"against a volunteer-run API.",
        )
    n = DEFAULT_NULLS if n_nulls is None else int(n_nulls)
    if not 1 <= n <= 500:
        raise ToolError("BAD_ARGUMENTS", f"n_nulls must be between 1 and 500, got {n}")

    rows: list[dict[str, Any]] = []
    with live.make_client() as client:
        listed = live.list_observations(
            client,
            ground_station=int(ground_station),
            limit=int(budget),
            require_waterfall=True,
            end_before=datetime.now(UTC),
        )
        for row in listed:
            if len(rows) >= int(budget):
                break
            obs_id = int(row["id"])
            try:
                image = live.fetch_waterfall(row["waterfall"], client)
                m = live.measure(row, image, n_nulls=n)
            except live.LiveRefusal as exc:
                rows.append(
                    {"observation_id": obs_id, "mode": f"REFUSED_{exc.code}", "why": str(exc)}
                )
                continue
            _remember(m)
            rows.append(m.to_dict())

    summary = station_mode_split(rows)
    summary["station"] = int(ground_station)
    summary["budget"] = int(budget)
    return summary


TOOLS: dict[str, dict[str, Any]] = {
    "live_triage_observation": {
        "handler": tool_live_triage_observation,
        "description": (
            "Measure one SatNOGS observation recorded at any time, including today. "
            "Propagates the pass from the TLE in the observation's own record, reads the "
            "frequency axis off the waterfall's tick labels, measures whether the capture "
            "was Doppler-corrected, fits the frequency offset, and scores it against "
            "permuted-Doppler nulls built from that same pass. Returns the offset in Hz "
            "and ppm with a p-value, or a named refusal. Every input is named with its URL "
            "and sha256 so the result can be recomputed."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "integer"},
                "n_nulls": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["observation_id"],
            "additionalProperties": False,
        },
    },
    "live_list_observations": {
        "handler": tool_live_list_observations,
        "description": (
            "Recent public observations, filtered by satellite, station or status. "
            "Metadata only: nothing in the result is measured, and SatNOGS's own "
            "with-signal flag is not a detection."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "norad_cat_id": {"type": "integer"},
                "ground_station": {"type": "integer"},
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    "live_check_claim": {
        "handler": tool_live_check_claim,
        "description": (
            "Check a sentence against an observation this server measured, including one "
            "recorded today. Same checker as the offline check_claim tool, which answers "
            "UNKNOWN_OBSERVATION for an id outside the committed corpus: this one builds "
            "the packet from the live measurement instead, so a false downlink frequency "
            "on this morning's pass is refused with a code rather than unanswerable. "
            "Reuses the measurement from this session when there is one, and says which."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "observation_id": {"type": "integer"},
                "text": {"type": "string"},
                "n_nulls": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["observation_id", "text"],
            "additionalProperties": False,
        },
    },
    "live_station": {
        "handler": tool_live_station,
        "description": (
            f"One ground station's recent captures, measured now, with the median offset "
            f"in ppm split by Doppler-correction mode and the number of distinct "
            f"satellites behind each median. Refuses a mixed-mode median, because "
            f"corrected and uncorrected captures measure different things, and refuses to "
            f"call any of it a calibration under three distinct satellites inside one "
            f"mode. Costs two HTTP fetches per observation, so the ceiling is "
            f"{STATION_MAX_BUDGET}."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "ground_station": {"type": "integer"},
                "budget": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": STATION_MAX_BUDGET,
                },
                "n_nulls": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["ground_station"],
            "additionalProperties": False,
        },
    },
    "live_rank_observations": {
        "handler": tool_live_rank_observations,
        "description": (
            f"Measure up to {MAX_BUDGET} recent observations for one satellite or station "
            f"and rank them: settled first, then by the size of the frequency offset. The "
            f"triage question, asked of today's captures rather than of a snapshot."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "norad_cat_id": {"type": "integer"},
                "ground_station": {"type": "integer"},
                "budget": {"type": "integer", "minimum": 1, "maximum": MAX_BUDGET},
                "n_nulls": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "additionalProperties": False,
        },
    },
}

INSTRUCTIONS = (
    "Measures public SatNOGS observations live. Every number is computed here and now, so "
    "every result carries the time it was measured, the waterfall's sha256 and the two TLE "
    "lines used. Nothing is written anywhere and no credential exists. Start with "
    "live_list_observations to find an id, then live_triage_observation on it, then "
    "live_check_claim to see a sentence about that measurement refused. live_station "
    "answers whether one receiver is off frequency. Three "
    "outcomes are normal and distinct: UNCORRECTED (the trace follows the pass's Doppler "
    "curve, so an offset and a p-value are reported), CORRECTED (the station corrected for "
    "Doppler, so the trace is vertical, an offset is reported and no p-value is available), "
    "and UNRESOLVED (the image does not settle which, which is most observations and is the "
    "answer that says skip this one). For the frozen, receipt-backed evidence this project "
    "is scored on, use the tracetriage server instead: these tools are not those numbers."
)


def live_preflight() -> list[str]:
    """Can this server answer at all? Asked at startup, not at first call.

    Two things can be missing and they need different sentences. Without numpy and friends
    nothing can be measured. Without the OCR extra the axis cannot be read, so a
    measurement would come back as NO_AXIS every time, which is a working server that
    answers no question.
    """
    problems: list[str] = []
    try:
        from . import live  # noqa: F401
    except ImportError as exc:
        problems.append(
            f"the measurement stack is not importable ({exc}); numpy, scipy, pillow, sgp4 "
            f"and httpx are all base dependencies of this project, so installing it is enough"
        )
        return problems

    # The axis used to be the second thing that could be missing, and easyocr's absence was
    # a startup problem because without it every measurement refused with NO_AXIS. It is not
    # any more: `glyph_axis` reads the same tick labels with numpy and scipy, so what has to
    # be present is the template file, which ships inside the package.
    from .glyph_axis import TEMPLATE_PATH  # noqa: PLC0415

    if not TEMPLATE_PATH.exists():
        problems.append(
            f"{TEMPLATE_PATH.name} is not installed beside the package, so the frequency "
            f"axis cannot be read and every measurement would refuse with NO_AXIS. Nothing "
            f"in an observation's metadata gives frequency per pixel, so there is no "
            f"fallback here that would not be an invented number. Regenerate it with "
            f"scripts/build_glyph_templates.py from a checkout, or install the neural "
            f"reader instead by installing this project's ocr extra"
        )
    return problems


def main() -> int:
    return serve(
        tools=TOOLS,
        server_info={"name": SERVER_NAME, "version": SERVER_VERSION},
        instructions=INSTRUCTIONS,
        preflight=live_preflight,
    )


if __name__ == "__main__":
    raise SystemExit(main())
