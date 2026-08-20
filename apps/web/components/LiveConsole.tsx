"use client";

/**
 * The one interactive instrument on this console.
 *
 * It has to hold four states honestly and they are genuinely different things, which is
 * why this is a state machine and not a loading boolean:
 *
 *   idle       nothing asked yet
 *   measuring  a pass is being downloaded and fitted, tens of seconds, with the elapsed
 *              time on screen because a spinner with no clock reads as broken at 20s
 *   measured   a complete measurement, which INCLUDES the UNRESOLVED verdict: an image
 *              that does not settle the Doppler convention is a result, not a failure
 *   refused    a named reason from the engine (no stored waterfall, an axis that cannot
 *              be read, elements that will not propagate) or a transport problem
 *
 * The distinction the interface must not blur is the last one. A refusal is a state of
 * the world and it is published with its code. A timeout is a property of the platform
 * and it says so, and points at the shelf, which is the same measurement taken earlier
 * rather than a different kind of number.
 *
 * No dependency is added for any of this. The whole file is one fetch, one interval and
 * a discriminated union, because the alternative on a page whose job is provenance is a
 * 40 kB library to draw a spinner.
 */

import { useCallback, useEffect, useRef, useState } from "react";

/** The measurement payload, as `LiveMeasurement.to_dict` writes it. */
type Measurement = {
  observation?: {
    id?: number;
    norad_cat_id?: number;
    satellite?: string;
    station?: number;
    station_name?: string;
    start?: string;
    end?: string;
    status?: string;
    waterfall_status?: string;
    client_family?: string;
  };
  pass?: {
    rx_freq_hz?: number;
    max_elevation_deg?: number;
    tle_epoch_age_days?: number;
    duration_s?: number;
    doppler_swing_hz?: number;
  };
  axis?: { hz_per_px?: number; derivation?: string; reader?: string; confidence?: number };
  mode?: {
    verdict?: string;
    why?: string;
    sigma_curved?: number | null;
    sigma_vertical?: number | null;
    corridor_scored?: string | null;
  };
  measurement?: {
    offset_hz?: number | null;
    offset_ppm?: number | null;
    at_search_bound?: boolean | null;
    sigma?: number | null;
    fit?: { degraded?: string | null; detect_frac?: number | null } | null;
  };
  nulls?: {
    n?: number | null;
    p_value?: number | null;
    not_tested?: string | null;
    median?: number | null;
  };
  provenance?: {
    measured_at_utc?: string;
    waterfall_url?: string;
    waterfall_sha256?: string;
    waterfall_bytes?: number;
    tle_source?: string;
    tle1?: string;
    tle2?: string;
    observation_api?: string;
  };
};

type State =
  | { kind: "idle" }
  | { kind: "measuring"; obsId: number; since: number }
  | { kind: "measured"; obsId: number; source: "live" | "shelf"; data: Measurement }
  | { kind: "refused"; obsId: number | null; code: string; detail: string };

/**
 * Where to post. Same origin by default, which is what the deployed function is: the
 * console's own `/api/live`. An env var overrides it for a worker hosted elsewhere, and
 * the default means a fresh clone needs no configuration to work locally.
 */
const ENDPOINT = process.env.NEXT_PUBLIC_LIVE_API_URL || "/api/live";

const num = (v: number | null | undefined, digits = 2): string =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";

const int = (v: number | null | undefined): string =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v).toLocaleString("en-GB") : "—";

function shortSha(sha: string | undefined): string {
  if (!sha) return "—";
  return `${sha.slice(0, 10)}…${sha.slice(-6)}`;
}

function stamp(iso: string | undefined): string {
  if (!iso) return "—";
  // Fixed format rather than toLocaleString: the reader's locale deciding whether a
  // measurement happened on 08/21 or 21/08 is a provenance field that changes by
  // browser, and this one is quoted in a receipt.
  return `${iso.replace("T", " ").replace(/(\+00:00|Z)$/, "")} UTC`;
}

