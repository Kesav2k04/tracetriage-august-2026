# SatNOGS API reconnaissance (verified, read-only)

**Probed:** 2026-08-16, 14:47 to 14:52 IST, from `D:\` by Claude Opus 5.
**Method:** live unauthenticated GET requests against the public API. No writes, no account, no token.
**Why this file exists:** every fact below was measured, not recalled. Bob should treat it as ground truth and skip rediscovery. If a fact here contradicts what Bob observes, Bob's live observation wins and this file gets corrected.

---

## 1. Which host serves what

| Need | Host | Verified |
|---|---|---|
| Observations, waterfalls, stations | `https://network.satnogs.org/api/` | HTTP 200 |
| Transmitters, satellites, TLE sets | `https://db.satnogs.org/api/` | HTTP 200 |

`https://db.satnogs.org/api/observations/` returns **HTTP 404**. Observations do not live on the DB host. This one mistake costs an hour if discovered by trial.

Measured payload sizes on a first page:

- `network/api/observations/?format=json` → 200, 36,370 bytes, 25 records
- `db/api/transmitters/?format=json` → 200, 3,492,085 bytes
- `db/api/tle/?format=json` → 200, 523,847 bytes
- `network/api/stations/?format=json` → 200, 2,797,081 bytes

No API key was required for any of the above.

---

## 2. Observation record: the exact 47 fields

Confirmed present on live records:

```
archive_url, archived, center_frequency, client_metadata, client_version,
demoddata, end, ground_station, id, max_altitude, norad_cat_id,
observation_frequency, observer, payload, rise_azimuth, sat_id, set_azimuth,
start, station_alt, station_lat, station_lng, station_name, status,
tle0, tle1, tle2, tle_source, transmitter, transmitter_baud,
transmitter_description, transmitter_downlink_drift, transmitter_downlink_high,
transmitter_downlink_low, transmitter_invert, transmitter_mode,
transmitter_status, transmitter_type, transmitter_unconfirmed,
transmitter_updated, transmitter_uplink_drift, transmitter_uplink_high,
transmitter_uplink_low, transmitter_uuid, vetted_datetime, vetted_status,
vetted_user, waterfall, waterfall_status, waterfall_status_datetime,
waterfall_status_user
```

Every field the physics corridor needs is on the observation record itself. **No join is required** to compute geometry:

