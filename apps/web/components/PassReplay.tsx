"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { timeSeriesCursorX } from "@/components/PassTimeSeries";
import { type GroundBounds, projectGround, projectSky } from "@/lib/projection";

/**
 * One clock, four instruments.
 *
 * This is the piece that turns four plots into a single reading. A time cursor runs
 * over the pass and every instrument follows it: the marker on the sky track, the
 * marker on the ground track, the Doppler shift, the elevation, the slant range, and
 * the row of the waterfall that was being recorded at that instant. A reader can
 * watch the Doppler cross zero and see, in the same frame, that the satellite is at
 * its highest elevation and its shortest range. That relationship is the entire
 * physical basis of the corridor, and no arrangement of static plots states it as
 * directly as a shared cursor does.
 *
 * ## Why the motion is honest
 *
 * Every animated quantity is a value the pipeline exported. Nothing eases into
 * place, nothing counts up from zero, and no number is interpolated beyond the
 * linear interpolation between two propagated samples, which is stated on the page
 * and is the same interpolation the drawn polylines already perform between the same
 * two points. A count-up on a Brier score would be showing intermediate
 * measurements that were never taken. A cursor moving along a propagated track is
 * showing samples that were.
 *
 * ## Why it does not cost frames
 *
 * The expensive mistake would be re-rendering React every animation frame, which at
 * a hundred samples and four instruments means rebuilding several hundred SVG nodes
 * sixty times a second. Instead:
 *
 *   - The plots are drawn once, by the server, and never re-rendered. The cursors
 *     are server-rendered too; this component only writes their transforms.
 *   - A frame writes one `transform` attribute per cursor. A transform on an
 *     element that is already its own layer moves without layout and without paint.
 *   - The numeric readout is written with `textContent` on seven nodes, not through
 *     state, and only when the text actually changed.
 *   - React state changes twice per interaction: play, and pause.
 *
 * A per-frame CSS custom property was the obvious alternative and is a trap: a
 * custom property read by descendants invalidates the whole subtree's style
 * computation, which on a plot of several hundred nodes costs far more than writing
 * two attributes.
 *
 * ## Reduced motion
 *
 * `prefers-reduced-motion` is honoured by not offering playback at all, leaving the
 * scrubber. The information is in the cursor's position rather than in its travel,
 * so a reader who cannot tolerate motion loses nothing by moving it themselves. The
 * query is read at run time rather than only in CSS, because CSS can hide a control
 * but cannot stop a requestAnimationFrame loop.
 */

export type ReplayGeometry = {
  fracs: number[];
  azimuth_deg: number[];
  elevation_deg: number[];
  sub_lat_deg: number[];
  sub_lon_deg: number[];
  range_km: number[];
  altitude_km: number[];
  doppler_hz: number[] | null;
};

const FMT = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });

const READOUT: Array<{ key: string; label: string }> = [
  { key: "elapsed", label: "Elapsed" },
  { key: "elevation", label: "Elevation" },
  { key: "azimuth", label: "Azimuth" },
  { key: "doppler", label: "Doppler" },
  { key: "range", label: "Slant range" },
  { key: "altitude", label: "Altitude" },
  { key: "subpoint", label: "Subpoint" },
];

/** Linear interpolation between the two propagated samples that bracket t. */
export function sampleAt(series: number[], t: number): number {
  if (series.length === 0) return Number.NaN;
  const x = t * (series.length - 1);
  const i = Math.floor(x);
  const j = Math.min(series.length - 1, i + 1);
  const a = series[i];
  const b = series[j];
  if (a === undefined || b === undefined) return Number.NaN;
  return a + (b - a) * (x - i);
}

/** The pass is replayed in a fixed wall-clock time so two passes are comparable. */
const REPLAY_MS = 12_000;

