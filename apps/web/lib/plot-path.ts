/**
 * One SVG polyline builder, shared by every plot that draws a measured series.
 *
 * Why it lives here rather than inside a component: two components carried
 * near-identical copies of it (`pathFrom` in WaterfallViewer, `polyline` in
 * CorridorHero), both untestable because importing either component drags in the
 * whole data module, and both carrying the same defect.
 *
 * The defect: the copies chose the command with `i === 0 ? "M" : "L"`, so a series
 * whose first point is missing produced a path beginning with `L`. A path that does
 * not start with a moveto draws nothing, and nothing is what a reader sees: no error,
 * no warning, an empty overlay over a real image. The command is now chosen by whether
 * anything has actually been emitted, which is the property that matters.
 */

/**
 * Build an SVG path from a row series and a column series.
 *
 * Points where either coordinate is missing are skipped rather than interpolated,
 * because a gap in a propagated series is a gap, and joining across it would draw a
 * straight segment that no measurement supports.
 *
 * @param rows y coordinates
 * @param columns x coordinates
 * @param decimals fixed precision for both coordinates. Omit for the raw value,
 *   which is what a series already rounded at export time wants: rounding twice
 *   is how a coordinate picks up a second error.
 */
export function svgPolyline(
  rows: number[],
  columns: number[],
  decimals?: number,
): string {
  let out = "";
  let started = false;
  for (let i = 0; i < rows.length; i += 1) {
    const x = columns[i];
    const y = rows[i];
    if (x === undefined || y === undefined) continue;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const xs = decimals === undefined ? `${x}` : x.toFixed(decimals);
    const ys = decimals === undefined ? `${y}` : y.toFixed(decimals);
    out += `${started ? "L" : "M"}${xs} ${ys}`;
    started = true;
  }
  return out;
}
