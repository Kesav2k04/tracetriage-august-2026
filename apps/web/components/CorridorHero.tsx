/**
 * The opening frame: one real waterfall, the corridor that was fitted to it, and
 * the corridors that could not fit.
 *
 * A curve drawn over an image is a picture. The same curve drawn among curves built
 * from that observation's own Doppler values, each given the identical bounded
 * offset search, none of which reached it, is a measurement. That is the
 * whole difference this project is arguing for, and it is the only thing on the page
 * that cannot be reproduced by a submission that has not measured anything.
 *
 * Every path here comes from `artifacts/HERO_NULLS.json`, written by
 * `scripts/export_hero_nulls.py`, which re-runs gate 3's own fit and refuses to
 * write unless seven statistics of the null distribution reproduce
 * `artifacts/GATE3_RECEIPT.json` to 1e-9. Nothing on this frame is drawn to look
 * like the measurement.
 *
 * **No client JavaScript.** This is a server component and the reveal is CSS on
 * `stroke-dashoffset` with `pathLength="1"`, so no length has to be measured in the
 * browser and nothing waits for hydration. The frame animates on a static document.
 * `prefers-reduced-motion: reduce` lands every path at its final state with no
 * animation at all, which is the honest reduced state here: the evidence is the
 * final frame, not the sweep.
 *
 * The verdict shown is NOT_ESTABLISHED and that is deliberate. Gate 3 asks for a
 * rate over observations, three of three is not enough to establish 70 per cent, and
 * the frame says so under the numbers rather than letting a strong per-observation
 * result imply a passed gate.
 *
 * Every figure in the limitation sentence is read from the gate's receipt, including
 * the words "3 of 3". They were typed prose until they were not: the sentence
 * asserted that all three testable observations discriminate, at a lower bound of
 * 0.368, with nothing reading either number. A review of this project proposes adding
 * `margin_over_best_null` to the `discriminates` criterion, which can drop an
 * observation from that count, and the sentence would have quietly become false while
 * every test stayed green. A number in a document that is not read from a receipt is
 * the defect this console exists to argue against, and it had one.
 */
import Link from "next/link";

import { fmt, heroNulls, type HeroNulls } from "@/lib/data";
import { svgPolyline } from "@/lib/plot-path";

// No rounding here: export_hero_nulls.py already writes these columns at the
// precision the frame needs, and rounding a rounded number twice is how a
// coordinate picks up a second error.
function polyline(rows: number[], px: number[]): string {
  return svgPolyline(rows, px);
}

