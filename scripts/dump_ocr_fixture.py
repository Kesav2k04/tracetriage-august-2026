"""Dump the OCR reading of each committed waterfall fixture to JSON.

Why this exists. Deriving Hz/px is two steps: read the axis tick labels, then fit
a scale to them. Only the first step needs a neural OCR model and its weights.
Pinning the second step behind that model would mean the single number the whole
project rests on, 123.46 and 80.00 Hz per pixel, could only ever be checked on
one laptop. Every CI runner and every clean clone would skip it.

So the OCR reading is captured once, here, and committed. `tests/test_waterfall.py`
feeds it to `parse_waterfall(..., ocr_results=...)` and asserts the derivation
offline. A separate `ocr`-marked test runs the live model where weights exist and
checks that it still reads what this file says it read.

Re-run only when a fixture image changes or the OCR pipeline changes:

    .venv\\Scripts\\python.exe scripts\\dump_ocr_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.tracetriage.waterfall import (  # noqa: E402
    _detect_plot_box,
    _extract_label_band,
    _load_rgb,
    _ocr_labels,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
OUT = FIXTURES / "ocr_labels.json"

IMAGES = {
    "waterfall_836px_client_v2.3.png": "836px client v2.3-compat, expect 123.46 Hz/px",
    "waterfall_832px_client_2.1.2.png": "832px client 2.1.2, expect 80.00 Hz/px",
}


def main() -> int:
    payload: dict[str, dict] = {}
    for name, note in IMAGES.items():
        path = FIXTURES / name
        rgb, w, h = _load_rgb(path)
        plot_box = _detect_plot_box(rgb)
        band, _, _ = _extract_label_band(rgb, plot_box)
        results = _ocr_labels(band)
        payload[name] = {
            "note": note,
            "image_width": w,
            "image_height": h,
            "ocr_results": [[float(x), str(t), float(c)] for x, t, c in results],
        }
        print(f"{name}: {len(results)} labels read")

    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
