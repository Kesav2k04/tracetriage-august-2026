"""Render a static evidence card for one observation triage receipt.

Reads artifacts/TRIAGE_RECEIPT.json and the snapshot waterfall PNG, then
produces a self-contained static HTML file (no external dependencies, no JS,
no network requests at render time).

The card shows:
  - Waterfall image (base64-inlined)
  - Physics corridor overlay (uncorrected S-curve or corrected vertical band)
    drawn with matplotlib and inlined as a base64 PNG
  - Detected trace residual summary (from A3 summary.json)
  - Artifact checks (usable, sha256, geometry version)
  - Current API label (waterfall_status)
  - Provenance (source URL, license, retrieved at)
  - Deterministic reason codes (from fixed rule table, not model attribution)
  - Calibrated HOG-LR probability
  - Gate-3 corridor intersection result with numbers

Usage
-----
    python scripts/render_evidence_card.py \\
        --receipt   artifacts/TRIAGE_RECEIPT.json \\
        --snapshot  D:/tracetriage_data/snap-stage1 \\
        --out       artifacts/evidence_card_14740031.html

The rendered card must display correctly with the network adapter disabled
(all images and styles are inlined).
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _png_to_data_uri(path: Path) -> str:
    """Read a PNG and return a data: URI."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _render_corridor_overlay(
    receipt: dict,
    wf_path: Path,
    a3_entry: dict,
    raw_obs: dict,
    snapshot_dir: Path,
) -> str:
    """Render the waterfall with corridor overlay and return as data URI.

    Uses matplotlib to draw:
      - The raw waterfall (greyscale)
      - The physics corridor (±half_width from predicted curve)
      - A vertical marker at the trace centre-of-mass (from A3)
    """
    try:
        import matplotlib  # noqa: PLC0415
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
    except ImportError as exc:
        logger.warning("matplotlib/PIL not available for overlay: %s", exc)
        return ""

    from pipeline.tracetriage.physics import (  # noqa: PLC0415
        AXIS_SIGN_CONVENTION,
        corridor_columns,
        corridor_for_obs,
    )

    phys = corridor_for_obs(raw_obs)
    if phys.degraded:
        logger.warning("Physics degraded, cannot draw corridor")
        return ""

    # Use A3-measured geometry instead of re-running OCR (geometry is already
    # in the A3 summary and is numerically identical to what waterfall.py produces).
    hz_per_px = a3_entry.get("hz_per_px")
    centre_px_from_a3 = a3_entry.get("centre_px")
    if not hz_per_px or centre_px_from_a3 is None:
        logger.warning("A3 geometry missing, cannot draw corridor")
        return ""

    # Determine which corridor to draw based on A3 verdict.
    obs_id = receipt["observation_id"]
    a3_verdict = a3_entry.get("verdict", "UNRESOLVED")
    if a3_verdict == "UNCORRECTED":
        corridor = phys.uncorrected
        corridor_label = "Uncorrected Doppler corridor"
        corridor_colour = "#ff6600"
    elif a3_verdict == "CORRECTED":
        corridor = phys.corrected
        corridor_label = "Corrected residual corridor"
        corridor_colour = "#00aaff"
    else:
        corridor = phys.uncorrected
        corridor_label = "Uncorrected corridor (unresolved)"
        corridor_colour = "#aaaaaa"

    # Load waterfall image.
    try:
        img = np.array(Image.open(wf_path).convert("L"))
    except Exception as exc:
        logger.warning("Cannot load waterfall: %s", exc)
        return ""

    h, w = img.shape
    # A3 measured centre_px as crop-relative (the plot-box pixel column for 0 Hz).
    # The waterfall image file is the full downloaded image, so we need to crop
    # to the plot box first.  A3 summary stores the family which tells us the layout.
    # Use family-based crop boxes derived from A3's measured values.
    # Family "1.6" → plot x: 66..686, y from non-white detection.
    # Use A3 n_drawn_track_points to estimate crop height.
    family = a3_entry.get("family", "")
    if family.startswith("1."):
        # Layout 1.x: x=66..686
        px0, px1 = 66, 686
    elif family.startswith("2."):
        # Layout 2.x: x=74..677
        px0, px1 = 74, 677
    else:
        px0, px1 = 66, 686  # default

    # Vertical extent: use the full image height (the pixel-time mapping uses row_frac
    # derived from the full crop height).  Detect the plot rows by looking for
    # non-white rows in the x-range.
    col_band = img[:, max(0, px0):min(w, px1)]
    row_occ = (col_band < 250).sum(axis=1) / max(col_band.shape[1], 1)
    heavy_rows = (row_occ > 0.25).nonzero()[0]
    if len(heavy_rows) > 10:
        py0, py1 = int(heavy_rows[0]), int(heavy_rows[-1]) + 1
    else:
        py0, py1 = 0, h

    img_crop = img[py0:py1, px0:px1]
    centre_px_crop = float(centre_px_from_a3)  # A3 stores crop-relative value

    crop_h, crop_w = img_crop.shape

    # Map corridor to pixel columns across image height.
    # A3's freq_offset: the measured offset of the trace from rx_freq.
    # For the uncorrected case the corridor is centred on the predicted Doppler
    # curve with freq_offset_hz=0 (no correction needed — it IS the curve).
    cols_centre = corridor_columns(corridor, hz_per_px, centre_px_crop, crop_h)
    cols_lo = cols_centre - corridor.half_width_hz / hz_per_px
    cols_hi = cols_centre + corridor.half_width_hz / hz_per_px

    # Row indices.
    rows = np.arange(crop_h)

    # Trace centre column from A3 (curved_offset_hz is offset from rx_freq).
    # For the UNCORRECTED trace, the trace follows the predicted curve, so its
    # column ≈ cols_centre at each row.  We show the measured A3 offset line.
    trace_offset_hz = a3_entry.get("curved_offset_hz", 0.0)
    trace_col = centre_px_crop + AXIS_SIGN_CONVENTION * trace_offset_hz / hz_per_px

    fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
    ax.imshow(img_crop, cmap="gray", aspect="auto",
              extent=[0, crop_w, crop_h, 0], origin="upper")

    # Corridor fill.
    ax.fill_betweenx(rows, cols_lo, cols_hi,
                     alpha=0.25, color=corridor_colour, label=corridor_label)
    # Corridor edges.
    ax.plot(cols_lo, rows, "--", color=corridor_colour, linewidth=0.8, alpha=0.8)
    ax.plot(cols_hi, rows, "--", color=corridor_colour, linewidth=0.8, alpha=0.8)
    ax.plot(cols_centre, rows, "-", color=corridor_colour, linewidth=1.2, alpha=0.9,
            label="Predicted curve")

    # Trace marker.
    ax.axvline(trace_col, color="#ffdd00", linewidth=1.2, linestyle=":",
               alpha=0.9, label=f"A3 trace CoM ({trace_offset_hz:+.0f} Hz)")

    ax.set_xlim(0, crop_w)
    ax.set_ylim(crop_h, 0)
    ax.set_xlabel("Pixel column (frequency axis)")
    ax.set_ylabel("Pixel row (time, bottom=start)")
    ax.set_title(f"Obs {obs_id} — {a3_verdict}", fontsize=11)
    ax.legend(fontsize=8, loc="upper right")

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _load_a3_entry(obs_id: int) -> dict:
    path = Path("artifacts/a3_overlays/summary.json")
    if not path.exists():
        return {}
    for entry in json.loads(path.read_bytes()):
        if entry.get("obs_id") == obs_id:
            return entry
    return {}


