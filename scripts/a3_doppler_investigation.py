"""A3: Doppler correction status investigation.

Answers the one blocking unknown: are SatNOGS waterfalls already Doppler
corrected at capture, or do they show the full S-curve?

Method, per observation:
  1. Propagate the observation's own stored TLE across the pass.
  2. Compute the expected Doppler shift at each sample from the range rate and
     the observation's rx-freq.
  3. Call waterfall.parse_waterfall for plot_box, crop_box, hz_per_px, centre_px.
  4. Measure where the signal actually is: the brightest column in each block
     of rows, kept only when it stands above that block's own noise floor by a
     margin in robust sigmas. That gives a frequency offset per unit of pass
     time, measured rather than assumed.
  5. Score the measurement against both hypotheses:
       uncorrected -> the measured track follows the predicted S-curve
       corrected   -> the measured track is flat near 0 Hz offset
     The measurement is repeated at three detection settings and the verdict is
     only accepted when all three agree, so no answer rests on one threshold.
     UNRESOLVED is a real outcome, not a failure to try.
  6. Render a side-by-side overlay: untouched waterfall on the left, the same
     image annotated on the right, so the raw evidence is never painted over.

Run:
    .venv\\Scripts\\python.exe scripts\\a3_doppler_investigation.py

Output:
    artifacts/a3_overlays/overlay_<obs_id>.png   (one per observation)
    artifacts/a3_overlays/summary.json           (machine-readable results)

API responses and waterfall PNGs are cached under .a3_cache/ so that a repeat
run costs no requests. The SatNOGS API rate-limits hard once a window is spent.
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pipeline.tracetriage import doppler_mode as _dm  # noqa: E402
from pipeline.tracetriage.doppler_mode import (  # noqa: E402
    matched_filter,
    predicted_swing_hz,
    verdict_from_scores,
)
from pipeline.tracetriage.physics import client_family  # noqa: E402
from pipeline.tracetriage.waterfall import parse_waterfall  # noqa: E402

logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TARGET_OBS = int(os.environ.get("A3_TARGET_OBS", "10"))
CANDIDATE_POOL = 24
MAX_PAGES = 6

# The listing is newest first, and the newest records are scheduled observations
# that have not run: status "future", waterfall null, waterfall_status "unknown".
# Vetting also lags capture. Asking for a window that closed several days ago is
# what makes the first page usable. A same-day end returned 200 future records
# and zero candidates. Six days back is far enough that vetting has caught up on
# most of the window, which is what makes with-signal common enough to stop
# paging early.
END_DATE = "2026-08-10T00:00:00Z"
API_BASE = "https://network.satnogs.org/api/observations/"
USER_AGENT = (
    "tracetriage/0.1 (+https://github.com/Kesav2k04/tracetriage-august-2026;"
    " kesavk659@gmail.com)"
)
REQUEST_INTERVAL = 2.0
RETRY_DELAYS = [5, 15, 45]
MAX_SLEEP_ON_429 = 120.0   # never block the run for longer than this

CACHE_DIR = Path(os.environ.get("A3_CACHE_DIR") or (REPO / ".a3_cache"))
OUT_DIR = REPO / "artifacts" / "a3_overlays"

C = 299_792_458.0
WGS84_A = 6378.137
WGS84_F = 1.0 / 298.257223563
OMEGA_EARTH = 7.2921159e-5

N_SAMPLES = 240

# One object under two names, not two constants: an assignment rather than a copy, so
# a threshold cannot be changed in one file and read from the other. This script's own
# tests reach for them as attributes of this module and the finding write-up cites them
# here, which is why the names stay.
FILTER_WIDTHS = _dm.FILTER_WIDTHS
PRIMARY_WIDTH = _dm.PRIMARY_WIDTH
SIGMA_MIN = _dm.SIGMA_MIN
SIGMA_MARGIN = _dm.SIGMA_MARGIN
MIN_PREDICTED_SWING_HZ = _dm.MIN_PREDICTED_SWING_HZ

# The scan, the thresholds and the verdict rule moved to
# `pipeline/tracetriage/doppler_mode.py` so that code shipped in the wheel can ask
# the same question of a live observation, which has no annotation to read a verdict
# from. Re-exported under their old names here: this script's own tests reach for
# them as module attributes, and the names are what the finding write-up cites.
#
# The scan takes `zs` as an argument and this file still computes it with the
# `normalised_rows` below, whose MAD floor of 1e-6 corridor_fit has since replaced
# with one grey level. That floor is a defect, and it is the one this receipt was
# measured through, so replaying A3 must keep it. See the note in doppler_mode.
EDGE_MARGIN_PX = 4

# Half-width of the residual corridor drawn for the corrected hypothesis.
CORRECTED_CORRIDOR_HZ = 200.0

# Viridis runs dark purple to blue to green to yellow, so annotation colours are
# chosen from outside that ramp. Green would be invisible against the signal.
UNCORR_COLOR = (255, 45, 45)      # red
CORR_COLOR = (255, 0, 255)        # magenta
TRACK_COLOR = (255, 170, 0)       # orange
CAPTION_H = 78


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------


def station_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> np.ndarray:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    alt_km = alt_m / 1000.0
    return np.array([
        (n + alt_km) * math.cos(lat) * math.cos(lon),
        (n + alt_km) * math.cos(lat) * math.sin(lon),
        (n * (1 - e2) + alt_km) * math.sin(lat),
    ])


def gmst(dt: datetime) -> float:
    jd = (dt - datetime(2000, 1, 1, 12, tzinfo=UTC)).total_seconds() / 86400.0
    return math.radians(280.46061837 + 360.98564736629 * jd) % (2 * math.pi)


def eci_to_ecef(v: np.ndarray, dt: datetime) -> np.ndarray:
    t = gmst(dt)
    ct, st = math.cos(t), math.sin(t)
    return np.array([ct * v[0] + st * v[1], -st * v[0] + ct * v[1], v[2]])


def rx_freq_of(obs: dict) -> float | None:
    """Truth for the tuned frequency is client_metadata.radio.parameters.rx-freq."""
    try:
        meta = json.loads(obs["client_metadata"])
    except Exception:
        return None
    params = meta.get("radio", {}).get("parameters", {})
    for key in ("rx-freq",):
        v = params.get(key)
        if v:
            return float(v)
    v = obs.get("observation_frequency") or obs.get("transmitter_downlink_low")
    return float(v) if v else None


def compute_doppler_curve(
    obs: dict,
) -> tuple[list[float], list[float], list[float]]:
    """Return (fracs, doppler_hz, max_elevation_deg) across the pass.

    doppler_hz is positive when the satellite is approaching, which is the
    higher received frequency and therefore the right-hand side of the axis.
    """
    from sgp4.api import Satrec, jday  # type: ignore[import]

    sat = Satrec.twoline2rv(obs["tle1"], obs["tle2"])
    start_dt = datetime.fromisoformat(obs["start"].replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(obs["end"].replace("Z", "+00:00"))
    duration_s = (end_dt - start_dt).total_seconds()

    freq = rx_freq_of(obs)
    if not freq:
        raise ValueError("no rx-freq available")

    site = station_ecef(
        float(obs["station_lat"]), float(obs["station_lng"]), float(obs["station_alt"])
    )
    site_hat = site / np.linalg.norm(site)

    fracs: list[float] = []
    dops: list[float] = []
    els: list[float] = []
    for i in range(N_SAMPLES):
        frac = i / (N_SAMPLES - 1)
        t = start_dt + timedelta(seconds=duration_s * frac)
        jd_whole, jd_fr = jday(
            t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6
        )
        err, r_eci, v_eci = sat.sgp4(jd_whole, jd_fr)
        if err != 0:
            continue

        r_ecef = eci_to_ecef(np.array(r_eci), t)
        v_ecef = eci_to_ecef(np.array(v_eci), t)
        v_ecef = v_ecef - np.cross(np.array([0.0, 0.0, OMEGA_EARTH]), r_ecef)

        los = r_ecef - site
        rng = float(np.linalg.norm(los))
        los_hat = los / rng
        range_rate = float(np.dot(los_hat, v_ecef))          # km/s, + is receding
        dops.append(-range_rate * 1000.0 / C * freq)
        fracs.append(frac)

        els.append(
            math.degrees(math.asin(max(-1.0, min(1.0, float(np.dot(los_hat, site_hat))))))
        )

    return fracs, dops, els


# ---------------------------------------------------------------------------
# Signal track measurement
# ---------------------------------------------------------------------------


def normalised_rows(rgb: np.ndarray, crop_box) -> np.ndarray:
    """Per-row robust z-scores over the spectrogram interior.

    Normalising each row separately removes the vertical brightness gradient
    that changing range puts into every pass, so a row near the horizon and a
    row at closest approach are scored on the same footing. Nothing is
    normalised along the time axis: that would delete a stationary carrier,
    which is the exact shape one of the two hypotheses predicts.
    """
    x0 = crop_box.x0 + EDGE_MARGIN_PX
    x1 = crop_box.x1 - EDGE_MARGIN_PX
    y0 = crop_box.y0 + EDGE_MARGIN_PX
    y1 = crop_box.y1 - EDGE_MARGIN_PX
    lum = rgb[y0:y1, x0:x1].astype(np.float32).mean(axis=2)
    med = np.median(lum, axis=1, keepdims=True)
    mad = np.median(np.abs(lum - med), axis=1, keepdims=True) * 1.4826
    return (lum - med) / np.maximum(mad, 1e-6)


def visible_track(rgb: np.ndarray, crop_box, z_min: float = 4.0):
    """Per-row brightest column, for drawing only. Never feeds the verdict.

    One row at a time, with no averaging, so a fast-sweeping trace is not
    smeared into the background before it can be drawn.
    """
    zs = normalised_rows(rgb, crop_box)
    idx = np.argmax(zs, axis=1)
    peak = zs[np.arange(zs.shape[0]), idx]
    keep = peak >= z_min
    rows = np.nonzero(keep)[0]
    fracs = (rows + EDGE_MARGIN_PX + 0.5) / crop_box.height()
    return fracs, idx[keep].astype(np.float64) + EDGE_MARGIN_PX, peak[keep]


def analyse(rgb: np.ndarray, geom, curve, els: list[float]) -> tuple[dict, dict, tuple]:
    """Score both hypotheses on one observation and return a verdict."""
    curve_fracs, curve_hz = curve
    centre = geom.centre_px if geom.centre_px is not None else geom.crop_box.width() / 2.0

    zs = normalised_rows(rgb, geom.crop_box)
    scores = matched_filter(zs, centre, geom.hz_per_px, curve_fracs, curve_hz)
    swing = predicted_swing_hz(curve_hz)
    verdict, reason, summary = verdict_from_scores(scores, swing)

    track = visible_track(rgb, geom.crop_box)
    summary["n_drawn_track_points"] = int(track[0].size)
    return {"consensus": (verdict, reason), "primary": summary}, scores, track



# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------


def _save(img: Image.Image, path: Path) -> None:
    """Write an overlay as a 256-colour PNG.

    A spectrogram is noise-dominated and compresses badly in truecolour: the
    full set came to 38.9 MB, and 16.4 MB with a palette. Measured against the
    source on observation 14745929 the cost is a mean absolute error of 0.06
    of 255 per channel, with the 99th percentile at 1. The untouched source is
    also still one request away from the observation id recorded beside it.
    """
    img.convert("P", palette=Image.ADAPTIVE, colors=256).save(str(path), optimize=True)


def _fmt(v) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.1f}"


def _font(size: int):
    """A readable font. Matplotlib ships DejaVu Sans, so it is always present."""
    try:
        import matplotlib

        path = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def draw_overlay(raw_png: bytes, obs: dict, geom, curve, track, stats, verdict) -> Image.Image:
    """Raw image on the left, annotated copy on the right, caption above both.

    The left panel is never drawn on. Whatever the annotation claims, the
    unmodified evidence is in the same file next to it.
    """
    base = Image.open(io.BytesIO(raw_png)).convert("RGB")
    w, h = base.size
    gap = 10
    canvas = Image.new("RGB", (w * 2 + gap, h + CAPTION_H), (16, 16, 18))
    canvas.paste(base, (0, CAPTION_H))
    canvas.paste(base, (w + gap, CAPTION_H))

    d = ImageDraw.Draw(canvas)
    ox = w + gap
    f_title = _font(17)
    f_body = _font(13)

    crop_box = geom.crop_box
    if crop_box is None or not geom.hz_per_px:
        d.text((10, 10), f"obs {obs['id']}: waterfall parse failed ({geom.degraded})",
               fill=UNCORR_COLOR, font=f_title)
        return canvas

    hz_per_px = geom.hz_per_px
    centre_px = geom.centre_px
    centre_x = ox + crop_box.x0 + (centre_px if centre_px is not None else crop_box.width() / 2.0)
    y0, y1 = crop_box.y0 + CAPTION_H, crop_box.y1 + CAPTION_H

    # Corrected hypothesis: the residual corridor, two lines rather than a fill
    # so the pixels underneath stay readable.
    half = CORRECTED_CORRIDOR_HZ / hz_per_px
    for x in (centre_x - half, centre_x + half):
        d.line([(x, y0), (x, y1)], fill=CORR_COLOR, width=1)

    # Uncorrected hypothesis: the predicted S-curve.
    curve_fracs, curve_hz = curve
    sign = stats.get("frequency_axis_sign", 1)
    offset_px = (stats.get("curved_offset_hz") or 0.0) / hz_per_px
    # Time runs bottom to top on a SatNOGS waterfall, so the start of the pass
    # is drawn at y1 and the end at y0.
    pts = [
        (centre_x + sign * hz / hz_per_px + offset_px, y1 - f * (y1 - y0))
        for f, hz in zip(curve_fracs, curve_hz, strict=True)
    ]
    if len(pts) >= 2:
        d.line(pts, fill=UNCORR_COLOR, width=2)

    # What was actually measured.
    meas_fracs, meas_x, _ = track
    for f, xc in zip(meas_fracs, meas_x, strict=True):
        px = ox + crop_box.x0 + xc
        py = y0 + f * (y1 - y0)
        d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=TRACK_COLOR)

    d.text((10, 8), f"obs {obs['id']}   {verdict[0]}", fill=(245, 245, 245), font=f_title)
    d.text((10, 30), verdict[1][:110], fill=(200, 200, 205), font=f_body)
    d.text(
        (10, 46),
        f"{obs.get('station_name') or ''}  norad {obs.get('norad_cat_id')}  "
        f"max_alt {obs.get('max_altitude')} deg   hz/px {hz_per_px:.2f}   "
        f"predicted swing {stats.get('predicted_swing_hz') or 0:,.0f} Hz   "
        f"curved {_fmt(stats.get('sigma_curved'))} sigma   "
        f"vertical {_fmt(stats.get('sigma_vertical'))} sigma",
        fill=(200, 200, 205), font=f_body,
    )
    d.text((10, 62), "left: raw waterfall, unmodified.   right: same image annotated.",
           fill=(150, 150, 155), font=f_body)

    lx = ox + 10
    for colour, label in (
        (UNCORR_COLOR, "predicted Doppler curve (uncorrected hypothesis)"),
        (CORR_COLOR, f"+/-{CORRECTED_CORRIDOR_HZ:.0f} Hz corridor (corrected hypothesis)"),
        (TRACK_COLOR, "measured signal track"),
    ):
        d.rectangle([lx, 12, lx + 16, 24], fill=colour)
        d.text((lx + 22, 11), label, fill=colour, font=f_body)
        lx += 26 + int(d.textlength(label, font=f_body))
    return canvas


# ---------------------------------------------------------------------------
# API access, with an on-disk cache
# ---------------------------------------------------------------------------


class Throttled(Exception):
    """The API is rate limiting for longer than this run is willing to wait.

    Raised rather than exiting, so that whatever is already cached still gets
    measured and written. A partial answer with named gaps beats no answer, and
    a resumed run re-fetches nothing.
    """


def _cache_path(kind: str, key: str) -> Path:
    # Page caches are keyed by the query window. Without that, changing END_DATE
    # silently replays the previous window's pages under the same file names.
    p = CACHE_DIR / kind
    if kind == "pages":
        p = p / END_DATE.replace(":", "").replace("-", "")
    p.mkdir(parents=True, exist_ok=True)
    return p / key


def _get(url: str, timeout: float = 60.0) -> tuple[bytes, dict]:
    headers = {"User-Agent": USER_AGENT}
    last_exc: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        if attempt:
            wait = RETRY_DELAYS[attempt - 1]
            print(f"  retry {attempt}: waiting {wait}s")
            time.sleep(wait)
        try:
            resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 30))
                if retry_after > MAX_SLEEP_ON_429:
                    raise Throttled(
                        f"rate limited for another {retry_after:.0f}s "
                        f"({retry_after / 60:.1f} min)"
                    )
                print(f"  429, Retry-After={retry_after:.0f}s")
                time.sleep(retry_after + 1)
                continue
            resp.raise_for_status()
            return resp.content, dict(resp.headers)
        except httpx.TimeoutException as exc:
            last_exc = exc
            print(f"  timeout: {exc}")
    raise RuntimeError(f"all retries exhausted for {url}: {last_exc}")


def next_cursor(link_header: str | None) -> str | None:
    """The API pages through a cursor carried in the Link rel=next header.

    Query filters that look like pagination (id__lt and friends) are accepted
    with HTTP 200 and silently ignored, which returns page one forever.
    """
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        start, end = part.find("<"), part.find(">")
        if start == -1 or end == -1:
            continue
        qs = parse_qs(urlparse(part[start + 1:end]).query)
        if qs.get("cursor"):
            return qs["cursor"][0]
    return None


def fetch_candidates() -> list[dict]:
    params = {"format": "json", "end": END_DATE}
    url = API_BASE + "?" + urlencode(params)

    collected: list[dict] = []
    reserve: list[dict] = []
    seen: set[int] = set()
    rejected: dict[str, int] = defaultdict(int)
    page_index = 0

    def enough() -> bool:
        """Stop as soon as the vetted pool can satisfy the task.

        The anonymous quota is small and every page is a request, so paging past
        what is needed is what puts the run behind another hour-long throttle.
        Diversity is part of the rule because the task requires at least three
        client families, not just ten observations. MAX_PAGES bounds the worst
        case; the reserve covers the case where vetting has not caught up.
        """
        return (
            len(collected) >= TARGET_OBS
            and len({client_family(o) for o in collected}) >= 3
        )

    print(f"Fetching with-signal observations (end={END_DATE})")
    while url and not enough() and page_index < MAX_PAGES:
        cached = _cache_path("pages", f"page_{page_index:03d}.json")
        cached_hdr = _cache_path("pages", f"page_{page_index:03d}.headers.json")
        if cached.exists() and cached_hdr.exists():
            raw = cached.read_bytes()
            headers = json.loads(cached_hdr.read_text(encoding="utf-8"))
            print(f"  page {page_index}: cache")
        else:
            raw, headers = _get(url)
            cached.write_bytes(raw)
            cached_hdr.write_text(json.dumps(headers), encoding="utf-8")
            print(f"  page {page_index}: fetched")
            time.sleep(REQUEST_INTERVAL)

        page = json.loads(raw)
        if not page:
            break
        page_index += 1

        for obs in page:
            rejected["seen"] += 1
            if not (obs.get("waterfall") and obs.get("tle1") and obs.get("tle2")):
                rejected["no waterfall url or tle"] += 1
                continue
            if not obs.get("client_metadata") or rx_freq_of(obs) is None:
                rejected["no client_metadata or rx-freq"] += 1
                continue
            if obs["id"] in seen:
                rejected["duplicate id"] += 1
                continue
            seen.add(obs["id"])

            if obs.get("waterfall_status") == "with-signal":
                obs["_pool"] = "with-signal"
                collected.append(obs)
            elif obs.get("status") == "good":
                # Vetting lags capture, so a good observation whose waterfall has
                # not been vetted yet still carries a signal worth measuring.
                # Kept as a reserve so one throttle window is enough.
                obs["_pool"] = "good, waterfall not vetted"
                reserve.append(obs)
            else:
                rejected[f"waterfall_status={obs.get('waterfall_status')}"] += 1

        cursor = next_cursor(headers.get("link") or headers.get("Link"))
        if not cursor:
            break
        url = API_BASE + "?" + urlencode({**params, "cursor": cursor})

    print(f"  {len(collected)} with-signal candidates and {len(reserve)} unvetted "
          f"reserves from {page_index} page(s), {rejected['seen']} records inspected")
    for key, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
        if key != "seen":
            print(f"    {key}: {count}")

    if len(collected) < TARGET_OBS:
        need = TARGET_OBS - len(collected)
        print(f"  topping up with {min(need, len(reserve))} unvetted observations; "
              f"each is labelled in summary.json")
        collected.extend(reserve[:need])
    return collected


def download_waterfall(obs: dict) -> bytes:
    cached = _cache_path("waterfalls", f"{obs['id']}.png")
    if cached.exists():
        return cached.read_bytes()
    raw, _ = _get(obs["waterfall"], timeout=90.0)
    cached.write_bytes(raw)
    time.sleep(REQUEST_INTERVAL)
    return raw


def download_all(selected: list[dict]) -> dict[int, bytes]:
    """Fetch every waterfall before any measurement runs.

    All network work happens here and nothing after this point touches the
    network. If the window closes mid-way, the observations already cached are
    still measured, written and rendered.
    """
    images: dict[int, bytes] = {}
    for i, obs in enumerate(selected, 1):
        cached = _cache_path("waterfalls", f"{obs['id']}.png").exists()
        try:
            images[obs["id"]] = download_waterfall(obs)
            print(f"  [{i}/{len(selected)}] obs {obs['id']}: "
                  f"{'cache' if cached else 'fetched'}")
        except Throttled as exc:
            print(f"  [{i}/{len(selected)}] obs {obs['id']}: {exc}")
            print(f"  stopping downloads with {len(images)} of {len(selected)} in hand; "
                  f"measuring those and leaving the rest for a resumed run")
            break
        except Exception as exc:
            print(f"  [{i}/{len(selected)}] obs {obs['id']}: download failed: {exc}")
    return images


# SPACE-S5: the normalisation moved to physics.py, where AXIS_SIGN_CONVENTION lives,
# because the axis sign is reasoned about per client family and two copies of the
# family rule would let the evidence base and the grouping drift apart. Verified
# identical to the version this replaced on all 150 records of the corpus: zero
# disagreements, including the build-suffix and client_metadata fallback paths.


def select_diverse(candidates: list[dict], target: int) -> list[dict]:
    by_family: dict[str, list[dict]] = defaultdict(list)
    for obs in candidates:
        by_family[client_family(obs)].append(obs)
    for pool in by_family.values():
        pool.sort(key=lambda o: -(o.get("max_altitude") or 0))

    families = sorted(by_family, key=lambda f: -len(by_family[f]))
    print(f"  client families: {', '.join(f'{f}({len(by_family[f])})' for f in families)}")

    selected: list[dict] = []
    cursors = dict.fromkeys(families, 0)
    while len(selected) < target:
        progressed = False
        for fam in families:
            i = cursors[fam]
            if i >= len(by_family[fam]):
                continue
            selected.append(by_family[fam][i])
            cursors[fam] = i + 1
            progressed = True
            if len(selected) >= target:
                break
        if not progressed:
            break
    return selected


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def preflight() -> None:
    """Fail before spending a request if the environment cannot read an axis.

    parse_waterfall needs the OCR weights to derive Hz/px per observation.
    Without them every record degrades to NO_OCR_BACKEND, and discovering that
    after the downloads costs a rate-limit window rather than a second. A wrong
    EASYOCR_MODULE_PATH is silent otherwise: the parser logs a warning and
    returns a degraded record, so the run looks like it worked.
    """
    from pipeline.tracetriage import waterfall as wf

    try:
        wf._get_ocr_reader()
    except Exception as exc:
        sys.exit(
            f"preflight failed: no OCR backend ({exc}). Every observation would "
            f"degrade and the run would spend the rate-limit window for nothing.\n"
            f"Weights are expected at {wf._EASYOCR_MODEL_DIR}. Either put "
            f"craft_mlt_25k.pth and english_g2.pth there, or unset "
            f"EASYOCR_MODULE_PATH to fall back to the packaged default."
        )
    print(f"preflight: OCR reader ready at {wf._EASYOCR_MODEL_DIR}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    preflight()

    try:
        candidates = fetch_candidates()
    except Throttled as exc:
        sys.exit(f"no observation pages available: {exc}. Rerun after the window "
                 f"resets; cached pages under {CACHE_DIR} are reused.")
    if not candidates:
        sys.exit("no usable observations returned")

    selected = select_diverse(candidates, TARGET_OBS)
    print(f"\nSelected {len(selected)} observations "
          f"from {len({client_family(o) for o in selected})} client families")

    print("\nDownloading waterfalls (this is the last network step)")
    images = download_all(selected)
    if not images:
        sys.exit("no waterfalls could be fetched; rerun after the rate-limit window")
    print(f"  {len(images)} of {len(selected)} waterfalls available\n")

    results: list[dict] = []
    for obs in selected:
        obs_id = obs["id"]
        fam = client_family(obs)
        meta = json.loads(obs["client_metadata"])
        params = meta.get("radio", {}).get("parameters", {})
        record = {
            "obs_id": obs_id,
            "family": fam,
            "station": obs.get("ground_station"),
            "station_name": obs.get("station_name"),
            "norad_cat_id": obs.get("norad_cat_id"),
            "max_altitude": obs.get("max_altitude"),
            "rx_freq_hz": rx_freq_of(obs),
            "doppler-correction-per-sec": params.get("doppler-correction-per-sec"),
            "rigctl-port": params.get("rigctl-port"),
            "samp-rate-rx": params.get("samp-rate-rx"),
            "vetting_pool": obs.get("_pool"),
            "waterfall_status": obs.get("waterfall_status"),
            "observation_status": obs.get("status"),
        }
        print(f"[obs {obs_id}] {fam}  max_alt={obs.get('max_altitude')}")

        raw_png = images.get(obs_id)
        if raw_png is None:
            record |= {"status": "not_downloaded",
                       "error": "rate-limit window closed before this one was fetched"}
            results.append(record)
            print("  skipped: not downloaded")
            continue

        start_dt = datetime.fromisoformat(obs["start"].replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(obs["end"].replace("Z", "+00:00"))
        duration_s = (end_dt - start_dt).total_seconds()

        try:
            geom = parse_waterfall(
                image_data=raw_png,
                observation_id=obs_id,
                pass_duration_s=duration_s,
                rx_freq_hz=rx_freq_of(obs),
            )
        except Exception as exc:
            record |= {"status": "parse_exception", "error": str(exc)}
            results.append(record)
            print(f"  parse raised: {exc}")
            continue

        record |= {
            "derivation": geom.derivation,
            "hz_per_px": geom.hz_per_px,
            "seconds_per_px": geom.seconds_per_px,
            "centre_px": geom.centre_px,
            "geom_degraded": geom.degraded,
            "pass_duration_s": duration_s,
        }
        if geom.derivation == "failed" or not geom.hz_per_px or geom.crop_box is None:
            reason = f"waterfall geometry degraded: {geom.degraded}"
            record |= {"status": "geometry_failed", "verdict": "UNRESOLVED",
                       "reason": reason}
            # Still render it. An observation that could not be measured is part
            # of the evidence, and a missing image reads as a hidden one.
            empty = (np.empty(0), np.empty(0), np.empty(0))
            img = draw_overlay(
                raw_png, obs, geom, ([], []), empty, {},
                ("UNRESOLVED", reason),
            )
            out_path = OUT_DIR / f"overlay_{obs_id}.png"
            _save(img, out_path)
            record["overlay_file"] = out_path.name
            results.append(record)
            print(f"  geometry degraded: {geom.degraded}")
            continue

        try:
            curve_fracs, curve_hz, els = compute_doppler_curve(obs)
        except Exception as exc:
            record |= {"status": "physics_failed", "error": str(exc)}
            results.append(record)
            print(f"  physics failed: {exc}")
            continue
        record["sgp4_max_elevation_deg"] = max(els) if els else None

        record["centre_px_source"] = (
            "axis zero tick" if geom.centre_px is not None else "geometric midpoint"
        )

        rgb = np.array(Image.open(io.BytesIO(raw_png)).convert("RGB"))
        combined, scores, track = analyse(rgb, geom, (curve_fracs, curve_hz), els)
        verdict = combined["consensus"]
        stats = combined["primary"]

        record |= stats
        record |= {"status": "ok", "verdict": verdict[0], "reason": verdict[1]}

        print(f"  {verdict[0]}: {verdict[1]}")
        print(f"  predicted swing {stats['predicted_swing_hz']:,.0f} Hz, "
              f"curved {stats['sigma_curved']:.1f} sigma, "
              f"vertical {stats['sigma_vertical']:.1f} sigma")

        img = draw_overlay(
            raw_png, obs, geom, (curve_fracs, curve_hz), track, stats, verdict,
        )
        out_path = OUT_DIR / f"overlay_{obs_id}.png"
        _save(img, out_path)
        record["overlay_file"] = out_path.name
        results.append(record)

    (OUT_DIR / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    # ---- aggregate ----------------------------------------------------------
    ok = [r for r in results if r.get("status") == "ok"]
    tally: dict[str, int] = defaultdict(int)
    for r in results:
        tally[r.get("verdict", r.get("status", "?"))] += 1

    print("\n" + "=" * 92)
    print(f"{'obs':>10} {'family':<14} {'alt':>5} {'hz/px':>7} {'pred_Hz':>10} "
          f"{'curved_s':>10} {'vert_s':>10} {'vert_off':>10}  verdict")
    print("-" * 92)
    for r in results:
        if r.get("status") != "ok":
            print(f"{r['obs_id']:>10} {r['family']:<14} {'':>5} {'':>7} {'':>10} "
                  f"{'':>10} {'':>10} {'':>10}  {r.get('status')}")
            continue
        print(f"{r['obs_id']:>10} {r['family']:<14} {r['max_altitude'] or 0:>5.0f} "
              f"{r['hz_per_px']:>7.2f} {r['predicted_swing_hz']:>10,.0f} "
              f"{r['sigma_curved']:>10.1f} {r['sigma_vertical']:>10.1f} "
              f"{r['vertical_column_offset_hz']:>+10,.0f}  {r['verdict']}")

    print("\nverdict tally: " + ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    print(f"client families with a verdict: "
          f"{sorted({r['family'] for r in ok})}")
    print(f"doppler-correction-per-sec seen: "
          f"{sorted({str(r.get('doppler-correction-per-sec')) for r in results})}")
    print(f"rigctl-port seen: {sorted({str(r.get('rigctl-port')) for r in results})}")

    by_family_verdict: dict[str, set[str]] = defaultdict(set)
    for r in ok:
        by_family_verdict[r["family"]].add(r["verdict"])
    print("\nper-family verdicts:")
    for fam, verdicts in sorted(by_family_verdict.items()):
        print(f"  {fam:<16} {sorted(verdicts)}")

    print(f"\nsummary: {OUT_DIR / 'summary.json'}")
    print(f"overlays: {len([r for r in results if r.get('overlay_file')])} written to {OUT_DIR}")


if __name__ == "__main__":
    main()
