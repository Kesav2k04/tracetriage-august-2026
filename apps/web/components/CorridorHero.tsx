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
 */
import Link from "next/link";

import { fmt, heroNulls, type HeroNulls } from "@/lib/data";

function polyline(rows: number[], px: number[]): string {
  let out = "";
  for (let i = 0; i < rows.length; i += 1) {
    const x = px[i];
    const y = rows[i];
    if (x === undefined || y === undefined) continue;
    out += `${i === 0 ? "M" : "L"}${x} ${y}`;
  }
  return out;
}

export default function CorridorHero({ data = heroNulls }: { data?: HeroNulls }) {
  const { width, height } = data.image;
  const d = data.distribution;

  // Stagger the nulls across 600 ms. The order is the file's order, which is by
  // ascending sigma, so the closest null arrives last and is on screen longest.
  const nullDelay = (i: number) => 0.15 + (i * 0.6) / Math.max(1, data.drawn.length);

  return (
    <section className="hero-plate" aria-labelledby="hero-plate-title">
      <div className="hero-plate-frame">
        <svg
          viewBox={`0 0 ${width} ${height}`}
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
              uniform map. This applies viridis, which is the map the observation
              page already defaults to, so the plate and the instrument agree.

              It is a colour map, not a contrast stretch: the greyscale value is
              first collapsed to luminance, then each channel is looked up in the
              same 17-stop table matplotlib generates for viridis. No pixel is
              brightened or darkened relative to another, so the ordering of the
              measured intensities is preserved exactly. Done as an SVG filter, it
              costs no JavaScript and no second copy of the image. */}
          <filter id="viridis-map" colorInterpolationFilters="sRGB">
            <feColorMatrix
              type="matrix"
              values="0.2126 0.7152 0.0722 0 0
                      0.2126 0.7152 0.0722 0 0
                      0.2126 0.7152 0.0722 0 0
                      0      0      0      1 0"
            />
            <feComponentTransfer>
              <feFuncR type="table" tableValues="0.267 0.282 0.279 0.259 0.230 0.199 0.173 0.149 0.128 0.121 0.158 0.246 0.369 0.516 0.678 0.846 0.993" />
              <feFuncG type="table" tableValues="0.005 0.095 0.175 0.252 0.322 0.388 0.449 0.508 0.567 0.626 0.684 0.739 0.789 0.831 0.864 0.887 0.906" />
              <feFuncB type="table" tableValues="0.329 0.417 0.483 0.525 0.546 0.555 0.558 0.557 0.551 0.533 0.502 0.452 0.383 0.294 0.190 0.100 0.144" />
            </feComponentTransfer>
          </filter>
          <image
            href={`/waterfalls/${data.obs_id}.webp`}
            x={0}
            y={0}
            width={width}
            height={height}
            className="hero-plate-image"
            filter="url(#viridis-map)"
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
              corridor, because a thin blue line over a noisy greyscale
              spectrogram loses its edge against the brighter pixels and reads as
              part of the noise. The casing is under the corridor and the same
              path, so it cannot displace it. */}
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
        </svg>
      </div>

      <div className="hero-plate-caption">
        <h2 id="hero-plate-title" className="hero-plate-title">
          The corridor the orbit predicts, and {d.n_nulls} that were built from the
          same numbers.
        </h2>
        <p className="hero-plate-body">
          Observation {data.obs_id}, a real SatNOGS capture. The white path is the
          Doppler shift computed from the satellite&rsquo;s orbit, shifted by one
          fitted frequency offset bounded at 50&nbsp;ppm. Each dark path is the same
          observation&rsquo;s own Doppler values in a scrambled time order, given the
          identical offset search. They keep every frequency value and the whole
          swing, and lose only the shape. {data.drawn.length} of the {d.n_nulls} are drawn,
          including the closest one.
        </p>
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
          visible trace in 70% of reviewed positives, and all three testable
          observations discriminate, which still does not establish a 70% rate: the
          exact one-sided 95% lower bound on three of three is 0.368. The gate is
          published as NOT_ESTABLISHED.{" "}
          <Link href={`/observation/${data.obs_id}`}>
            Open this observation
          </Link>
          , or read{" "}
          <Link href="/provenance">how every number here was generated</Link>.
        </p>
      </div>
    </section>
  );
}
