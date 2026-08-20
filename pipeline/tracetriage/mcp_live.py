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

from typing import Any

from .mcp_transport import ToolError, serve

SERVER_NAME = "tracetriage-live"
SERVER_VERSION = "0.1.0"

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
    return _measurement_payload(m)


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
    "live_list_observations to find an id, then live_triage_observation on it. Three "
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