export default function PassReplay({
  geometry,
  durationS,
  groundLons,
  bounds,
  imageHeight,
}: {
  geometry: ReplayGeometry;
  durationS: number;
  /** Longitudes already unwrapped by the plot, so the cursor cannot re-wrap them. */
  groundLons: number[];
  bounds: GroundBounds;
  imageHeight: number;
}) {
  const [playing, setPlaying] = useState(false);
  const [canPlay, setCanPlay] = useState(false);
  const [ready, setReady] = useState(false);
  /* True while the slider is being dragged, which is the other way the readout
     changes continuously. It is state rather than a ref because it decides
     aria-live, so it has to reach the DOM: two renders per drag, not one per
     input event. */
  const [scrubbing, setScrubbing] = useState(false);
  /* Set when a run or a drag has just ended, so the effect below repaints once with
     the region back in polite and the reader hears the value it settled on. */
  const announceRef = useRef(false);
  const settleRef = useRef<number | null>(null);

  const rafRef = useRef<number | null>(null);
  const startedRef = useRef<{ wall: number; from: number } | null>(null);
  const tRef = useRef(0);
  const rangeRef = useRef<HTMLInputElement | null>(null);
  const readoutRefs = useRef<Record<string, HTMLElement | null>>({});
  const nodesRef = useRef<{
    sky: SVGGElement | null;
    ground: SVGGElement | null;
    row: SVGGElement | null;
    time: SVGGElement | null;
  }>({ sky: null, ground: null, row: null, time: null });

  /* The two elapsed overlays, with their path lengths measured once. getTotalLength
     walks the path, so calling it per frame would put a geometry query inside the
     clock; the length cannot change because the server wrote the path and nothing
     rewrites it. The last written offset is kept so a change too small to see can
     be skipped: a stroke-dashoffset write re-rasterises the path, and the sky path
     is only about 232 user units long, so at 60 frames a second across a 12 second
     pass most frames move the end of the line a fraction of a unit. The threshold
     is one user unit, which at these plots' scales (1.03 to 1.30) is close enough
     to one device pixel to be the right unit to think in. Measured: 180 of 721
     frames write, so the guard drops 75 per cent of the rasters, and both writes
     together with a forced style flush cost 0.009 ms per frame. */
  const trailRef = useRef<
    Array<{ node: SVGGeometryElement; length: number; lastOffset: number }>
  >([]);

  // The cursors and the waterfall row marker are rendered by the server, so they
  // are looked up once rather than owned by React. That keeps the plots out of the
  // client bundle: this component ships the clock, not the drawing.
  useEffect(() => {
    nodesRef.current = {
      sky: document.getElementById("sky-cursor") as SVGGElement | null,
      ground: document.getElementById("ground-cursor") as SVGGElement | null,
      row: document.getElementById("waterfall-row-cursor") as SVGGElement | null,
      time: document.getElementById("timeseries-cursor") as SVGGElement | null,
    };
    const trails: Array<{
      node: SVGGeometryElement;
      length: number;
      lastOffset: number;
    }> = [];
    for (const id of ["sky-trail", "ground-trail"]) {
      const node = document.getElementById(id) as SVGGeometryElement | null;
      if (!node) continue;
      const length = node.getTotalLength();
      // A zero-length path would make every offset NaN and paint nothing, which is
      // indistinguishable from the overlay simply not being wired up.
      if (!Number.isFinite(length) || length <= 0) continue;
      node.style.strokeDasharray = String(length);
      node.style.strokeDashoffset = String(length);
      trails.push({ node, length, lastOffset: length });
    }
    trailRef.current = trails;

    setReady(true);
    document.documentElement.dataset.replay = "ready";
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setCanPlay(!query.matches);
    const onChange = (event: MediaQueryListEvent) => {
      setCanPlay(!event.matches);
      if (event.matches) setPlaying(false);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
      // Unmounting hides the cursors again, so a client-side navigation to a page
      // without a replay cannot leave three orphan markers frozen on its plots.
      delete document.documentElement.dataset.replay;
    };
  }, []);

  const paint = useCallback(
    (value: number) => {
      tRef.current = value;
      const az = sampleAt(geometry.azimuth_deg, value);
      const el = sampleAt(geometry.elevation_deg, value);
      const lat = sampleAt(geometry.sub_lat_deg, value);
      const lon = sampleAt(groundLons, value);
      const rng = sampleAt(geometry.range_km, value);
      const alt = sampleAt(geometry.altitude_km, value);
      const dop = geometry.doppler_hz
        ? sampleAt(geometry.doppler_hz, value)
        : Number.NaN;

      const { sky, ground, row, time } = nodesRef.current;
      if (sky) {
        // Below the horizon the satellite has no place on this plot, and the sky
        // track it is tracing has a gap there. Moving the cursor to the rim would
        // put it on a line that is not drawn, which is precisely what projectSky
        // used to do: it clamped, so during playback the cursor sat pinned to the
        // horizon ring while the track underneath it was absent. Hiding it for
        // those instants is the same statement the plot already makes.
        const point =
          Number.isFinite(az) && Number.isFinite(el) ? projectSky(az, el) : null;
        if (point === null) {
          sky.setAttribute("visibility", "hidden");
        } else {
          sky.removeAttribute("visibility");
          sky.setAttribute(
            "transform",
            `translate(${point[0].toFixed(2)} ${point[1].toFixed(2)})`,
          );
        }
      }
      if (ground && Number.isFinite(lat) && Number.isFinite(lon)) {
        const [x, y] = projectGround(bounds, lon, lat);
        ground.setAttribute("transform", `translate(${x.toFixed(2)} ${y.toFixed(2)})`);
      }
      if (row) {
        // Time runs bottom to top on a SatNOGS waterfall: row 0 is the END of the
        // pass. The cursor therefore travels upward as the clock runs forward.
        // Getting this backwards would put the marker on the wrong end of the trace
        // while still looking like it worked, which is the kind of error that
        // survives a screenshot review.
        //
        // The units are image rows, not CSS pixels, because the marker lives in an
        // SVG whose viewBox is the image's own pixel grid.
        row.setAttribute(
          "transform",
          `translate(0 ${((1 - value) * imageHeight).toFixed(2)})`,
        );
      }

      if (time) {
        // The time-series cursor moves only in x, because its line already spans
        // both panels vertically. One attribute, one axis.
        time.setAttribute(
          "transform",
          `translate(${timeSeriesCursorX(value).toFixed(2)} 0)`,
        );
      }

      // The elapsed overlays. One number each, and only when the end of the drawn
      // line has actually moved a pixel's worth along the path.
      for (const trail of trailRef.current) {
        const offset = trail.length * (1 - value);
        if (Math.abs(offset - trail.lastOffset) < 1) continue;
        trail.lastOffset = offset;
        trail.node.style.strokeDashoffset = offset.toFixed(2);
      }

      const write = (key: string, text: string) => {
        const node = readoutRefs.current[key];
        if (node && node.textContent !== text) node.textContent = text;
      };
      write("elapsed", `${(value * durationS).toFixed(0)} s`);
      write("elevation", Number.isFinite(el) ? `${el.toFixed(2)}°` : "—");
      write("azimuth", Number.isFinite(az) ? `${az.toFixed(1)}°` : "—");
      write(
        "doppler",
        Number.isFinite(dop)
          ? `${dop > 0 ? "+" : ""}${FMT.format(dop)} Hz`
          : "not measurable",
      );
      write("range", Number.isFinite(rng) ? `${FMT.format(rng)} km` : "—");
      write("altitude", Number.isFinite(alt) ? `${FMT.format(alt)} km` : "—");
      write(
        "subpoint",
        Number.isFinite(lat) && Number.isFinite(lon)
          ? `${lat.toFixed(2)}, ${lon.toFixed(2)}`
          : "—",
      );
    },
    [geometry, groundLons, bounds, imageHeight, durationS],
  );

  // Paint once the server-rendered nodes have been found, so the readout carries
  // real values before any interaction rather than a row of dashes.
  useEffect(() => {
    if (ready) paint(tRef.current);
  }, [ready, paint]);

  // One announcement per stop. The readout is silent while values are moving, so
  // without this a completed replay says nothing at all: the numbers would change
  // 700 times inside a region that was off and then never change again.
  useEffect(() => {
    if (playing || scrubbing || !announceRef.current) return;
    announceRef.current = false;
    paint(tRef.current);
  }, [playing, scrubbing, paint]);

  // A drag that ends while the component unmounts must not leave a timer holding a
  // reference to it.
  useEffect(
    () => () => {
      if (settleRef.current !== null) window.clearTimeout(settleRef.current);
    },
    [],
  );

  useEffect(() => {
    if (!playing) {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      startedRef.current = null;
      return;
    }

    startedRef.current = {
      wall: performance.now(),
      from: tRef.current >= 1 ? 0 : tRef.current,
    };

    const step = (now: number) => {
      const started = startedRef.current;
      if (!started) return;
      const value = Math.min(1, started.from + (now - started.wall) / REPLAY_MS);
      paint(value);
      // The scrubber is written directly rather than through state: a controlled
      // input on every frame is the re-render this component exists to avoid.
      if (rangeRef.current) rangeRef.current.value = String(value);
      if (value >= 1) {
        setPlaying(false);
        // The region was off for the whole run, so without this the reader hears
        // nothing at all from a completed replay. Painting the end state after the
        // flag flips means the announcement carries the values at set, which is the
        // one frame of a replay that is worth reading aloud.
        announceRef.current = true;
        return;
      }
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
  }, [playing, paint]);

  // Nothing renders until the cursors have been located. With scripting off this
  // component never mounts, the cursors stay hidden by CSS, and the page is the
  // static plots it always was.
  if (!ready) return null;

  return (
    <div className="replay">
      <div className="replay-controls">
        {canPlay && (
          <button
            type="button"
            className="replay-play"
            onClick={() => {
              // Pausing is a deliberate read: the reader wants to know where the
              // pass got to, so the stop announces once through the effect above.
              announceRef.current = true;
              setPlaying((p) => !p);
            }}
            aria-pressed={playing}
          >
            {playing ? "Pause" : "Replay the pass"}
          </button>
        )}
        <label className="replay-scrub">
          <span>Pass time</span>
          <input
            ref={rangeRef}
            type="range"
            min={0}
            max={1}
            step={0.001}
            defaultValue={0}
            aria-label="Scrub through the pass"
            onInput={(event) => {
              const value = Number(event.currentTarget.value);
              if (playing) setPlaying(false);
              // A keyboard step is one event and announces once, which is correct.
              // A mouse drag fires continuously, so the plot follows every event and
              // the readout text is only updated on a 200 ms trailing edge: a
              // dragged slider that announces forty intermediate positions is the
              // same defect as the animation loop, at a different rate.
              if (!scrubbing) setScrubbing(true);
              paint(value);
              if (settleRef.current !== null) window.clearTimeout(settleRef.current);
              settleRef.current = window.setTimeout(() => {
                settleRef.current = null;
                announceRef.current = true;
                setScrubbing(false);
              }, 200);
            }}
          />
        </label>
      </div>

      {/* A description list, so a screen reader gets each label with its value
          rather than a row of loose numbers.
          Announced when the reader asked for a value and silent while the animation
          runs. Polite was chosen originally because assertive "would interrupt on
          every frame of playback", which answers the wrong question: polite does not
          interrupt, and it still queues. REPLAY_MS is 12,000, so one press of Replay
          writes on the order of 700 batches across seven nodes, five of which change
          every frame. Off during playback means a press of Replay announces nothing
          until it stops, which is when there is a value worth hearing; a scrub or a
          keyboard step announces once, because it is one event.
          aria-atomic keeps a batch from being read as seven unrelated fragments. */}
      <dl
        className="replay-readout"
        aria-live={playing || scrubbing ? "off" : "polite"}
        aria-atomic="true"
      >
        {READOUT.map((item) => (
          <div key={item.key}>
            <dt>{item.label}</dt>
            <dd
              className="num"
              ref={(node) => {
                readoutRefs.current[item.key] = node;
              }}
            >
              &mdash;
            </dd>
          </div>
        ))}
      </dl>

      <p className="replay-note">
        One clock drives all four instruments below. Values between two propagated
        samples are linearly interpolated, the same interpolation the drawn tracks
        already perform between the same two points; there are{" "}
        {geometry.fracs.length} samples over {FMT.format(durationS)} seconds of
        recording. Playback runs for a fixed 12 seconds so two passes can be
        compared, and the elapsed figure is real seconds rather than replay seconds.
      </p>
    </div>
  );
}
