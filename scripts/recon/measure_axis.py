"""Measure a SatNOGS waterfall's plot box and Hz-per-pixel from the rendered axis.

READ-ONLY RECON. Not the production module. Bob writes that one, with tests.

Why this exists: the waterfall PNG does not span `samp-rate-rx`. It spans a decimated
band whose width is only stated by the rendered matplotlib axis. Assuming the sample
rate compresses the Doppler corridor to about 5 pixels and makes the physics look
worthless. See docs/SATNOGS_API_RECON.md section 7.

Method:
  1. find the plot box as the largest run of columns that are mostly non-white
  2. find tick marks in the few rows directly below the plot bottom
  3. tick spacing in pixels, against the kHz-per-tick read off the labels, gives Hz/px

Step 3 currently needs the kHz-per-tick supplied by the caller, because reading the
label text requires OCR. Both layouts observed so far used 10 kHz per tick. Bob should
either OCR the labels or assert the assumption against a fixture per client family
rather than trusting it silently.

Run:  .venv/Scripts/python.exe scripts/recon/measure_axis.py <waterfall.png> [khz_per_tick]
"""

from __future__ import annotations

import sys

import numpy as np
from PIL import Image


def contiguous_runs(idx: np.ndarray) -> list[tuple[int, int]]:
    if len(idx) == 0:
        return []
    runs, start, prev = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i != prev + 1:
            runs.append((start, prev))
            start = i
        prev = i
    runs.append((start, prev))
    return runs


def measure(path: str, khz_per_tick: float = 10.0) -> dict:
    img = np.array(Image.open(path).convert("RGB")).astype(int)
    h, w, _ = img.shape
    non_white = img.sum(axis=2) < 700

    col_runs = [r for r in contiguous_runs(np.where(non_white.sum(axis=0) > h * 0.5)[0])
                if r[1] - r[0] > 20]
    if not col_runs:
        raise SystemExit(f"{path}: no plot area found")
    # the widest run is the spectrogram; narrower runs are the colorbar
    plot_x0, plot_x1 = max(col_runs, key=lambda r: r[1] - r[0])
    extras = [r for r in col_runs if (r[0], r[1]) != (plot_x0, plot_x1)]

    rows = np.where(non_white.sum(axis=1) > w * 0.3)[0]
    plot_y0, plot_y1 = int(rows[0]), int(rows[-1])

    # tick marks sit in the handful of rows immediately below the plot
    tick_band = (img[plot_y1 + 1: plot_y1 + 7].sum(axis=2) < 400).sum(axis=0)
    tick_runs = contiguous_runs(np.where(tick_band >= 4)[0])
    ticks = [(a + b) / 2 for a, b in tick_runs]

    out = {
        "path": path,
        "image": (w, h),
        "plot_box": (plot_x0, plot_y0, plot_x1, plot_y1),
        "plot_width_px": plot_x1 - plot_x0 + 1,
        "plot_height_px": plot_y1 - plot_y0 + 1,
        "extra_runs": extras,
        "ticks_x": [round(t, 1) for t in ticks],
    }
    if len(ticks) >= 3:
        spacing = float(np.median(np.diff(ticks)))
        out["tick_spacing_px"] = round(spacing, 2)
        out["hz_per_px"] = round(khz_per_tick * 1000.0 / spacing, 3)
        out["labelled_span_khz"] = round(khz_per_tick * (len(ticks) - 1), 1)
        out["full_plot_span_hz"] = round(out["hz_per_px"] * out["plot_width_px"], 0)
    return out


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    khz = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    for path in sys.argv[1:2]:
        for k, v in measure(path, khz).items():
            print(f"  {k:20s} {v}")
        print("\n  NOTE: khz_per_tick was supplied, not read. Confirm it against the image.")


if __name__ == "__main__":
    main()