export default function CorridorHero({ data = heroNulls }: { data?: HeroNulls }) {
  const { width, height } = data.image;
  const d = data.distribution;
  const g = data.gate;

  // Stagger the nulls across 600 ms. The order is the file's order, which is by
  // ascending sigma, so the closest null arrives last and is on screen longest.
  const nullDelay = (i: number) => 0.15 + (i * 0.6) / Math.max(1, data.drawn.length);

  return (
    <section className="hero-plate" aria-labelledby="hero-plate-title">
      {/* Landscape, and the axes are swapped with it. The stored plate is 620 by 1540:
          upright in a reading column it is either 800px tall or cropped, and cropped it
          showed the top fifth of one pass as a wall of noise with the corridor's shape
          entirely outside the frame. Turned a quarter turn the whole pass fits a band,
          time reads left to right the way every other time axis on this console does,
          and the one thing the frame exists to show, a smooth curve against six that
          wander, is legible at a glance.

          Nothing is cropped and nothing is scaled unevenly: the group inside is a rigid
          rotation, so every pixel and every path point keeps its place.
          `tests/test_hero_frame.py` maps the image corners and the corridor's own
          extremes through the same transform and fails if any of them leaves the
          frame. */}
      <div className="hero-plate-frame">
        <svg
          viewBox={`0 0 ${height} ${width}`}
          className="hero-plate-svg"
          role="img"
          aria-label={
            `Waterfall of SatNOGS observation ${data.obs_id} with ` +
            `${data.drawn.length + 1} corridors drawn over it. ` +
            `${data.drawn.length} are dark null corridors built by permuting this ` +
            `observation's own Doppler values in time; they wander across the ` +
            `frame. The last is the corridor predicted from the orbit, and it ` +
            `follows a smooth S curve. It scores ${fmt(data.true.sigma, 2)} sigma ` +
            `against a best null of ${fmt(d.max, 2)}, and none of the ` +
            `${d.n_nulls} nulls reached it.`
          }
        >
          {/* The stored waterfall is greyscale, and greyscale is a choice with a
              measurable cost: the human eye resolves far fewer steps of lightness
              than of hue, so a faint trace two or three levels above the noise
              floor is nearly invisible in grey and obvious in a perceptually
              uniform map. This applies inferno, which is the map every accent
              token in globals.css is sampled from, so the plate and the interface
              are reading off one table rather than two.

              It is a colour map, not a contrast stretch: the greyscale value is
              first collapsed to luminance, then each channel is looked up in the
              same 17-stop table matplotlib generates for inferno. No pixel is
              brightened or darkened relative to another, so the ordering of the
              measured intensities is preserved exactly. Done as an SVG filter, it
              costs no JavaScript and no second copy of the image.

              Inferno rather than viridis for one measurable reason: viridis spends
              its bottom third on blue-to-teal, where sRGB carries the least
              luminance, so a faint trace lands in the part of the ramp a display
              renders worst. Inferno's bottom third is a near-black plum and its
              top two thirds are the red-to-yellow run, which is where the ramp has
              room. The observation page still offers viridis and grey, so a reader
              who wants the other map has it. */}
          <filter id="inferno-map" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.2126 0.7152 0.0722 0 0
                      0.2126 0.7152 0.0722 0 0
                      0.2126 0.7152 0.0722 0 0
                      0      0      0      1 0"
            />
            {/* The display window, and where its two ends come from.
                This plate's intensities occupy a fifth of the range the file can
                hold. Handed straight to a colour map, four fifths of the ramp is
                spent on values that do not occur and every real value lands in one
                narrow band of it, which is why the unwindowed plate reads as a
                single flat colour rather than as a spectrogram.

                The low end is the noise floor, and it is not a percentile choice.
                Measured on the committed image, 23.3% of every pixel sits at exactly
                level 51 of 255, which is 0.2000: the receiver's floor, quantised.
                Nothing below a noise floor is a measurement, so that is where the
                display starts. The floor maps to exactly zero, so it renders black
                along with everything under it: 30.7% of the frame, which is the
                23.3% sitting on the floor plus the 7.4% beneath it. A third of this
                plate is receiver noise and the display says so rather than lifting
                it into the ramp.

                The high end is the 99.5th percentile, 0.4078. The brightest pixel in
                the frame is 0.6431 and it is a handful of samples; windowing to the
                maximum would spend a third of the ramp on them and flatten
                everything else. 0.47% clamps to white.

                slope = 1 / (0.4078 - 0.2000) = 4.8113 and
                intercept = -0.2000 * 4.8113 = -0.9623. It is a linear transform, so
                the ordering of the measured intensities is preserved exactly and no
                pixel changes rank against another. This is what vmin and vmax do in
                every spectrogram matplotlib has drawn, and what the SatNOGS renderer
                already did once to produce the greyscale.

                `tests/test_hero_window.py` recomputes the modal level and the
                percentile from the committed image and fails if either constant
                drifts from it, because a display constant that no longer matches its
                image is a number in a document that nothing reads. */}
            <feComponentTransfer>
              <feFuncR type="linear" slope="4.8113" intercept="-0.9623" />
              <feFuncG type="linear" slope="4.8113" intercept="-0.9623" />
              <feFuncB type="linear" slope="4.8113" intercept="-0.9623" />
            </feComponentTransfer>
            <feComponentTransfer>
              <feFuncR type="table" tableValues="0.001 0.042 0.129 0.238 0.342 0.441 0.541 0.640 0.736 0.822 0.894 0.947 0.978 0.988 0.975 0.948 0.988" />
              <feFuncG type="table" tableValues="0.000 0.028 0.047 0.037 0.062 0.099 0.135 0.171 0.216 0.275 0.353 0.449 0.558 0.675 0.798 0.917 0.998" />
              <feFuncB type="table" tableValues="0.014 0.141 0.291 0.396 0.429 0.432 0.415 0.381 0.330 0.266 0.194 0.115 0.035 0.065 0.206 0.411 0.645" />
            </feComponentTransfer>
          </filter>
          {/* (col, row) -> (height - row, col). Right-to-left, as SVG composes them:
              rotate first, then translate the result back into the viewBox. Row 0 is
              the end of the pass, so this puts the start of the pass on the left. */}
          <g transform={`translate(${height} 0) rotate(90)`}>
          <image
            href={`/waterfalls/${data.obs_id}.webp`}
            x={0}
            y={0}
            width={width}
            height={height}
            className="hero-plate-image"
            filter="url(#inferno-map)"
            preserveAspectRatio="none"
          />
          <g className="hero-plate-nulls">
            {data.drawn.map((n, i) => (
              <path
                key={n.seed}
                d={polyline(data.rows, n.px)}
                pathLength={1}
                className={
                  n.is_best_null ? "hero-null hero-null-best" : "hero-null"
                }
                style={{ animationDelay: `${nullDelay(i).toFixed(3)}s` }}
              />
            ))}
          </g>
          {/* Drawn twice. The casing is a wider near-black stroke under the
              corridor, because a thin light line over a colour-mapped spectrogram
              loses its edge wherever the map runs bright and reads as part of the
              noise. Inferno's top third makes that worse than viridis did, so the
              casing matters more now, not less. It is under the corridor and on the
              same path, so it cannot displace it. */}
          <path
            d={polyline(data.rows, data.true.px)}
            pathLength={1}
            className="hero-corridor-casing"
          />
          <path
            d={polyline(data.rows, data.true.px)}
            pathLength={1}
            className="hero-corridor"
          />
          </g>
        </svg>
        <p className="hero-plate-axis hero-plate-axis-time">
          Time, {String.fromCharCode(0x2192)} one pass
        </p>
        <p className="hero-plate-axis hero-plate-axis-freq">
          Received frequency {String.fromCharCode(0x2191)}
        </p>
      </div>

      <div className="hero-plate-caption">
        <h2 id="hero-plate-title" className="hero-plate-title">
          The corridor the orbit predicts, and {d.n_nulls} that were built from the
          same numbers.
        </h2>
        {/* Both paragraphs in one cell. `.hero-plate-body` is placed explicitly at column
            one, row two, so a second one landed on top of the first: 572 by 72 pixels of
            overprinted text on the landing page. They stack inside a wrapper instead. */}
        <div className="hero-plate-bodies">
        <p className="hero-plate-body">
          Observation {data.obs_id}, a real SatNOGS capture. The white path is the
          Doppler shift computed from the satellite&rsquo;s orbit, shifted by one
          fitted frequency offset bounded at 50&nbsp;ppm. Each dark path is the same
          observation&rsquo;s own Doppler values in a scrambled time order, given the
          identical offset search. They keep every frequency value and the whole
          swing, and lose only the shape. {data.drawn.length} of the {d.n_nulls} are drawn,
          including the closest one.
        </p>
        {/* Moved here from the colophon, where it was restated at the foot of all nine
            pages. How a plate is encoded is a fact about the plate, and this is the
            first one a reader meets. */}
        <p className="hero-plate-body">
          The plate is greyscale as the network published it, to within 1 part in 255, so
          every grey is a measured intensity and every coloured mark is something the
          pipeline computed. The colour is a map applied for legibility and changes no
          pixel&rsquo;s rank against another.
        </p>
        </div>
        <dl className="hero-plate-readout">
          <div>
            <dt>Fitted corridor</dt>
            <dd>{fmt(data.true.sigma, 2)}&nbsp;&sigma;</dd>
          </div>
          <div>
            <dt>Best of {d.n_nulls} nulls</dt>
            <dd>{fmt(d.max, 2)}&nbsp;&sigma;</dd>
          </div>
          <div>
            <dt>Nulls that reached it</dt>
            <dd>
              {d.n_at_least} of {d.n_nulls}
            </dd>
          </div>
          <div>
            <dt>One-sided p</dt>
            <dd>{fmt(d.p_value, 3)}</dd>
          </div>
        </dl>
        <p className="hero-plate-limit">
          This is one observation. Gate 3 asked for the corridor to intersect a
          visible trace in {fmt(g.threshold * 100, 0)}% of reviewed positives, and{" "}
          {g.observations_discriminating} of {g.observations_scored} testable
          observations discriminate, which still does not establish a{" "}
          {fmt(g.threshold * 100, 0)}% rate: the exact one-sided 95% lower bound on{" "}
          {g.observations_discriminating} of {g.observations_scored} is{" "}
          {fmt(g.rate_lower_bound_95, 3)}. The gate is published as {g.verdict}.{" "}
          <Link href={`/observation/${data.obs_id}`}>
            Open this observation
          </Link>
          , or read{" "}
          <Link href="/provenance/">how every number here was generated</Link>.
        </p>
      </div>
    </section>
  );
}