- Orbit: `tle0`, `tle1`, `tle2`, `tle_source` (the TLE actually used at schedule time, not today's TLE)
- Station: `station_lat`, `station_lng`, `station_alt`
- Timing: `start`, `end` (ISO 8601, `Z`)
- Frequency: `observation_frequency`, `transmitter_downlink_low`, `center_frequency`
- Geometry sanity: `rise_azimuth`, `set_azimuth`, `max_altitude`
- Split keys: `ground_station`, `transmitter_uuid`, `norad_cat_id`, `sat_id`

> **Assumption:** `tle1`/`tle2` are the TLE used for that pass. Field name and content are verified; the "used at schedule time" reading is inferred from `tle_source` being populated per observation. Bob should confirm before claiming epoch-accurate propagation.

---

## 3. `center_frequency` is null in practice. Use `client_metadata`.

**Measured:** `center_frequency` was `null` on **0/25 present** in the good-status sample, and null across every record inspected.

The receiver truth lives in `client_metadata`, a **JSON-encoded string** (parse it, it is not a nested object). Verified shape from observation 14786766:

```json
{
  "radio": {
    "name": "gr-satnogs",
    "version": "2.3.1.1",
    "parameters": {
      "soapy-rx-device": "driver=rtlsdr",
      "samp-rate-rx": "2.048e6",
      "rx-freq": "436990000",
      "doppler-correction-per-sec": null,
      "lo-offset": null,
      "ppm": null,
      "baudrate": "9600",
      "framing": "ax25"
    }
  },
  "latitude": 48.363,
  "longitude": 10.312,
  "elevation": 480,
  "frequency": 436990000
}
```

This gives the four things the corrected-corridor calculation actually needs:

| Quantity | Source | Note |
|---|---|---|
| Tuned RX frequency | `radio.parameters.rx-freq` | string, needs float cast |
| Sample rate → waterfall span | `radio.parameters.samp-rate-rx` | string in scientific notation, e.g. `"2.048e6"` |
| Client + version | `radio.name`, `radio.version` | drives per-format image parsing |
| LO offset / ppm | `lo-offset`, `ppm` | often null; treat null as zero only after checking |

`samp-rate-rx` is **not** the displayed waterfall bandwidth. The gr-satnogs waterfall is decimated before rendering. Bob must derive pixels-per-Hz empirically per client version rather than assuming full sample rate spans the image width.

---

## 4. Query filters: what works and what silently lies

Tested individually against `network/api/observations/`:

| Filter | Result |
|---|---|
| `status=good` | **works** |
| `vetted_status=good` | works (legacy alias for the same thing) |
| `ground_station=<id>` | **works** |
| `satellite__norad_cat_id=<id>` | **works** |
| `transmitter_mode=<mode>` | **works** |
| `end=<ISO8601>` | **works**, behaves as "ended on or before" |
| `start=<ISO8601>` | works, behaves as "starts on or after" (returns future passes) |
| `waterfall_status=with-signal` | **HTTP 400 Bad Request. Not a filter.** |
| `end__lte=<ISO8601>` | **silently ignored.** Returns unfiltered results with HTTP 200. |

Two traps here, both of which produce a green-looking wrong dataset:

1. `end__lte` is accepted, returns 200, and is **ignored**. Django-style `__lte` suffixes are not supported. Use bare `end=`.
2. `waterfall_status` cannot be filtered server-side. **Filter it client-side after fetching.** This drives the sampling budget in section 5.

**Default listing returns future observations.** A bare `?format=json` call returns records with `status: "future"`, `waterfall: null`, and `waterfall_status: "unknown"`. Any ingestion that forgets a date bound will download nothing but empty scheduled passes.

### Working recipe for mature labelled data

```
https://network.satnogs.org/api/observations/?format=json&end=<cutoff-ISO8601>
```

then page with the cursor from the `Link: <...>; rel="next"` response header, and filter `waterfall_status` locally.

---

## 5. Measured label and metadata coverage (n=600)

Sampled 24 cursor pages, `end=2026-07-15T00:00:00Z`, 600 consecutive observations, 0.4 s between requests. No throttling, no 429, no `Retry-After` header observed.

| Quantity | Measured | Rate |
|---|---|---|
| `waterfall` URL present | 554/600 | **92.3%** |
| `client_metadata` present | 564/600 | **94.0%** |
| `tle1` + `tle2` present | 600/600 | **100.0%** |
| Decisive `waterfall_status` (with-signal or without-signal) | 174/600 | **29.0%** |

`waterfall_status` distribution: `unknown` 426, `with-signal` 113, `without-signal` 61.
`status` distribution: `unknown` 292, `good` 186, `failed` 62, `bad` 60.

Entity diversity in the same 600 records: **211 unique stations, 197 unique transmitters, 179 unique NORAD IDs.**

### What this does to the kill gate

The kill gate asks for at least 2,000 mature waterfalls across at least 12 transmitters and 30 stations, with decisive positive, decisive negative and unknown examples present.

- Entity diversity: **passes with enormous margin.** 600 records already gave 197 transmitters and 211 stations, roughly 16x and 7x the floor. Grouped holdouts by station and transmitter are viable.
- Volume: fetching ~2,170 records yields ~2,000 with waterfalls at the measured 92.3% rate. That is **~87 cursor pages**, about 3 minutes of polite paging.
- Decisive labels: at 29.0%, a 2,000-waterfall snapshot yields roughly **580 decisive** (about 380 positive, 200 negative) and about 1,420 unknown.

> **The binding constraint is decisive negatives, not volume.** `without-signal` ran at 10.2% (61/600). A 2,000-record snapshot gives roughly 200 decisive negatives. If Bob wants a balanced decisive set of 1,000 per class, the snapshot must grow to roughly 10,000 observations, which is ~17 GB of waterfall PNG at the sizes in section 6. Decide the target decisive-negative count **before** starting the download, not after.

Class imbalance is measured at roughly **1.85 : 1 positive to negative** among decisive labels. Report it; do not silently rebalance.

---

## 6. Waterfall artifacts

Three downloaded and opened successfully:

| Observation | `waterfall_status` | `client_version` | Bytes | Format | Size |
|---|---|---|---|---|---|
| 14513023 | with-signal | 1.6 | 1,911,499 | PNG RGBA | **836 x 1603** |
| 14519869 | with-signal | 2.1.2 | 1,716,877 | PNG RGBA | **832 x 1603** |
| 14513923 | with-signal | 2.1.2+1.gcded8f6.dirty | 1,717,793 | PNG RGBA | **832 x 1603** |

Findings that matter:

- **Width varies with client version.** 836 px on client 1.6 versus 832 px on client 2.1.2. Width is the frequency axis. A hardcoded pixels-per-Hz constant will misplace the corridor on a subset of the corpus and the error will be invisible to the eye. Derive the mapping **per client version** and test it on both widths.
- Height was constant at 1603 in this sample, but height is the time axis and must scale with pass duration. Do not assume 1603.
- Images are **RGBA PNG**, not RGB. `Image.open(...).convert("RGB")` before any array work, or the alpha channel silently becomes a fourth feature plane.
- Mean size ~1.7 MB. **2,000 waterfalls ≈ 3.4 GB. 10,000 ≈ 17 GB.** Disk `D:\` had 104 GB free at setup time. Budget it.
- Artifacts are served from `https://s3.eu-central-1.wasabisys.com/satnogs-network/data_obs/<Y>/<M>/<D>/<H>/<obs_id>/waterfall_<obs_id>_<timestamp>.png`, not from the API host. The download path is a separate failure domain from the metadata path and needs its own retry and its own failure state.

### Client version spread (n=600)

`1.8.1` 152, `2.1.2` 134, `2.1.1` 66, `1.9.3` 64, empty string 36, `1.9.3+5.g4ee...` 30, plus a long tail including `1.6` and `.dirty` suffixes.

At least **six** distinct client families appear in any realistic snapshot, and 6% of records have **no client version at all**. The plan's "unsupported client format" failure state is not hypothetical, it is guaranteed to fire. Version strings are not clean semver: they carry `+N.g<sha>` and `.dirty` suffixes and must be normalised before use as a grouping key.

---

## 7. The pixel-to-frequency mapping. Read the axis, never the sample rate.

**This is the single most expensive mistake available in this project, and it is measured below rather than assumed.**

The waterfall PNG does **not** span `samp-rate-rx`. It spans a decimated band, and the rendered matplotlib axis states which one. Measured by locating tick marks under the plot and reading the rendered labels on the images themselves:

| Observation | Client | Image | Plot box x | Tick spacing | **Hz per pixel** | Axis span read off image |
|---|---|---|---|---|---|---|
| 14513023 | `v2.3-compat-xxx-v2.3.4.0` | 836 x 1603 | 66..686 (621 px) | 81.0 px = 10 kHz | **123.46** | -30..+30 kHz labelled, ~±35 kHz edge |
| 14513923 | `2.1.2+1.gcded8f6.dirty` | 832 x 1603 | 74..677 (604 px) | 125.0 px = 10 kHz | **80.00** | -20..+20 kHz labelled, ~±24 kHz edge |
| 14519869 | `2.1.2` | 832 x 1603 | 74..677 (604 px) | 125.0 px = 10 kHz | **80.00** | -20..+20 kHz labelled |

Tick labels were confirmed by eye on both distinct layouts, not inferred from spacing.

### Why this decides the project

For observation 14513023 the physics probe computed a Doppler swing of **14,631 Hz** across the pass, on a sample rate of 2,500,000 Hz.

- If the image is assumed to span `samp-rate-rx`: 14,631 Hz maps to about **5 pixels** of a 621 px plot. The corridor is a vertical line, the physics looks worthless, and the kill gate **fails for a reason that is entirely an artifact of the wrong constant.**
- Using the measured 123.46 Hz/px: 14,631 Hz maps to about **118 pixels**, roughly 19% of the plot width. A clearly visible S-curve with real discriminative power.

The displayed band is about 76.7 kHz against a 2.5 MHz sample rate, a decimation factor near 32.6. **Nothing in the API tells you that factor.** It must come off the axis.

### Consequences Bob must build around

1. **Hz/px varies by 54% between two real observations in a three-image sample.** It is not a constant, not per-project, and not derivable from `samp-rate-rx`. Derive it per observation.
2. **The plot box is not the image box.** Plot area is x=66..686 on one client and x=74..677 on another, and the 836 px client renders an extra colorbar at x=724..755 that a naive "non-white columns" crop will swallow. Crop to the measured plot box before any model sees the image, or the network trains on axis text and a colorbar.
3. **Image width is a proxy for client family, not a reliable one.** 836 px and 832 px appeared here; the population has at least six client families (section 6). Key the mapping on the measured axis, and use the client version only as a sanity check.
4. Time axis height was 1603 px in all three samples but must scale with pass duration. Do not hardcode it.

A reusable measurement routine lives at `scripts/recon/measure_axis.py`. It is recon, not production: Bob should write the production version with tests over both layouts above as fixtures.

---

## 8. Doppler correction: what is and is not established

**Established:** `doppler-correction-per-sec` exists inside `client_metadata.radio.parameters` and was `null` on every record inspected, while `rigctl-port` was populated (`"4532"`) on the same records.

**Established by computation:** on observation 14513023 the stored TLE plus station coordinates reproduced the pass geometry to **0.18 degrees** of the API's own reported `max_altitude` (computed 31.18 deg, API 31.0 deg). The orbital chain is sound. See section 10.

**Not established, and Bob must verify before any physics claim:**

1. Whether a null `doppler-correction-per-sec` means correction was off, or means correction was applied by `rigctl` outside the flowgraph. The populated `rigctl-port` points to external rig control, which would mean the waterfall **is** corrected and the residual, not the raw S-curve, is the signal to model. This is the load-bearing assumption of the entire physics story.
2. Whether the waterfall time axis starts at `start` or at first-sample time, and the size of that offset.
3. Whether the corridor centre sits at axis zero or is offset by `lo-offset` / `ppm` when those are non-null.

The master plan is explicit that drawing a raw S-curve over an already-corrected waterfall is false evidence. Item 1 decides which curve is correct. **Test it against known-good passes before building anything on top of it.**

---

## 9. Licensing and politeness

- SatNOGS observation data and waterfalls are published under **CC BY-SA 4.0**. Attribution, source URL, retrieval timestamp, modification notice and a licence link are required on anything redistributed. Store these per record at snapshot time; they cannot be reconstructed later.
- No rate limit header was returned and no request was throttled at 0.4 s spacing across 24 consecutive pages. Absence of a limit header is **not** a licence to hammer the endpoint. Keep the delay, send a real `User-Agent` with a contact address, and cache every raw response so a re-run never re-fetches.
- `User-Agent` used for this recon: `TraceTriage-recon/0.1 (kesavk659@gmail.com)`.

---

## 10. Physics feasibility result (measured end to end)

`scripts/recon/physics_feasibility.py` was run against live observation **14513023** (NORAD 63237, station 91 at 50.77, -2.02, 60 m, pass of 207 s on 2026-07-14).

```
computed peak elevation   +31.18 deg
API max_altitude           31.0  deg
agreement error            0.18  deg          -> PASS

doppler swing             -7,284 Hz .. +7,347 Hz   (total 14,631 Hz)
                          = 0.59% of the 2.5 MHz sample rate
                          = ~118 px at the measured 123.46 Hz/px  -> visible
range at closest approach  841.6 km
range rate at TCA          -0.05 km/s (sign flip confirms the geometry)
```

The elevation profile is symmetric about the midpoint and the range-rate sign flips exactly at peak elevation, which is what a correct pass geometry looks like.

**What this proves:** an observation's own stored `tle1`/`tle2`, `station_lat`/`lng`/`alt` and `start`/`end` are sufficient to reproduce the pass to sub-degree accuracy, with no external TLE lookup and no join. The corridor computation the plan depends on is viable.

**What this does not prove:** that the waterfall image is Doppler-corrected, or where on the image the corridor lands. Those need section 8 item 1 resolved and section 7's mapping applied. Geometry being right is necessary, not sufficient.

The probe uses a first-order GMST rotation adequate for a feasibility check. The production module should use a proper ECI-to-ECEF transform with polar motion ignored but nutation handled, and be tested against the API's own `max_altitude`, `rise_azimuth` and `set_azimuth` on a few hundred observations rather than one.

---

## 11. Reproducing this recon

Probe scripts are preserved at `scripts/recon/`. They are read-only and safe to re-run:

```bash
.venv/Scripts/python.exe scripts/recon/probe_filters.py       # section 4
.venv/Scripts/python.exe scripts/recon/survey_coverage.py     # section 5
.venv/Scripts/python.exe scripts/recon/fetch_waterfalls.py    # section 6
.venv/Scripts/python.exe scripts/recon/measure_axis.py        # section 7
.venv/Scripts/python.exe scripts/recon/physics_feasibility.py # section 10
```

Re-running against a different date window will produce different rates. The section 5 numbers are a single-window measurement, not a population constant. Any public claim must cite the frozen snapshot, not this file.

**None of these scripts belong in `pipeline/`.** They are throwaway evidence that the plan is buildable. Bob writes the production versions with tests.
