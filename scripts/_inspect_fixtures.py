"""Inspect the two fixture images to understand layout."""
import numpy as np
from PIL import Image

for name, path in [
    ("836px v2.3", "tests/fixtures/waterfall_836px_client_v2.3.png"),
    ("832px 2.1.2", "tests/fixtures/waterfall_832px_client_2.1.2.png"),
]:
    img = Image.open(path)
    print(f"{name}: mode={img.mode}, size={img.size}")
    arr = np.array(img.convert("RGB")).astype(int)
    h, w, _ = arr.shape
    non_white = arr.sum(axis=2) < 700
    col_sum = non_white.sum(axis=0)

    # find column runs with > 50% non-white pixels
    heavy = np.where(col_sum > h * 0.5)[0]
    if len(heavy):
        print(f"  heavy col range: {heavy[0]}..{heavy[-1]}")

    # find columns with ANY non-white pixel (>0)
    any_nonwhite = np.where(col_sum > 0)[0]
    if len(any_nonwhite):
        print(f"  any-nonwhite range: {any_nonwhite[0]}..{any_nonwhite[-1]}")

    # check x=700..w for colorbar
    for x in range(700, w):
        cnt = col_sum[x]
        if cnt > 10:
            print(f"  nonwhite col at x={x}: count={cnt}")

    # find tick region (a few rows below the plot bottom)
    row_sum = non_white.sum(axis=1)
    heavy_rows = np.where(row_sum > w * 0.3)[0]
    if len(heavy_rows):
        plot_y0, plot_y1 = int(heavy_rows[0]), int(heavy_rows[-1])
        print(f"  plot_y range: {plot_y0}..{plot_y1}")
        # look at tick band
        tick_band = arr[plot_y1+1:plot_y1+10]
        print(f"  tick band shape: {tick_band.shape}")
        # columns that are dark in tick band
        tick_dark = (tick_band.sum(axis=2) < 400).sum(axis=0)
        tick_cols = np.where(tick_dark >= 3)[0]
        print(f"  dark tick cols: {tick_cols[:20]}")

    print()