def _load_raw_obs(snapshot_dir: Path, obs_id: int) -> dict:
    pages_dir = snapshot_dir / "pages"
    if not pages_dir.exists():
        return {}
    for page_file in sorted(pages_dir.glob("*.json")):
        try:
            records = json.loads(page_file.read_bytes())
        except Exception:
            continue
        if isinstance(records, list):
            for rec in records:
                if rec.get("id") == obs_id:
                    return rec
    return {}


def render_card(
    receipt: dict,
    wf_path: Path,
    snapshot_dir: Path,
) -> str:
    """Return a complete self-contained HTML evidence card string."""
    obs_id = receipt["observation_id"]
    a3_entry = _load_a3_entry(obs_id)
    raw_obs = _load_raw_obs(snapshot_dir, obs_id)

    # Waterfall image.
    wf_data_uri = ""
    if wf_path.exists():
        wf_data_uri = _png_to_data_uri(wf_path)

    # Corridor overlay.
    overlay_uri = ""
    if wf_path.exists() and raw_obs:
        logger.info("Rendering corridor overlay…")
        overlay_uri = _render_corridor_overlay(receipt, wf_path, a3_entry, raw_obs, snapshot_dir)

    ev = receipt.get("evidence", {})
    sc = receipt.get("scores", {})
    pr = receipt.get("provenance", {})

    sigma_curved   = a3_entry.get("sigma_curved",   "n/a")
    sigma_vertical = a3_entry.get("sigma_vertical", "n/a")
    a3_verdict     = a3_entry.get("verdict",        "n/a")
    hz_per_px      = a3_entry.get("hz_per_px",      "n/a")
    a3_reason      = a3_entry.get("reason",         "n/a")

    intersects = ev.get("corridor_intersects_trace")
    intersects_str = "✓ YES" if intersects is True else ("✗ NO" if intersects is False else "—")
    intersects_colour = (
        "#1a9e5c" if intersects is True
        else "#c0392b" if intersects is False
        else "#888"
    )

    prob = sc.get("calibrated_probability")
    prob_str = f"{prob:.3f}" if prob is not None else "—"
    prob_bar = int((prob or 0) * 100)

    # Formatted once here rather than inline in the template. These were written
    # as `value and f"..." or "—"`, which renders a legitimate 0.0 as the absent
    # placeholder, because 0.0 is falsy. An evidence axis reading exactly zero is
    # a real measurement and has to be distinguishable from a missing one.
    def _num(value: Any, fmt: str) -> str:
        return format(value, fmt) if isinstance(value, (int, float)) else "—"

    corridor_shape_label = (
        "Uncorrected (S-curve)" if a3_verdict == "UNCORRECTED"
        else "Corrected (near-vertical)" if a3_verdict == "CORRECTED"
        else "Unresolved"
    )
    sigma_curved_txt = _num(sigma_curved, ".1f")
    sigma_vertical_txt = _num(sigma_vertical, ".1f")
    target_consistency_txt = _num(ev.get("target_consistency"), ".3f")
    curved_offset_txt = (
        f"{a3_entry['curved_offset_hz']:+.0f} Hz"
        if isinstance(a3_entry.get("curved_offset_hz"), (int, float)) else "—"
    )
    predicted_swing_txt = (
        f"{a3_entry['predicted_swing_hz']:.0f} Hz"
        if isinstance(a3_entry.get("predicted_swing_hz"), (int, float)) else "—"
    )
    source_url = pr.get("source_url", "")
    source_url_txt = source_url or "—"

    decision_colour = {
        "flag_for_review": "#c0392b",
        "no_conflict":     "#1a9e5c",
        "abstain":         "#888",
    }.get(receipt.get("decision", ""), "#888")

    reason_codes_html = "".join(
        f'<span class="badge">{rc}</span> ' for rc in receipt.get("reason_codes", [])
    )

    overlay_section = ""
    if overlay_uri:
        overlay_section = f'''
        <div class="section">
          <h2>Corridor overlay</h2>
          <img src="{overlay_uri}" style="max-width:100%;border:1px solid #ddd;"
               alt="Corridor overlay">
          <p class="caption">Orange fill: ±2000 Hz Doppler corridor. Orange line: predicted S-curve.
          Yellow dotted: A3 trace centre-of-mass. Time runs bottom→top (row 0 = pass end).</p>
        </div>'''

    wf_section = ""
    if wf_data_uri:
        wf_section = f'''
        <div class="section">
          <h2>Waterfall (raw)</h2>
          <img src="{wf_data_uri}" style="max-width:100%;border:1px solid #ddd;"
               alt="Waterfall {obs_id}">
        </div>'''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>TraceTriage Evidence Card — Obs {obs_id}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
          font-size: 14px; line-height: 1.6; background: #f7f8fa;
          color: #1f2328; margin: 0; padding: 0; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 24px 20px; }}
  h1 {{ font-size: 18px; border-bottom: 2px solid #e5e7eb;
       padding-bottom: 8px; margin-bottom: 16px; }}
  h2 {{ font-size: 13px; font-weight: 600; color: #57606a; text-transform: uppercase;
        letter-spacing: 0.04em; margin: 24px 0 8px; }}
  .section {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 6px;
              padding: 16px 20px; margin-bottom: 16px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
  .row {{ display: flex; justify-content: space-between; border-bottom: 1px solid #f0f0f0;
          padding: 4px 0; }}
  .row:last-child {{ border-bottom: none; }}
  .label {{ color: #57606a; font-size: 12px; }}
  .value {{ font-weight: 500; font-size: 12px; }}
  .badge {{ background: #e8f0fe; color: #3b5bdb; font-size: 11px; font-weight: 600;
            padding: 2px 8px; border-radius: 10px; display: inline-block; margin: 1px; }}
  .decision-pill {{ display: inline-block; padding: 4px 14px; border-radius: 20px;
                    font-weight: 700; font-size: 13px; color: #fff;
                    background: {decision_colour}; }}
  .gate3-result {{ font-size: 15px; font-weight: 700; color: {intersects_colour}; }}
  .prob-bar-bg {{ height: 10px; background: #e5e7eb; border-radius: 5px; overflow: hidden;
                  margin-top: 4px; }}
  .prob-bar-fill {{ height: 100%; background: #3b82d4; border-radius: 5px;
                    width: {prob_bar}%; }}
  .caption {{ color: #57606a; font-size: 11px; margin-top: 6px; }}
  footer {{ margin-top: 32px; padding-top: 12px; border-top: 1px solid #e5e7eb;
            text-align: center; font-size: 11px; color: #888; }}
  .mono {{ font-family: "SFMono-Regular", Consolas, monospace; font-size: 11px; }}
</style>
</head>
<body>
<div class="container">
  <h1>TraceTriage Evidence Card — Observation {obs_id}</h1>

  <div class="section">
    <h2>Decision</h2>
    <div style="margin-bottom:10px;">
      <span class="decision-pill">{receipt.get("decision","").upper().replace("_"," ")}</span>
    </div>
    <div class="row">
      <span class="label">Reason codes</span>
      <span class="value">{reason_codes_html}</span>
    </div>
    <div class="row">
      <span class="label">API label (waterfall_status)</span>
      <span class="value">{pr.get("api_label","—")}</span>
    </div>
    <div class="row">
      <span class="label">Label origin</span>
      <span class="value">{pr.get("label_origin","—")}</span>
    </div>
  </div>

  <div class="grid2">
    <div class="section">
      <h2>Gate 3: Corridor ∩ Trace</h2>
      <p class="gate3-result">{intersects_str}</p>
      <div class="row">
        <span class="label">Corridor type</span>
        <span class="value">{corridor_shape_label}</span>
      </div>
      <div class="row">
        <span class="label">Half-width</span>
        <span class="value">{"±2000 Hz" if a3_verdict == "UNCORRECTED" else "±1200 Hz"}</span>
      </div>
      <div class="row">
        <span class="label">Trace half-extent (residual_hz)</span>
        <span class="value">{ev.get("residual_hz") and f"{ev['residual_hz']:.1f} Hz" or "—"}</span>
      </div>
      <div class="row">
        <span class="label">A3 sigma (curved vs vertical)</span>
        <span class="value">{sigma_curved_txt} vs {sigma_vertical_txt}</span>
      </div>
      <div class="row">
        <span class="label">A3 verdict</span>
        <span class="value">{a3_verdict}</span>
      </div>
    </div>

    <div class="section">
      <h2>Model score</h2>
      <div class="row">
        <span class="label">Calibrated P(signal)</span>
        <span class="value">{prob_str}</span>
      </div>
      <div class="prob-bar-bg"><div class="prob-bar-fill"></div></div>
      <div class="row" style="margin-top:8px;">
        <span class="label">Target consistency</span>
        <span class="value">{target_consistency_txt}</span>
      </div>
      <div class="row">
        <span class="label">Artifact usable</span>
        <span class="value">{"✓" if ev.get("artifact_usable") else "✗"}</span>
      </div>
      <div class="row">
        <span class="label">Physics available</span>
        <span class="value">{"✓" if ev.get("physics_available") else "✗"}</span>
      </div>
      <div class="row">
        <span class="label">Geometry schema version</span>
        <span class="value">{ev.get("waterfall_geometry_version","—")}</span>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>A3 trace measurement</h2>
    <p class="caption">{a3_reason}</p>
    <div class="row">
      <span class="label">Hz/px (measured from axis ticks)</span>
      <span class="value">{f"{hz_per_px:.4f}" if isinstance(hz_per_px,float) else hz_per_px}</span>
    </div>
    <div class="row">
      <span class="label">Trace offset from rx_freq (curved_offset_hz)</span>
      <span class="value">{curved_offset_txt}</span>
    </div>
    <div class="row">
      <span class="label">Predicted Doppler swing</span>
      <span class="value">{predicted_swing_txt}</span>
    </div>
  </div>

  <div class="section">
    <h2>Provenance</h2>
    <div class="row">
      <span class="label">Source</span>
      <span class="value"><a href="{source_url}" class="mono">{source_url_txt}</a></span>
    </div>
    <div class="row">
      <span class="label">Retrieved at</span>
      <span class="value">{pr.get("retrieved_at","—")}</span>
    </div>
    <div class="row">
      <span class="label">License</span>
      <span class="value">{pr.get("license","—")}</span>
    </div>
    <div class="row">
      <span class="label">Artifact SHA-256</span>
      <span class="value mono">{pr.get("artifact_sha256","—")[:16]}…</span>
    </div>
    <div class="row">
      <span class="label">Station</span>
      <span class="value">{pr.get("station_id","—")}</span>
    </div>
    <div class="row">
      <span class="label">Model checksum (BASELINE_RECEIPT)</span>
      <span class="value mono">{receipt.get("model_checksum","—")[:16]}…</span>
    </div>
    <div class="row">
      <span class="label">Generated at</span>
      <span class="value">{receipt.get("generated_at","—")}</span>
    </div>
    <div class="row">
      <span class="label">Snapshot</span>
      <span class="value">{receipt.get("snapshot_id","—")}</span>
    </div>
  </div>

  {overlay_section}
  {wf_section}

  <footer>Made with IBM Bob &nbsp;|&nbsp; TraceTriage August 2026 &nbsp;|&nbsp;
  All numbers from <code>artifacts/TRIAGE_RECEIPT.json</code> &nbsp;|&nbsp;
  Reason codes from fixed rule table, not model attribution</footer>
</div>
</body>
</html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a static HTML evidence card from a triage receipt."
    )
    parser.add_argument("--receipt", type=Path,
                        default=Path("artifacts/TRIAGE_RECEIPT.json"))
    parser.add_argument("--snapshot", type=Path,
                        default=Path("D:/tracetriage_data/snap-stage1"))
    parser.add_argument("--out", type=Path,
                        default=None,
                        help="Output HTML path (default: artifacts/evidence_card_<obs_id>.html)")
    args = parser.parse_args(argv)

    if not args.receipt.exists():
        logger.error("Receipt not found: %s", args.receipt)
        return 1

    receipt = json.loads(args.receipt.read_bytes())
    obs_id = receipt["observation_id"]
    snapshot_dir = args.snapshot.resolve()
    wf_path = snapshot_dir / "waterfalls" / f"waterfall_{obs_id}.png"

    out_path = args.out or Path(f"artifacts/evidence_card_{obs_id}.html")

    logger.info("Rendering evidence card for obs %d → %s", obs_id, out_path)
    html = render_card(receipt, wf_path, snapshot_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    logger.info("Card written: %s  (%d bytes)", out_path, len(html))

    print(f"\nEvidence card: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