function verdictTone(verdict: string | undefined): string {
  if (verdict === "UNCORRECTED") return "live-verdict-uncorrected";
  if (verdict === "CORRECTED") return "live-verdict-corrected";
  return "live-verdict-unresolved";
}

export default function LiveConsole({
  shelf,
  builtAt,
  snapshotCutoff,
  nNulls,
  nDecisive,
}: {
  shelf: unknown[];
  builtAt: string;
  snapshotCutoff: string;
  nNulls: number;
  nDecisive: number;
}) {
  const entries = shelf as Measurement[];
  const [raw, setRaw] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (state.kind !== "measuring") {
      if (timer.current !== null) window.clearInterval(timer.current);
      timer.current = null;
      return;
    }
    timer.current = window.setInterval(() => {
      setElapsed(Math.round((Date.now() - state.since) / 1000));
    }, 250);
    return () => {
      if (timer.current !== null) window.clearInterval(timer.current);
    };
  }, [state]);

  const measure = useCallback(async (obsId: number) => {
    setElapsed(0);
    setState({ kind: "measuring", obsId, since: Date.now() });
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ obs_id: obsId }),
      });
      const body = (await response.json()) as {
        ok?: boolean;
        code?: string;
        detail?: string;
        message?: string;
        measurement?: Measurement;
      };
      if (response.ok && body.ok && body.measurement) {
        setState({ kind: "measured", obsId, source: "live", data: body.measurement });
        return;
      }
      setState({
        kind: "refused",
        obsId,
        code: body.code || `HTTP_${response.status}`,
        detail:
          body.detail ||
          body.message ||
          "The endpoint answered without a measurement and without a reason.",
      });
    } catch (error) {
      // A network failure and a cold start that ran out of time land here together, so
      // the copy names both rather than guessing which one happened.
      setState({
        kind: "refused",
        obsId,
        code: "ENDPOINT_UNREACHABLE",
        detail:
          "The measurement endpoint did not answer. One waterfall download plus a " +
          "corridor fit takes tens of seconds, so a cold start can exceed the " +
          "platform's function limit. The shelf below holds the same measurement " +
          "taken earlier, by the same function. " +
          (error instanceof Error ? error.message : String(error)),
      });
    }
  }, []);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = raw.trim();
    if (!/^[0-9]{1,9}$/.test(trimmed)) {
      setState({
        kind: "refused",
        obsId: null,
        code: "BAD_OBSERVATION_ID",
        detail:
          "An observation id is a positive integer, the number in a " +
          "network.satnogs.org/observations/<id>/ URL.",
      });
      return;
    }
    void measure(Number(trimmed));
  };

  const shown =
    state.kind === "measured" ? state.data : null;

  return (
    <>
      <section className="live-panel" aria-labelledby="live-form-heading">
        <h2 className="panel-heading" id="live-form-heading">
          Paste an observation id
        </h2>
        <form className="live-form" onSubmit={submit}>
          <label className="live-field">
            <span className="live-field-label">SatNOGS observation id</span>
            <input
              className="live-input mono"
              inputMode="numeric"
              autoComplete="off"
              spellCheck={false}
              placeholder="14829364"
              value={raw}
              onChange={(event) => setRaw(event.target.value)}
              aria-describedby="live-form-help"
            />
          </label>
          <button
            className="live-submit"
            type="submit"
            disabled={state.kind === "measuring"}
          >
            {state.kind === "measuring" ? `Measuring… ${elapsed}s` : "Measure now"}
          </button>
        </form>
        <p className="live-help" id="live-form-help">
          Any public id works, including one recorded minutes ago. Find one on{" "}
          <a href="https://network.satnogs.org/observations/" rel="noreferrer noopener">
            the SatNOGS observation list
          </a>
          . The endpoint downloads one image and fits one corridor, so expect tens of
          seconds, and it caches each id for a day so a second reader pays nothing.
        </p>
      </section>

      {state.kind === "measuring" ? (
        <section className="live-panel live-panel-working" aria-live="polite">
          <h2 className="panel-heading">
            Measuring observation <span className="mono">{state.obsId}</span>
          </h2>
          <ol className="live-steps">
            <li>Reading the observation record and its two-line elements</li>
            <li>Downloading the published waterfall and hashing it</li>
            <li>Propagating the pass and building the predicted Doppler curve</li>
            <li>Reading the frequency axis off the tick labels</li>
            <li>Scoring corrected against uncorrected, then fitting the offset</li>
            <li>Permuting the pass to build the null distribution</li>
          </ol>
          <p className="live-elapsed mono">{elapsed}s elapsed</p>
        </section>
      ) : null}

      {state.kind === "refused" ? (
        <section className="live-panel live-panel-refused" aria-live="polite">
          <h2 className="panel-heading">
            {state.obsId === null ? "Not an id" : `Refused: observation ${state.obsId}`}
          </h2>
          <p className="live-code mono">{state.code}</p>
          <p className="live-refusal-detail">{state.detail}</p>
        </section>
      ) : null}

      {shown ? <Measured data={shown} source={state.kind === "measured" ? state.source : "live"} /> : null}

      <section className="live-panel" aria-labelledby="live-shelf-heading">
        <h2 className="panel-heading" id="live-shelf-heading">
          Frozen shelf: {entries.length} passes recorded after the snapshot
        </h2>
        <p className="live-help">
          Measured with the same function at{" "}
          <span className="mono">{stamp(builtAt)}</span> and baked into this build, so a
          button answers with no network call. Every one of them started after{" "}
          <span className="mono">{stamp(snapshotCutoff)}</span>, which is when the corpus
          this project was built on stopped growing, so nothing here was available to any
          model in this repository. {nDecisive} of {entries.length} settled the Doppler
          convention; the rest are <span className="mono">UNRESOLVED</span>, which is what
          most of a real queue looks like. Null distributions are {nNulls} permutations.
        </p>
        <ul className="live-shelf">
          {entries.map((entry) => {
            const id = entry.observation?.id;
            const verdict = entry.mode?.verdict;
            return (
              <li key={id}>
                <button
                  type="button"
                  className="live-shelf-button"
                  onClick={() =>
                    setState({
                      kind: "measured",
                      obsId: Number(id),
                      source: "shelf",
                      data: entry,
                    })
                  }
                >
                  <span className="live-shelf-id mono">{id}</span>
                  <span className={`live-shelf-verdict ${verdictTone(verdict)}`}>
                    {verdict}
                  </span>
                  <span className="live-shelf-ppm mono">
                    {entry.measurement?.offset_ppm === null ||
                    entry.measurement?.offset_ppm === undefined
                      ? "no offset"
                      : `${num(entry.measurement.offset_ppm, 2)} ppm`}
                  </span>
                  <span className="live-shelf-when">
                    {entry.observation?.start?.replace("T", " ").replace("Z", "") ?? ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

function Measured({ data, source }: { data: Measurement; source: "live" | "shelf" }) {
  const mode = data.mode ?? {};
  const measurement = data.measurement ?? {};
  const nulls = data.nulls ?? {};
  const provenance = data.provenance ?? {};
  const observation = data.observation ?? {};
  const pass = data.pass ?? {};
  const degraded = measurement.fit?.degraded ?? null;

  return (
    <section className="live-panel live-panel-result" aria-live="polite">
      <header className="live-result-head">
        <div>
          <p className="eyebrow">
            {source === "live" ? "Measured just now" : "Measured earlier, frozen in this build"}
          </p>
          <h2 className="live-result-title">
            <span className="mono">{observation.id}</span>{" "}
            <span className="live-result-sat">{observation.satellite}</span>
          </h2>
          <p className="live-result-sub">
            station <span className="mono">{observation.station}</span>{" "}
            {observation.station_name ? `(${observation.station_name})` : null} · recorded{" "}
            <span className="mono">{observation.start?.replace("T", " ").replace("Z", "")}</span>{" "}
            to <span className="mono">{observation.end?.slice(11, 19)}</span> UTC · client{" "}
            <span className="mono">{observation.client_family ?? "unknown"}</span>
          </p>
        </div>
        <p className={`live-verdict ${verdictTone(mode.verdict)}`}>{mode.verdict}</p>
      </header>

      <p className="live-why">{mode.why}</p>

      <div className="live-stats">
        <Figure
          label="Offset"
          value={
            measurement.offset_ppm === null || measurement.offset_ppm === undefined
              ? "—"
              : num(measurement.offset_ppm, 2)
          }
          unit="ppm"
          note={
            measurement.offset_hz === null || measurement.offset_hz === undefined
              ? "no corridor was selected, so no offset was fitted"
              : `${int(measurement.offset_hz)} Hz from the catalogue centre`
          }
        />
        <Figure
          label="Null test"
          value={nulls.p_value === null || nulls.p_value === undefined ? "—" : num(nulls.p_value, 3)}
          unit="p"
          note={
            nulls.not_tested
              ? `not tested: ${nulls.not_tested}`
              : `${nulls.n ?? "—"} permutations of this pass`
          }
        />
        <Figure
          label="Peak elevation"
          value={num(pass.max_elevation_deg, 1)}
          unit="deg"
          note={`${int(pass.duration_s)} s recorded, ${int(pass.doppler_swing_hz)} Hz predicted swing`}
        />
        <Figure
          label="Elements"
          value={num(pass.tle_epoch_age_days, 2)}
          unit="days old"
          note={`${provenance.tle_source ?? "unknown source"}, at measurement time`}
        />
      </div>

      {degraded ? (
        <p className="live-degraded">
          The corridor fit reports <span className="mono">{degraded}</span>: the row-wise
          trace detector found{" "}
          <span className="mono">{num((measurement.fit?.detect_frac ?? 0) * 100, 1)}%</span>{" "}
          of rows. The mode verdict above is a separate measurement, scored on the whole
          image rather than row by row, which is why one can settle while the other does
          not.
        </p>
      ) : null}

      <div className="live-provenance">
        <h3 className="live-provenance-heading">Provenance</h3>
        <dl>
          <div>
            <dt>Measured at</dt>
            <dd className="mono">{stamp(provenance.measured_at_utc)}</dd>
          </div>
          <div>
            <dt>Waterfall sha256</dt>
            <dd className="mono" title={provenance.waterfall_sha256}>
              {shortSha(provenance.waterfall_sha256)}
            </dd>
          </div>
          <div>
            <dt>Image</dt>
            <dd>
              {provenance.waterfall_url ? (
                <a href={provenance.waterfall_url} rel="noreferrer noopener">
                  {int(provenance.waterfall_bytes)} bytes, as published
                </a>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div>
            <dt>Frequency axis</dt>
            <dd className="mono">
              {num(data.axis?.hz_per_px, 2)} Hz/px, {data.axis?.reader},{" "}
              {num((data.axis?.confidence ?? 0) * 100, 1)}% confidence
            </dd>
          </div>
          <div>
            <dt>Record</dt>
            <dd>
              {provenance.observation_api ? (
                <a href={provenance.observation_api} rel="noreferrer noopener">
                  the observation as the API returned it
                </a>
              ) : (
                "—"
              )}
            </dd>
          </div>
        </dl>
        <pre className="live-tle mono">
          {provenance.tle1}
          {"\n"}
          {provenance.tle2}
        </pre>
      </div>
    </section>
  );
}

function Figure({
  label,
  value,
  unit,
  note,
}: {
  label: string;
  value: string;
  unit: string;
  note: string;
}) {
  return (
    <div className="live-figure">
      <p className="live-figure-label">{label}</p>
      <p className="live-figure-value mono">
        {value}
        <span className="live-figure-unit">{unit}</span>
      </p>
      <p className="live-figure-note">{note}</p>
    </div>
  );
}
