# Independent review: flight dynamics and observational science

Scope was the physics and the science: `pipeline/tracetriage/physics.py` in full,
`artifacts/PHYSICS_VALIDATION.json` and `scripts/validate_physics.py`, kill gates 1 to 4 in
`docs/KILL_GATE.md`, the statistical treatment in `scripts/run_fusion.py` and
`scripts/run_queue.py` with the receipts they wrote, and the sky and ground plot conventions
in `apps/web/components/SkyPlot.tsx`, `apps/web/components/GroundTrack.tsx` and
`apps/web/lib/projection.ts`. Reviewed at commit `7fbb980`.

This was not a reading exercise. Using `.venv/Scripts/python.exe`, the cached API pages under
`.a3_cache/a4_validation_pages/` and the snapshot at `D:/tracetriage_data/snap-stage1`, I
re-ran the whole 200-observation geometry validation twice (once as shipped, once with the
elevation reference deliberately broken), ran the azimuth validation the project never ran,
ran the gate-3 null calibration with the frequency axis inverted and with time reversed,
fault-injected `corridor_for_obs` with four kinds of damaged TLE, recomputed the GMST
expression against the full IAU-1982 series, computed the ionospheric, tropospheric and
relativistic Doppler terms, measured the Doppler slope to price a stale TLE, and reproduced
the horizon-circle framing on every one of the 25 shipped observation cards. Every number
below came out of one of those runs. Where I did not execute something, it is in
"Limits of this review" rather than asserted.

Counts: 5 BLOCKING, 9 SERIOUS, 11 MINOR.

> **What happened to these findings.** This is an adversarial pre-ship review. It was
> commissioned to find defects, so every line below is something that was wrong at the
> commit named above, not something that is wrong now. The work that answers them runs
> in `docs/OPERATOR_BUILD_LOG.md` from Wave D (2026-08-19) onward, under the identifiers the
> log assigns. This file is the list of what was found; the build log is what was done
> about it.

---

## Findings

### [BLOCKING] A TLE whose epoch cannot be parsed returns a confident corridor wrong by eight half-widths

- **Where**: `pipeline/tracetriage/physics.py:626-639` (the staleness gate),
  `pipeline/tracetriage/physics.py:276-291` (`tle_epoch_datetime`).

- **What is wrong**: the staleness check is guarded by `if tle_epoch is not None:`, and
  `tle_epoch_datetime` catches every exception and returns `None`. When the epoch field is
  unreadable, no staleness check runs, `tle_epoch_age_days` stays `None`, control falls
  through to propagation, and `corridor_for_obs` returns `degraded=None`, which every caller
  reads as success. The module's stated contract at `physics.py:48-56` promises a named reason
  code for every degrade state. This is the one path that returns a wrong answer instead of a
  code, and "the epoch could not be parsed" is reported with the same `None` that means "no
  epoch age was computed".

- **How I know**: I took observation 14740031 out of the snapshot, replaced only the two
  epoch-year characters of `tle1` with `XX`, and called `corridor_for_obs`.

  | | as stored | epoch unreadable |
  |---|---|---|
  | `degraded` | `None` | `None` |
  | `tle_epoch_age_days` | 0.479 | `None` |
  | Doppler swing | 17,290 Hz | 1,500 Hz |
  | max elevation | 41.22 deg | 2.54 deg |
  | samples returned | 512 | 512 |
  | max absolute difference between the two corridors | | **16,477 Hz** |

  `UNCORRECTED_CORRIDOR_HZ` is 2,000, so the returned corridor is displaced by 8.2 half-widths
  and reported clean. The underlying parser accepted the line and propagated from a garbage
  epoch. A second injection (epoch replaced by `ZZZZZ.ZZZZZZZZ`) also returned
  `degraded=None`. Two other injections behaved correctly: swapped TLE lines and a truncated
  line 2 both returned `SGP4_ERROR`.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json,glob,numpy as np;from pipeline.tracetriage.physics import corridor_for_obs,tle_epoch_datetime;
  raw=[r for p in sorted(glob.glob('D:/tracetriage_data/snap-stage1/pages/*.json')) for r in json.load(open(p)) if r.get('id')==14740031][0];
  t=corridor_for_obs(raw);bad=dict(raw);bad['tle1']=raw['tle1'][:18]+'XX'+raw['tle1'][20:];b=corridor_for_obs(bad);
  print('epoch parse:',tle_epoch_datetime(bad['tle1']));print('degraded:',b.degraded,'age:',b.tle_epoch_age_days);
  a=np.array(t.uncorrected.doppler_hz);c=np.array(b.uncorrected.doppler_hz);
  print('swings',np.ptp(a),np.ptp(c));print('max diff Hz',abs(a-c).max());print('max el',t.uncorrected.max_elevation_deg,b.uncorrected.max_elevation_deg)"
  ```

- **Suggested fix**: add a named code, `UNPARSEABLE_TLE_EPOCH`, and return it when
  `tle_epoch_datetime` yields `None`. A TLE whose epoch cannot be read is not a TLE whose age
  is unknown; it is a TLE that should not be propagated.

---

### [BLOCKING] SGP4 error codes are computed, returned, bound to a name, and never read

- **Where**: `pipeline/tracetriage/physics.py:643-649`, and
  `pipeline/tracetriage/physics.py:731-742` for the consequence.

- **What is wrong**:

  ```python
  fracs, dops, els, errs = propagate_pass(...)
  if not fracs:
      return _fail("SGP4_ERROR")
  ```

  `errs` is never referenced again and `PhysicsResult` has no field for it. A propagation in
  which 400 of 512 samples returned a non-zero SGP4 error and 112 succeeded is reported as
  `degraded=None` with nothing to indicate that four fifths of the pass is missing. The
  consequence is not neutral: `corridor_columns` resolves the gap with `np.interp`, which
  clamps outside the sample range, so if propagation fails across the first 30 percent of the
  pass every row there receives the first surviving Doppler value and the corridor is drawn as
  a flat vertical segment where the physics produced nothing. This is the same shape of defect
  the project has already fixed twice by its own account, `offset_at_bound` being computed and
  consulted nowhere at `corridor_fit.py:643-646`.

- **How I know**: read the assignment and grepped the rest of the function and the dataclass
  for `errs`; there is no second reference and no field. `scripts/build_console_data.py` does
  surface the count for the console (`n_sgp4_errors`, `n_samples_propagated`, both present on
  all 25 shipped cards and both zero), which shows the value is available and that the
  production entry point simply drops it. The `np.interp` clamping behaviour is documented
  numpy semantics, visible directly at `physics.py:734-738`.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  grep -n "errs" pipeline/tracetriage/physics.py
  .venv/Scripts/python.exe -c "from pipeline.tracetriage.physics import PhysicsResult;print(PhysicsResult.__dataclass_fields__.keys())"
  .venv/Scripts/python.exe -c "import json;from pathlib import Path;
  print([(c['obs_id'],c['geometry']['n_sgp4_errors'],c['geometry']['n_samples_propagated']) for c in json.loads(Path('apps/web/public/data/cards.json').read_text(encoding='utf-8'))['cards']][:5])"
  ```

- **Suggested fix**: put `n_sgp4_errors` and `n_samples_propagated` on `PhysicsResult`, and
  degrade above a stated missing-sample fraction. A corridor built on 22 percent of a pass is
  a different object from one built on all of it, and the caller cannot currently tell them
  apart.

---

### [BLOCKING] Gate 3 is marked PASSED against a 70 percent threshold on three trials, where the data cannot establish 70 percent

- **Where**: `docs/KILL_GATE.md`, gate 3 status row and the gate 3 section heading
  ("PASSED on 3 testable observations").

- **What is wrong**: the threshold is "the expected corridor intersects a visible target-like
  trace in at least 70% of reviewed positive examples", and the verdict is PASSED on 3
  successes in 3 trials. Three trials cannot resolve a 70 percent rate. The achievable
  outcomes are 0, 33.3, 66.7 and 100 percent, so the measurement can only land far below the
  threshold or far above it, and the exact confidence bound is well below the bar.

  The document caveats the scope limit (only uncorrected captures are testable, 4 of 7
  excluded) and the non-independence (2 stations, 1 UTC night, a 22-minute window, two
  observations sharing one receiver and therefore one systematic offset) at length and
  honestly. Those caveats address which population the rate generalises to. Neither addresses
  whether the rate was measured at all.

- **How I know**: the exact one-sided Clopper-Pearson lower bound for `k = n` successes at
  confidence `1 - alpha` is `alpha ** (1/n)`. For 3 of 3 at 95 percent that is
  `0.05 ** (1/3) = 0.3684`. The observed data are consistent with a true intersection rate of
  36.8 percent, roughly half the threshold. Counting the two independent (station, date)
  groups the document itself identifies, the bound is `0.05 ** (1/2) = 0.2236`.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "print('n=3 lower bound',0.05**(1/3));print('n=2 lower bound',0.05**(1/2))"
  ```

  Cross-check with an exact binomial test if preferred: under a true rate of 0.70,
  `P(3 of 3) = 0.343`, so 3 of 3 does not reject any rate at or above 0.368.

- **Suggested fix**: keep the per-observation verdicts, which are strong and well controlled
  (each observation beats 200 nulls and all four scaled-swing controls). Change the
  cross-observation rate to NOT ESTABLISHED and print the 0.368 bound beside it. Gates 5 and 6
  already read NOT ESTABLISHED on far larger samples for the same reason, so the current
  PASSED is internally inconsistent with the register the rest of the board uses.

---

### [BLOCKING] The published gate-3 significance statistic is earned by a corridor with the frequency axis inverted

- **Where**: `docs/KILL_GATE.md`, the gate 3 results table (columns `sigma`, `200-null max`,
  `nulls >= true`, `p`), and the `discriminates` criterion at
  `pipeline/tracetriage/corridor_fit.py:658-662`.

- **What is wrong**: the gate leads with `0 of 200` and `p = 0.005`. A physically inverted
  corridor reaches the same p-value. The permutation null is so weak that clearing it carries
  almost no information, because scrambled paths collapse into noise around sigma 0.40 to 0.57
  and anything smooth beats them. `discriminates` is built from `p_value`, `beats_scaled` and
  `at_bound`; `margin_over_best_null`, which does separate truth from the inversion by a factor
  of 66, is computed and reported and is not part of the criterion.

- **How I know**: I ran `calibrate_against_nulls` on the three uncorrected observations with
  the corridor's `doppler_hz` negated, which is exactly `AXIS_SIGN_CONVENTION` inverted with
  the offset refitted, using the shipped thresholds and the real waterfalls.

  | obs | true sigma | inverted sigma | inverted `n_at_least` | inverted p | true margin | inverted margin |
  |---|---|---|---|---|---|---|
  | 14740031 | 2.024 | 0.590 | 0 of 200 | **0.00498** | 1.453 | 0.022 |
  | 14745664 | 1.539 | 0.398 | 9 of 200 | 0.0498 | 1.129 | -0.010 |
  | 14745929 | 1.652 | 0.411 | 0 of 200 | **0.00498** | 1.250 | 0.010 |

  The inverted corridor clears `p_value_max = 0.05` on all three and matches the published
  p-value exactly on two. What stops it is `beats_scaled_swing`, which is `False` for every
  inverted corridor because a rescaled version of the wrong curve outscores it.

- **How to reproduce**: build the corridor, negate it, and score both. The load and geometry
  calls are the same ones `scripts/run_gate3.py` makes; note `parse_waterfall` takes
  `observation_id`, not `obs_id`.

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "
  import json,glob,numpy as np
  from dataclasses import replace
  from PIL import Image
  from pathlib import Path
  from pipeline.tracetriage.corridor_fit import DEFAULT_THRESHOLDS,normalised_rows,calibrate_against_nulls
  from pipeline.tracetriage.physics import corridor_for_obs,rx_freq_of
  from pipeline.tracetriage.waterfall import parse_waterfall
  for oid in (14740031,14745664,14745929):
      raw=[r for p in sorted(glob.glob('D:/tracetriage_data/snap-stage1/pages/*.json')) for r in json.load(open(p)) if r.get('id')==oid][0]
      ph=corridor_for_obs(raw);rx=rx_freq_of(raw)
      img=Path(f'D:/tracetriage_data/snap-stage1/waterfalls/waterfall_{oid}.png')
      g=parse_waterfall(img,observation_id=oid,rx_freq_hz=rx,pass_duration_s=ph.pass_duration_s)
      with Image.open(img) as im: rgb=np.asarray(im.convert('RGB'))
      zs=normalised_rows(rgb,g.crop_box);C=ph.uncorrected;d=np.asarray(C.doppler_hz,float)
      for nm,cor in (('true',C),('inverted',replace(C,doppler_hz=list(-d)))):
          c=calibrate_against_nulls(zs,cor,g.hz_per_px,g.centre_px,rx,DEFAULT_THRESHOLDS)
          print(oid,nm,'sigma %.3f p %.5f n_at_least %s margin %.3f beats_scaled %s'%(c.true_sigma,c.p_value,c.n_at_least,c.margin_over_best_null,c.beats_scaled_swing))"
  ```

- **Suggested fix**: lead the gate-3 table with `margin_over_best_null` and the scaled-swing
  row, and state that the permutation p-value is a necessary and very weak condition. Add
  `margin_over_best_null` to the `discriminates` criterion with a floor fixed before the next
  scoring run. As published, a reader who takes "0 of 200, p = 0.005" as the evidence has taken
  the one number a wrong-sign corridor also earns.

---

### [BLOCKING] The stated reason for omitting the time-reversal control is measurably false, and it is the control that tests the axis sign

- **Where**: `pipeline/tracetriage/corridor_fit.py:44-50`, and the matching paragraph in
  `docs/KILL_GATE.md` under gate 3's control discussion.

- **What is wrong**: the module says

  > Time reversal is deliberately **not** used as a control. A3 established that a Doppler
  > curve is near odd-symmetric about closest approach, so reversing time and flipping the
  > frequency sign are errors that cancel and score well. A reversed curve is a weak null for
  > exactly the reason A3 documented.

  The premise is right and the conclusion inverts it. If `D` is odd about closest approach then
  `D(1-f) = -D(f)`, so time reversal *is* the sign flip. The two errors cancel when applied
  together, which is precisely why a visual check cannot find them. Applied singly, each
  produces a maximally wrong curve. The paragraph conflates "the pair cancels" with "each one
  alone still fits", and the second reading is the operative one, because it is the stated
  ground for dropping the control.

- **How I know**: I verified the premise and then ran the excluded control. The curves are odd
  symmetric to 0.1, 1.3 and 1.6 percent of swing, measured as
  `max |D(f) + D(1-f)|` over the sample series against the swing, so the premise holds. The
  reversal scores:

  | obs | true sigma | time-reversed sigma | scrambled-null maximum |
  |---|---|---|---|
  | 14740031 | 2.024 | **0.585** | 0.571 |
  | 14745664 | 1.539 | **0.397** | 0.410 |
  | 14745929 | 1.652 | **0.413** | 0.402 |

  Time reversal is not a weak null. It is the strongest null available, landing at or below the
  maximum of 200 scrambled corridors on all three observations. Dropping it removed the single
  control that most directly tests the axis sign convention.

- **How to reproduce**: same command as the previous finding, with
  `('reversed', replace(C, doppler_hz=list(d[::-1])))` added to the variant tuple. For the
  symmetry check, add
  `print('odd-symmetry residual', abs(d[:len(d)//2] + d[::-1][:len(d)//2]).max(), 'of swing', np.ptp(d))`.

- **Suggested fix**: restore the reversal control and correct the paragraph in both files. It
  costs one call and it strengthens the gate, because it is the one null that an "any smooth
  bright path wins" objection cannot explain away. Leaving the wrong statement in place is the
  worse outcome, since the fix improves the published result.

---

### [SERIOUS] The physics validation's reference is quantised to one degree, and the code's docstring claims a detectability that does not hold

- **Where**: `artifacts/PHYSICS_VALIDATION.json` (the `distribution` block),
  `scripts/validate_physics.py:validate`, and `pipeline/tracetriage/physics.py:216-218`.

- **What is wrong**: the validation compares SGP4 max elevation against the API's
  `max_altitude` on 200 observations and reports a mean absolute error of 0.243 degrees as
  evidence of agreement. Every one of the 200 reference values is an exact integer, so the
  reference carries one-degree quantisation and the reported distribution is the rounding, not
  the physics. Separately, `geodetic_normal`'s docstring asserts that the geocentric-reference
  error was "invisible in the mean error against the reported elevation and visible in the
  variance". The first half is right. The second half is not.

- **How I know**: three measurements.

  First, the quantisation. Checked against the raw cached API bytes, not the artifact: all 200
  `max_altitude` values are exact integers. A uniform rounding error on `[-0.5, 0.5]` has mean
  absolute value 0.250 and standard deviation 0.289. The artifact reports mean absolute 0.2429,
  median 0.2249, p95 0.4686, p99 0.5276, and a signed standard deviation of 0.362. Excluding
  one 3.44 degree outlier, all 200 residuals lie inside plus or minus 0.577.

  Second, the detectability claim, which is the build log's and which I confirm. I re-ran the
  entire validation with the station position vector substituted for the geodetic normal, which
  is the exact defect unit C7 fixed:

  | up reference | mean signed error | sd | mean absolute | median absolute | p95 absolute | within 1 deg |
  |---|---|---|---|---|---|---|
  | geodetic normal (shipped) | +0.0035 | 0.3632 | 0.2437 | 0.2258 | 0.4685 | 99.50% |
  | position vector (the defect) | -0.0329 | 0.3696 | 0.2495 | 0.2100 | 0.5220 | 99.50% |

  The mean moves by 0.0364 degrees against a standard error of 0.0261, which is 1.4 sigma, and
  the mean absolute error moves by 0.0058 degrees. The check could not have found it. The
  per-observation difference is signed as the docstring says, ranging from -0.1915 to +0.1691
  with a mean of +0.0364, which is the cancellation mechanism and it is correct.

  Third, the part that is wrong. The standard deviation moves from 0.3632 to 0.3696, a variance
  ratio of 1.035 against an F critical value near 1.28 at df 199 and 199. The defect is not
  visible in the variance either.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json,glob;
  v=[r['max_altitude'] for p in sorted(glob.glob('.a3_cache/a4_validation_pages/*/page_*.json')) if 'headers' not in p for r in json.load(open(p)) if r.get('max_altitude') is not None];
  print('n',len(v),'non-integer',[x for x in v if abs(x-round(x))>1e-9])"
  ```

  For the A/B, propagate each cached record twice with
  `site_up = geodetic_normal(lat, lon)` and with `site_up = station_ecef(...) / norm`, take
  `max(elevations_deg)` from each, and difference against `max_altitude`.

- **Suggested fix**: state in the artifact that the reference is integer-quantised and that the
  validation therefore bounds errors at roughly half a degree and cannot resolve anything
  finer. Correct the `geodetic_normal` docstring to say the check could not see the defect at
  all, in the mean or the variance, which is the finding and a sharper one. Add the third
  measurement below, which is the one that would have caught it.

---

### [SERIOUS] The API supplies two unrounded geometry fields, the project's own recon required validating against them, and it was never done

- **Where**: `scripts/validate_physics.py` (validates `max_altitude` only),
  against `docs/SATNOGS_API_RECON.md:272`, and against the unit's own task prompt,
  which is a working document this repository does not publish.

- **What is wrong**: the recon document states the production module should "be tested against
  the API's own `max_altitude`, `rise_azimuth` and `set_azimuth` on a few hundred observations
  rather than one", and the task prompt repeats it. Only `max_altitude` was validated, and it
  is the one field of the three that is destroyed by rounding. `rise_azimuth` and `set_azimuth`
  are the only independent check available on the azimuth convention and the local
  East/North/Up basis, and `pass_geometry` currently ships with neither validated.

- **How I know**: `rise_azimuth` and `set_azimuth` are present on **200 of 200** cached
  records. I ran the missing validation, comparing `pass_geometry` azimuth at fracs 0 and 1
  against the two API fields on the same 200 records:

  | | mean | sd | median absolute | p95 absolute | max absolute | within 1 deg | within 3 deg |
  |---|---|---|---|---|---|---|---|
  | rise azimuth | -0.007 | 0.321 | 0.268 | 0.479 | 1.962 | 99.5% | 100% |
  | set azimuth | -0.030 | 0.306 | 0.265 | 0.487 | 1.142 | 99.5% | 100% |

  Counterfactuals for scale: swapping the `atan2` arguments gives a median absolute error of
  93.9 degrees, and mirroring the azimuth gives 27.0 degrees. The convention is confirmed
  decisively, which makes this a pass that is missing from the receipt rather than a defect in
  the code.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "
  import json,glob,numpy as np
  from datetime import datetime
  from pipeline.tracetriage import physics as P
  d=lambda a,b:(a-b+180.0)%360.0-180.0
  dr=[];ds=[]
  for p in sorted(glob.glob('.a3_cache/a4_validation_pages/*/page_*.json')):
      if 'headers' in p: continue
      for r in json.load(open(p)):
          if not (r.get('tle1') and r.get('tle2') and r.get('rise_azimuth') is not None): continue
          lat=float(r['station_lat']);lon=float(r['station_lng']);alt=float(r['station_alt'])
          st=datetime.fromisoformat(r['start'].replace('Z','+00:00'));en=datetime.fromisoformat(r['end'].replace('Z','+00:00'))
          g=P.pass_geometry(r['tle1'],r['tle2'],st,en,P.station_ecef(lat,lon,alt),P.geodetic_normal(lat,lon),n_samples=256)
          if not g.fracs: continue
          dr.append(d(g.azimuth_deg[0],r['rise_azimuth']));ds.append(d(g.azimuth_deg[-1],r['set_azimuth']))
  for nm,a in (('rise',np.array(dr)),('set',np.array(ds))):
      print(nm,'n %d mean %+.3f sd %.3f medabs %.3f maxabs %.3f within3 %.1f%%'%(len(a),a.mean(),a.std(ddof=1),np.median(abs(a)),abs(a).max(),100*np.mean(abs(a)<=3)))"
  ```

- **Suggested fix**: add the azimuth comparison to `scripts/validate_physics.py` and write both
  distributions into `artifacts/PHYSICS_VALIDATION.json`. It is a free, unrounded, independent
  confirmation of the one convention the project currently asserts without evidence, and it
  passes.

---

### [SERIOUS] `TLE_MAX_EPOCH_AGE_DAYS = 14.0` is the only constant in the file with no derivation, and it is never exercised

- **Where**: `pipeline/tracetriage/physics.py:127-128`.

- **What is wrong**: the comment says what the constant does and not why it is 14. Every other
  constant in the file carries a measured rationale: `CORRECTED_CORRIDOR_HZ` cites the four
  measured carrier wanders (77, 639, 639 and 1935 Hz), `UNCORRECTED_CORRIDOR_HZ` cites the
  123 Hz p95 residual over 39 rows, `FREQ_OFFSET_SEARCH_HZ` cites the three measured offsets,
  `MAD_FLOOR` cites the grey-level gap. Fourteen days is not tied to the corridor width it is
  supposed to protect, and it has never been near its own boundary on real data.

- **How I know**: two measurements.

  The price of staleness. Measured peak Doppler slope on obs 14740031 is **119.4 Hz/s** over a
  241 s pass with a 17,290 Hz swing, taken as `max |dDoppler/dt|` on the propagated series:

  | along-track timing error | corridor displacement | in 2,000 Hz half-widths |
  |---|---|---|
  | 1 s | 119 Hz | 0.06 |
  | 5 s | 597 Hz | 0.30 |
  | 10 s | 1,194 Hz | 0.60 |
  | 30 s | 3,583 Hz | 1.79 |

  At an ordinary LEO along-track growth of 1 to 3 km/day and 7.5 km/s, 14 days is 1.9 to 5.6
  seconds, so 0.1 to 0.3 half-widths, which is tolerable. A 400 km object during a geomagnetic
  storm drifts an order of magnitude faster, at which point 14 days exceeds the half-width and
  the corridor is drawn where the trace is not, with `degraded=None`.

  The constant is inert. Across the 200 validation records the maximum epoch age is **3.837
  days**, the median is 0.743, 26 of 199 exceed one day, and exactly one record in the entire
  sample tripped `STALE_TLE`.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json,statistics;
  o=json.load(open('artifacts/PHYSICS_VALIDATION.json'))['observations'];
  a=[x['tle_epoch_age_days'] for x in o if x.get('tle_epoch_age_days') is not None];
  print('n',len(a),'min',min(a),'max',max(a),'median',statistics.median(a),'n>14',sum(1 for v in a if v>14))"
  .venv/Scripts/python.exe -c "import json,glob,numpy as np;from pipeline.tracetriage.physics import corridor_for_obs;
  raw=[r for p in sorted(glob.glob('D:/tracetriage_data/snap-stage1/pages/*.json')) for r in json.load(open(p)) if r.get('id')==14740031][0];
  r=corridor_for_obs(raw);d=np.array(r.uncorrected.doppler_hz);t=np.array(r.uncorrected.fracs)*r.pass_duration_s;
  s=np.abs(np.gradient(d,t)).max();print('peak slope Hz/s',round(s,1));print([(k,round(s*k),round(s*k/2000,2)) for k in (1,5,10,30)])"
  ```

- **Suggested fix**: derive the bound from the corridor half-width and the object's drag term
  rather than from nothing. A tolerance of 0.25 half-widths is about 4 seconds of timing, which
  is 1 to 3 days for a typical LEO and much less for a high-drag object. Publish the epoch-age
  distribution in the receipt so a reader can see the threshold is currently inert.

---

### [SERIOUS] Rows where the satellite is below the local horizon are neither masked nor reported, and a fifth of observations have them

- **Where**: `pipeline/tracetriage/physics.py:396-401` (elevation computed for every sample and
  all returned), `pipeline/tracetriage/corridor_fit.py` (no elevation mask anywhere),
  `pipeline/tracetriage/physics.py:731-742` (every row mapped).

- **What is wrong**: SatNOGS observation windows are not horizon to horizon, and some start
  below the horizon. A corridor drawn over a row where the satellite is below the station's
  horizon cannot contain a real trace, because the line of sight passes through the Earth.
  Those rows still contribute to `path_score`, still dilute `coverage`, and are still counted
  in the detection fraction tested against `min_detect_frac = 0.30`. There is no Earth
  occultation test beyond the implicit elevation sign, and `Corridor` carries no visibility
  information at all, so a downstream consumer cannot apply the mask either.

- **How I know**: propagated all 200 cached records at 128 samples and measured the elevation
  series. Elevation at window start has mean 12.95 degrees, standard deviation 13.16, minimum
  **-5.87**, maximum 59.10. **39 of 200 observations, 19.5 percent, contain at least one
  below-horizon sample**, with a maximum of 17.2 percent of a single window below the horizon
  and a mean of 0.48 percent across the sample.

  This does not affect the published gate-3 numbers. The three scored observations start and
  end at +20.0, +4.8 and +4.8 degrees with zero below-horizon rows. It is a live defect at
  snapshot scale, where a fifth of the corpus carries such rows. Three of the 25 shipped
  console cards also carry them.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  grep -n "elevation\|horizon\|occult" pipeline/tracetriage/corridor_fit.py
  .venv/Scripts/python.exe -c "
  import json,glob,numpy as np
  from datetime import datetime
  from pipeline.tracetriage import physics as P
  f=[]
  for p in sorted(glob.glob('.a3_cache/a4_validation_pages/*/page_*.json')):
      if 'headers' in p: continue
      for r in json.load(open(p)):
          if not (r.get('tle1') and r.get('tle2') and r.get('max_altitude') is not None): continue
          lat=float(r['station_lat']);lon=float(r['station_lng']);alt=float(r['station_alt'])
          st=datetime.fromisoformat(r['start'].replace('Z','+00:00'));en=datetime.fromisoformat(r['end'].replace('Z','+00:00'))
          _,_,els,_=P.propagate_pass(r['tle1'],r['tle2'],st,en,P.station_ecef(lat,lon,alt),4.35e8,P.geodetic_normal(lat,lon),n_samples=128)
          e=np.array(els);f.append(float(np.mean(e<0)))
  f=np.array(f);print('n',len(f),'with any below-horizon',int((f>0).sum()),'max window fraction %.3f'%f.max())"
  ```

- **Suggested fix**: carry `elevation_deg` on `Corridor`, mask rows below a stated elevation
  floor (0 degrees at minimum, and a real station mask sits well above it), and report the
  masked fraction per observation. `SkyPlot.tsx` already gets this right, breaking the path at
  negative elevation rather than clamping it. The scorer should agree with the plot.

---

### [SERIOUS] `AXIS_SIGN_CONVENTION` is a global constant established on three observations from two of four client families, where the upstream analysis fitted the sign per observation

- **Where**: `pipeline/tracetriage/physics.py:137-140`, under the heading at
  `physics.py:15-16` that reads "CALIBRATION FACTS, do not re-derive, do not check by eye".

- **What is wrong**: the axis direction is a property of the rendering code, not of the pass,
  and it is asserted as a global constant. The evidence in `artifacts/a3_overlays/summary.json`
  is `frequency_axis_sign`, chosen per observation as the argmax of `sigma_curved_by_sign`, and
  it did not come out the same for every observation.

- **How I know**: read the stored per-observation sign and both sigmas for all seven decisive
  observations.

  | obs | verdict | client family | station | sign chosen | sigma at +1 | sigma at -1 |
  |---|---|---|---|---|---|---|
  | 14740031 | UNCORRECTED | 1.6 | 91 | -1 | 1.99 | **25.10** |
  | 14745664 | UNCORRECTED | 2.1.2 | 1696 | -1 | 1.18 | **15.14** |
  | 14745929 | UNCORRECTED | 2.1.2 | 1696 | -1 | 1.41 | **15.94** |
  | 14746118 | CORRECTED | 2.1.2 | | **+1** | 7.27 | 7.12 |
  | 14746055 | CORRECTED | 1.9.3 | | -1 | 20.96 | 21.01 |
  | 14746048 | CORRECTED | 1.9.3 | | -1 | 1.60 | 1.71 |
  | 14745602 | CORRECTED | 2.1.2 | | **+1** | 12.03 | 10.19 |

  On the corrected observations the two signs are tied to within a few percent, because a flat
  corridor has no shape and the sign is unmeasurable there. The argmax then returns noise, and
  it returned +1 twice. Where the sign is measurable, -1 wins by more than an order of
  magnitude, which is a real result and which my own inversion test reproduces independently.

  The scope of the evidence is 3 observations, 1 UTC night, 2 stations, one frequency
  (436.4 MHz), and 2 of the 4 client families present in the set (1.6 and 2.1.2). Families
  1.8.1 and 1.9.3 have no observation on which the sign can be measured. A family-dependent
  sign is the specific risk, and it is untested on half the families already in hand.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json;from pathlib import Path;
  a=json.loads(Path('artifacts/a3_overlays/summary.json').read_text(encoding='utf-8'));
  print([(r['obs_id'],r['verdict'],r['family'],r['frequency_axis_sign'],r['sigma_curved_by_sign']) for r in a if r.get('verdict') in ('CORRECTED','UNCORRECTED')])"
  ```

- **Suggested fix**: state the evidence base beside the constant, naming the families, the
  frequencies and the observation count. Add a guard that recomputes the sign for a client
  family the first time one appears with no measurable observation behind it, rather than
  assuming the constant travels across renderer versions.

---

### [SERIOUS] Gate 5's grouped bootstrap resamples groups of size 1.0 in every published interval, while the same corpus measures a station ICC of 0.089

- **Where**: `artifacts/FUSION_RECEIPT.json` (`gate5.per_split.*` and `splits[*].comparisons.*`),
  `pipeline/tracetriage/fusion.py:375-440` (`grouped_paired_bootstrap` and its `note`), against
  `pipeline/tracetriage/queue.py:218-241` and `artifacts/QUEUE_RECEIPT.json`.

- **What is wrong**: this is not the observation that gate 5 is inconclusive, which is
  deliberate and correctly reported. It is that the interval was computed the wrong way. Every
  gate-5 interval carries `n_groups == n_observations` and `mean_group_size: 1.0`, so the
  episode bootstrap is arithmetically identical to an observation-level bootstrap and provides
  none of the clustering protection its own note claims:

  > Bootstrap resamples pass episodes, not observations, because captures of one pass at one
  > station share a receiver and a geometry.

  That statement sits in the same JSON object as `"mean_group_size": 1.0`. The project knows
  this: the ICC docstring at `queue.py:227-231` says "Episodes hold 1.004 observations each, so
  there is no within-episode variance to partition, while stations hold 2.86 in the
  chronological test partition and carry an ICC of 0.1409 on the conflict indicator." Unit C2
  acted on it and unit B did not.

- **How I know**: the group counts, read from the receipt: 88 groups over 88 observations on
  chronological, 217 over 217 on cold_station, 96 on cold_transmitter, 76 on cold_combined.
  There is no station-clustered interval anywhere in the fusion receipt.

  `artifacts/QUEUE_RECEIPT.json` does it correctly for gate 6: `episode_clustering.measurable`
  is `false` with the reason "Got 87 groups over 87 observations",
  `station_clustering.icc = 0.0887` with `design_effect = 1.1318` over 35 stations, and
  `governing_interval = "union_of_episode_and_station"`, publishing
  `lift_ci95 = [1.3533, 1.7547]` as the union of `[1.3533, 1.7400]` and `[1.3744, 1.7547]`.

  The asymmetry matters because the one claim in the project that clears zero is a gate-5
  comparison. `chronological / image_corridor_vs_image_only`: margin +0.020264, 95 percent
  interval [0.006951, 0.034352], Bonferroni-adjusted to [0.002959, 0.039763]. Applying the
  station design effect measured on the matching split (1.1318, a standard-error factor of
  1.0639) moves the corrected lower bound from **+0.00296 to +0.00185**. It survives, thinly.
  The design effect that would take it to zero is 1.371, which needs a station ICC near 0.25
  against the 0.089 measured.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json;from pathlib import Path;
  r=json.loads(Path('artifacts/FUSION_RECEIPT.json').read_text(encoding='utf-8'));
  print({k:(v.get('n_observations'),v.get('n_groups')) for k,v in r['gate5']['per_split'].items()});
  c=[s for s in r['splits'] if s['split']=='chronological'][0]['comparisons']['image_corridor_vs_image_only'];
  print('mean_group_size',c['mean_group_size'],'ci',c['ci95']);
  m=[s for s in r['splits'] if s['split']=='chronological'][0]['multiplicity_adjusted']['image_corridor_vs_image_only'];
  print('adjusted',m['ci_adjusted']);
  import math;f=math.sqrt(1.1318);print('widened lower bound',m['margin']-(m['margin']-m['ci_adjusted'][0])*f)"
  .venv/Scripts/python.exe -c "import json;from pathlib import Path;
  q=json.loads(Path('artifacts/QUEUE_RECEIPT.json').read_text(encoding='utf-8'))['gate6']['per_split']['chronological'];
  print(q['governing_interval'],q['lift_ci95_episode'],q['lift_ci95_station'],q['station_clustering'])"
  ```

- **Suggested fix**: compute the station-clustered interval for the Brier comparisons and
  publish the union, exactly as unit C2 already does for gate 6. Change the note to say the
  episode grouping is inert on this corpus and print the group size beside it. A protection
  whose mean group size is 1.0 should not be described as protecting anything.

---

### [SERIOUS] The multiplicity correction stops at the split boundary while the decision rule ranges across splits, and the receipt says so itself

- **Where**: `scripts/run_fusion.py:341-372` (`n_family = len(challengers) + _N_AURC_COMPARISONS`),
  and `artifacts/FUSION_RECEIPT.json` at `ablation_conclusion.rules.multiplicity_corrected`
  and `ablation_conclusion.why_the_corrected_rule_decides`.

- **What is wrong**: the correction is Bonferroni over 7 comparisons within one split. The
  decision rule is not within-split:

  > Retain a block if an arm containing it beat image-only with a 95% interval clearing zero
  > **on a split** with at least 300 decisive training rows, and no such split showed it
  > reliably worse.

  That is a disjunction across splits, and the receipt's own justification names the real
  family size: "this ladder runs 5 comparisons on each of 4 splits, where one nominal win by
  chance is the expected outcome rather than evidence." Twenty comparisons, corrected over
  seven. The `corridor` block's RETAIN rests on exactly one of them,
  `better_on: ["chronological/image_corridor"]`, `worse_on: []`, and that is the arm that
  ships.

- **How I know**: `challengers` is the five arms containing `image` excluding the reference and
  `prior_only`, plus 2 AURC comparisons, so `n_family = 7`, confirmed by
  `"n_comparisons": 7` and `"per_comparison_alpha": 0.0071428...` in the receipt.
  `splits_used` is `["chronological", "cold_station", "cold_transmitter"]` with
  `cold_combined` below the training floor, so the live family is 5 challengers on at least 3
  splits, 15 comparisons, and the receipt's own text says 20.

  Correcting at the 20-comparison level needs the 0.125th percentile of the bootstrap. At
  `n_boot = 4000` that is the 5th draw, which cannot resolve an interval endpoint. The
  correction actually applied (99.286 percent, the 0.357th percentile) is decided by about 14
  draws of 4,000. Extrapolating the two published endpoints in z suggests the interval would
  still clear zero by roughly +0.001, but that is an extrapolation and not a measurement.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "import json;from pathlib import Path;
  a=json.loads(Path('artifacts/FUSION_RECEIPT.json').read_text(encoding='utf-8'))['ablation_conclusion'];
  print(a['rules']['multiplicity_corrected']);print(a['why_the_corrected_rule_decides']);
  print('splits_used',a['splits_used']);print('corridor',a['multiplicity_corrected']['blocks']['corridor'])"
  .venv/Scripts/python.exe -c "print('draw index at alpha/2 for 20 comparisons:',0.05/20/2*4000)"
  ```

- **Suggested fix**: either correct over the family the decision rule actually reads, or narrow
  the rule to one pre-registered split. Whichever is chosen, raise `n_boot` until the adjusted
  percentile is resolved by more than a handful of draws; a 20-comparison Bonferroni wants of
  order 50,000. The project's single surviving claim should not rest on an interval endpoint
  determined by five bootstrap samples.

---

### [SERIOUS] The ground track's footprint polygon spans 360 degrees of longitude on a shipped page, compressing the whole track into four percent of the plot

- **Where**: `apps/web/lib/projection.ts`, `horizonCircle` (returns `lam + atan2(...)` with no
  unwrapping) and `groundBounds` (takes min and max over `circleLon`);
  `apps/web/components/GroundTrack.tsx`, `boundsForPass`.

- **What is wrong**: `unwrapLongitudes` is applied to the track and to the station longitude
  and not to the footprint circle. When the circle encloses a pole the `atan2` denominator
  `cos(theta) - sin(phi) sin(latR)` changes sign, the returned longitudes cover the full range,
  and `groundBounds` frames the whole world. The trigger is
  `|subsatellite latitude| + half-angle > 90`, which for a 500 km orbit means any subsatellite
  latitude above about 68 degrees. Unwrapping the circle does not fix it either: a
  pole-enclosing small circle genuinely covers every longitude, so the frame has to be decided
  by the track and the circle clipped.

- **How I know**: reproduced `horizonCircle`, `unwrapLongitudes` and `groundBounds` and ran
  them over all 25 shipped cards in `apps/web/public/data/cards.json`. It is live on
  **observation 14744250** (station 329CZ144, NORAD 46487):

  | | |
  |---|---|
  | subsatellite latitude at closest approach | 62.28 deg |
  | altitude at closest approach | 1,518 km |
  | footprint half-angle | 36.14 deg |
  | sum against the 90 deg limit | **98.41 deg** |
  | circle longitude span drawn | **360.0 deg** |
  | ground track longitude span | 15.5 deg |
  | fraction of plot width the track occupies | **4.3 percent, 16.2 px of 378** |

  Confirmed the general condition separately at subsatellite latitudes 50, 60, 72, 78 and 80
  degrees: the drawn longitude span is 71.3, 97.0, 360.0, 360.0 and 360.0 degrees. Polar and
  sun-synchronous orbits are most of the SatNOGS target set, so this recurs at scale.

- **How to reproduce**:

  ```
  cd "D:/IBM August Challenge/tracetriage-august-2026"
  .venv/Scripts/python.exe -c "
  import json,math
  from pathlib import Path
  R=6371.0088
  def circle(la,lo,h,step=3):
      half=math.degrees(math.acos(min(1,R/(R+max(h,1)))));phi=math.radians(la);lam=math.radians(lo);th=math.radians(half)
      lon=[];d=0
      while d<=360:
          b=math.radians(d)
          lr=math.asin(math.sin(phi)*math.cos(th)+math.cos(phi)*math.sin(th)*math.cos(b))
          lon.append(math.degrees(lam+math.atan2(math.sin(b)*math.sin(th)*math.cos(phi),math.cos(th)-math.sin(phi)*math.sin(lr))));d+=step
      return lon,half
  for c in json.loads(Path('apps/web/public/data/cards.json').read_text(encoding='utf-8'))['cards']:
      g=c['geometry'];el=g['elevation_deg'];i=max(range(len(el)),key=lambda k:el[k])
      lon,half=circle(g['sub_lat_deg'][i],g['sub_lon_deg'][i],g['altitude_km'][i])
      s=max(lon)-min(lon)
      if s>180: print('BROKEN FRAME',c['obs_id'],'sub_lat %.2f half %.2f sum %.2f span %.1f'%(g['sub_lat_deg'][i],half,abs(g['sub_lat_deg'][i])+half,s))"
  ```

- **Suggested fix**: frame on the track and the station only, then clip the footprint to the
  frame, or cap the frame span and draw the footprint as a clipped path. Say in the caption
  that the circle continues off-plot, so a reader is not misled about the footprint's extent.

---

### [SERIOUS] `corridor_fit`'s sigma is not comparable to the upstream sigma, contrary to the docstring, and the two disagree about which curve wins

- **Where**: `pipeline/tracetriage/corridor_fit.py:414-417`, against
  `artifacts/a3_overlays/summary.json` and the two figures quoted in different sections of
  `docs/KILL_GATE.md`.

- **What is wrong**: the docstring says "The estimator is the same matched filter A3 used, so
  the numbers stay comparable. The difference is the search range: bounded here, unbounded
  there." The scales differ by more than an order of magnitude, and the difference is large
  enough to invert the reader's conclusion.

- **How I know**: measured on obs 14740031.

  | statistic | value |
  |---|---|
  | stored `sigma_curved` | 25.10 |
  | stored `sigma_vertical` | 2.83 |
  | `corridor_fit` true sigma | **2.024** |

  A factor of 12.4 between the two curved sigmas, and the upstream *vertical* sigma exceeds the
  downstream *curved* sigma. A reader comparing the artifacts concludes that a straight
  vertical line beats the Doppler curve, which is the opposite of the finding. The same
  pattern holds on the other two: 15.14 against 1.539, and 15.94 against 1.652. The cause is
  legitimate, `_pixel_sigma_scale` normalising against the MAD of the whole `zs` array; the
  comparability claim is not.

- **How to reproduce**: run the gate-3 command from the fourth BLOCKING finding and compare
  its `true` sigma against
  `[(r['obs_id'], r['sigma_curved'], r['sigma_vertical']) for r in json.loads(Path('artifacts/a3_overlays/summary.json').read_text(encoding='utf-8')) if r.get('verdict') == 'UNCORRECTED']`.

- **Suggested fix**: delete the comparability claim, or print both statistics side by side with
  their definitions. `docs/KILL_GATE.md` quotes 25.1 sigma in one section and 2.02 in another
  without noting they are different scales.

---

### [MINOR] UT1 minus UTC is the largest neglected frame term and is not mentioned

- **Where**: `pipeline/tracetriage/physics.py:243-255` (`eci_to_ecef` docstring),
  `pipeline/tracetriage/physics.py:229-240` (`gmst`, evaluated on UTC).

- **What is wrong**: the docstring lists "no polar motion, no nutation corrections" and omits
  the substitution of UTC for UT1, which is the largest of the three. Separately, "no nutation
  corrections" is imprecise: GMST1982 is the correct rotation angle for the TEME frame that
  SGP4 emits, so there is no nutation term being dropped. The three real omissions are UT1,
  polar motion, and the pseudo-Earth-fixed to WGS-84 difference, in that order of size.

- **How I know**: computed. `|UT1 - UTC| <= 0.9 s` is 0.00376 degrees of Earth rotation, 13.5
  arcsec, which displaces the satellite 451 m and gives 0.052 degrees of pointing error at
  500 km slant range, 0.026 at 1,000 km and 0.013 at 2,000 km. Polar motion at roughly 0.3
  arcsec of pole offset gives about 0.001 degrees. The UT1 term is a quarter of the geodetic
  error unit C7 just fixed and 50 times polar motion.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import math;r=0.9*360.98564736629/86400;print(r,'deg',r*3600,'arcsec');d=math.radians(r)*6871.0;print(d*1000,'m',[math.degrees(d/x) for x in (500,1000,2000)])"`

- **Suggested fix**: replace "no nutation corrections" with the three omissions and their
  sizes. Nothing in the code needs to change.

---

### [MINOR] Ionospheric, tropospheric and relativistic terms are never acknowledged

- **Where**: `pipeline/tracetriage/physics.py:386-394` (the Doppler computation) and the
  module docstring, which documents the free constant offset and no other frequency term.

- **What is wrong**: all these terms are negligible, so omitting them is correct. The silence
  is the gap: a flight-dynamics reader will ask, and one sentence with a number closes it.

- **How I know**: computed. Second-order Doppler at 7.6 km/s is 3.21e-10 fractional, 0.140 Hz
  at 436.4 MHz. Gravitational shift between the surface and 500 km is 5.07e-11, 0.022 Hz. The
  ionosphere contributes 2.12 m per TECU at 436 MHz and 21.32 m per TECU at 137 MHz, so a
  30 TECU slant change across a 300 s pass is 0.31 Hz and 0.98 Hz. The troposphere is
  non-dispersive and gives under 1 Hz. Against half-widths of 1,200 and 2,000 Hz the largest is
  0.05 percent.

  One exception worth recording: tropospheric *refraction* at low elevation is about 0.16
  degrees at 5 degrees elevation and 0.55 degrees at the horizon, which dwarfs the 0.19 degree
  geodetic effect. It is correctly not applied, because `max_altitude` is itself a geometric
  prediction and applying refraction to one side of that comparison would introduce a bias.
  If an elevation is ever compared against a pointed antenna it will matter.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "c=299792458.0;
  print('2nd order Hz',436.4e6*7.6e3**2/(2*c*c));
  print('grav Hz',436.4e6*3.986004418e14/(c*c)*(1/6371e3-1/6871e3));
  [print(f/1e6,'MHz iono Hz',f*(40.3e16/f**2*30/300)/c) for f in (436.4e6,137.5e6)]"`

- **Suggested fix**: one paragraph in the module docstring with the 0.98 Hz worst case and the
  refraction caveat.

---

### [MINOR] The sky plot's cardinal labels have exactly zero offset

- **Where**: `apps/web/components/SkyPlot.tsx`, the `CARDINALS.map` block calling
  `projectSky(azDeg, -7.5)`; `apps/web/lib/projection.ts`, `projectSky`'s
  `Math.max(0, Math.min(90, elDeg))`.

- **What is wrong**: the label anchor asks for a position 7.5 degrees below the horizon so the
  glyph sits outside the ring. The clamp turns -7.5 into 0, so the anchor lands exactly on the
  spoke end and the N, E, S and W glyphs sit on the horizon circle instead of outside it.

- **How I know**: evaluated both calls at all four cardinals. Spoke end and label anchor are
  identical to four decimal places at every azimuth; the offset is 0.0000 px against an
  intended `SKY.r * 7.5 / 90 = 11.00` px.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import math
  def p(az,el):
      c=max(0,min(90,el));r=132*(90-c)/90;a=math.radians(az-90);return (160+r*math.cos(a),160+r*math.sin(a))
  print([(az,math.dist(p(az,0),p(az,-7.5))) for az in (0,90,180,270)],'intended',132*7.5/90)"`

- **Suggested fix**: compute the label radius directly rather than through `projectSky`, or give
  `projectSky` an opt-out for the clamp. The clamp itself is right for track samples.

---

### [MINOR] The ground track's aspect ratio is not preserved and is not labelled

- **Where**: `apps/web/lib/projection.ts`, `projectGround`;
  `apps/web/components/GroundTrack.tsx` module docstring.

- **What is wrong**: `projectGround` scales longitude and latitude independently to fill a
  fixed 378 by 232 box, so the footprint circle, correctly computed as a spherical locus, is
  drawn as an ellipse whose eccentricity depends on the frame. The component docstring explains
  that the circle is walked on the sphere rather than drawn as an ellipse "because away from
  the equator an ellipse is wrong by more than the circle is wide", and then the projection
  stretches it into one.

- **How I know**: read the two scale expressions; `plotW / (lonMax - lonMin)` and
  `plotH / (latMax - latMin)` are independent with no equalisation step.

- **How to reproduce**: read `projectGround` in `apps/web/lib/projection.ts`.

- **Suggested fix**: either equalise the two scales, or add a per-axis degree-per-pixel note to
  the caption so a reader does not read the drawn shape as the physical one.

---

### [MINOR] Gate 1 arithmetic: "roughly 15 minutes at 0.4 s spacing" is wrong

- **Where**: `docs/KILL_GATE.md`, gate 1, the 10,000-observation table row for cursor pages.

- **What is wrong**: "Cursor pages at 25/page | ~400, roughly 15 minutes at 0.4 s spacing".
  400 pages at 0.4 s is 160 s, which is 2.7 minutes. Fifteen minutes needs 2.25 s per page.

- **How I know**: checked every number in gates 1 and 2. All the others hold: 197/12 = 16.4x,
  211/30 = 7.0x, 2000/0.923 = 2,167 records, 2170/25 = 87 pages, 2000 x 1.7 MB = 3.4 GB,
  9230 x 1.7 MB = 15.7 GB, 18.83/10.17 = 1.85, 61/600 = 10.17 percent, and gate 2's union
  bound 1 - 0.06 - 0.077 = 0.863. This one row does not.

- **How to reproduce**: `.venv/Scripts/python.exe -c "print(400*0.4/60,'minutes'); print(900/400,'s per page to reach 15 min')"`

- **Suggested fix**: state the real per-page round trip, or change the figure to 2.7 minutes of
  spacing plus request latency.

---

### [MINOR] `transmitter_downlink_drift` is consumed as a model feature and never as a physics cross-check

- **Where**: `pipeline/tracetriage/features.py:266` and `:303`,
  `pipeline/tracetriage/fusion.py:130`; absent from `pipeline/tracetriage/physics.py` and
  `pipeline/tracetriage/corridor_fit.py`.

- **What is wrong**: SatNOGS publishes a measured downlink drift per transmitter, which is
  part of the quantity the "free constant offset" absorbs. Comparing the fitted offset against
  the published drift on records that carry it would move gate 3 partway from a shape test
  toward the position test its own name implies.

- **How I know**: the field is present on 29 of the 200 cached records with values from -12,468
  to +44,007, which in parts per billion is -12.5 to +44 ppm. The gate-3 fitted offsets are
  +32.0, -16.4 and -16.4 ppm against a 50 ppm bound, inside exactly that range.

- **How to reproduce**:
  ```
  .venv/Scripts/python.exe -c "import json,glob;
  d=[r.get('transmitter_downlink_drift') for p in sorted(glob.glob('.a3_cache/a4_validation_pages/*/page_*.json')) if 'headers' not in p for r in json.load(open(p))];
  print('non-null',sum(1 for x in d if x is not None),'range',min(x for x in d if x is not None),max(x for x in d if x is not None))"
  ```

- **Suggested fix**: report `fitted_offset_ppm` beside `transmitter_downlink_drift` for every
  observation that has both, and note the agreement or the disagreement. It costs nothing and
  it addresses the gate's stated open question directly.

---

### [MINOR] `design_effect` uses the plain mean group size while the ICC uses the size-adjusted `n0`

- **Where**: `pipeline/tracetriage/queue.py:264-280`.

- **What is wrong**: the ICC denominator uses `n0 = (N - sum(n_i^2)/N) / (k - 1)`, and two
  lines later `design_effect = 1 + (mean_size - 1) * max(icc, 0)` uses `mean_size = N / k`.
  Mixing the two is conventional and both values are published, so a reader can recompute
  either way. Noted only because the two sit adjacent.

- **How I know**: read both expressions; the receipt reports `mean_group_size` 2.4857 and
  `size_adjusted_mean_group_size` 2.4165 on the chronological split, so the two differ by 3
  percent and the design effect changes by under 1 percent.

- **How to reproduce**: read `queue.py:264-280` and compare against
  `gate6.per_split.chronological.station_clustering` in `artifacts/QUEUE_RECEIPT.json`.

- **Suggested fix**: none required. If changed, say which convention in the receipt note.

---

### [MINOR] One published interval sits outside the corrected family

- **Where**: `scripts/run_fusion.py:336-346`.

- **What is wrong**: `image_only_vs_prior_only` is computed and published on every split and is
  not counted in `n_family = 7`, so eight intervals are reported against a family of seven.
  It is a sanity check rather than a claim about the physics, so the omission is defensible; it
  is not stated.

- **How I know**: counted the keys in `splits[*].comparisons` against `n_comparisons` in
  `splits[*].multiplicity_adjusted`.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import json;from pathlib import Path;s=[x for x in json.loads(Path('artifacts/FUSION_RECEIPT.json').read_text(encoding='utf-8'))['splits'] if x['split']=='chronological'][0];print(len(s['comparisons']),list(s['comparisons']));print(list(s['multiplicity_adjusted'].values())[0]['n_comparisons'])"`

- **Suggested fix**: one sentence in the family comment saying which reported interval is
  excluded and why.

---

### [MINOR] `transmitter_invert` is a spectral-inversion flag and is treated only as a feature

- **Where**: `pipeline/tracetriage/features.py:300` and `:312`,
  `pipeline/tracetriage/fusion.py:134`; absent from `pipeline/tracetriage/physics.py`.

- **What is wrong**: for a linear-transponder passband an inverting transponder reverses the
  sense of the observed frequency excursion. For a plain telemetry downlink it is irrelevant, which is the usual
  case here, but it is exactly the kind of per-record condition that would break a global sign
  convention, and it is never consulted by the physics.

- **How I know**: set on 1 of the 200 cached records. Grep confirms it appears only in the
  feature and split-admissibility tables.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import json,glob;print(sum(1 for p in sorted(glob.glob('.a3_cache/a4_validation_pages/*/page_*.json')) if 'headers' not in p for r in json.load(open(p)) if r.get('transmitter_invert')))"`

- **Suggested fix**: mention the interaction with the sign convention in the note beside
  `AXIS_SIGN_CONVENTION`, even if no code change follows.

---

### [MINOR] Truncated pass windows are handled silently

- **Where**: `pipeline/tracetriage/physics.py:652-654` (`max_el` and `tca_frac` taken over the
  window), `apps/web/components/SkyPlot.tsx` (the closest-approach marker).

- **What is wrong**: when the culmination falls outside the recorded window,
  `max_elevation_deg` is a window boundary value rather than a pass maximum, and comparing it
  against the API's `max_altitude` compares two different quantities. Nothing flags it. The sky
  plot guards its rise and set markers with `firstEl >= 0` and `lastEl >= 0` and applies no
  such guard to the closest-approach marker, which would be clamped to the rim rather than
  dropped.

- **How I know**: `tca_frac` reaches 1.0 on one of the 200 validation records and 0.0 on
  shipped card 14744250, where the peak elevation is the very first sample and the rise and
  closest-approach markers therefore coincide. The 3.44 degree validation outlier
  (obs 14735287) has `tca_frac` 0.656 and a window running from -5.87 to +6.91 degrees.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import json;o=json.load(open('artifacts/PHYSICS_VALIDATION.json'))['observations'];t=[x['tca_frac'] for x in o if x.get('tca_frac') is not None];print('min',min(t),'max',max(t),'at boundary',sum(1 for v in t if v<=0.001 or v>=0.999))"`

- **Suggested fix**: flag `tca_frac` at a window boundary in the validation record, and add the
  same `>= 0` guard to the closest-approach marker.

---

### [MINOR] Mean Earth radius is paired with an ellipsoidal height for the horizon half-angle

- **Where**: `apps/web/lib/projection.ts`, `EARTH_R_KM = 6371.0088` with the comment "The
  right one for a horizon half-angle", consuming `altitude_km` from
  `pipeline/tracetriage/physics.py:ecef_to_geodetic`, which returns height above the WGS-84
  ellipsoid.

- **What is wrong**: nothing measurable. The comment is a little confident for a quantity that
  has no single right value on an ellipsoid.

- **How I know**: at 500 km, `arccos(Re / (Re + h))` gives 22.04, 22.02 and 22.01 degrees for
  polar, mean and equatorial radii, so the half-angle moves by 0.03 degrees out of 22 across
  the full range. Negligible at plot resolution.

- **How to reproduce**:
  `.venv/Scripts/python.exe -c "import math;print([round(math.degrees(math.acos(R/(R+500))),3) for R in (6356.75,6371.0088,6378.137)])"`

- **Suggested fix**: soften the comment, or use the local prime-vertical radius at the
  subpoint. No behaviour change needed.

---

## Checked and found correct

Only items I actively verified, each with the check.

- **GMST formulation and epoch.** The J2000 constant 280.46061837 degrees equals 18.697375 h
  against the expected 18h 41m 50.548s = 18.697374 h. Compared the shipped first-order
  expression against the full IAU-1982 series including the T-squared and T-cubed terms: it
  differs by 0.099 arcsec at the observation epoch and 0.181 arcsec by 2036, which is 3 mm and
  6 mm at the equator. Using GMST rather than GAST is the correct pairing for the TEME frame
  SGP4 emits, so the choice is right and not merely adequate.

- **ECI to ECEF rotation sense.** `eci_to_ecef` implements ROT3(theta) as
  `[[c, s, 0], [-s, c, 0], [0, 0, 1]]`, which is the correct sense for TEME to
  pseudo-Earth-fixed. Checked component by component against the matrix definition.

- **The Earth-rotation correction to velocity, including its sign.** Derived
  `dR/dt r_eci` symbolically: it equals `omega (u_y, -u_x, 0)` where `u = r_ecef`, and
  `-omega_vec x r_ecef = -omega (-u_y, u_x, 0) = omega (u_y, -u_x, 0)`. The two agree, so
  `v_ecef = R(GMST) v_eci - omega x r_ecef` at `physics.py:266-268` is right.

- **The elevation reference fix is right, not merely different.** `geodetic_normal` returns
  `(cos phi cos lambda, cos phi sin lambda, sin phi)` at geodetic latitude, which are exactly
  the direction cosines of the WGS-84 ellipsoid normal. `station_ecef` uses the standard
  `N = a / sqrt(1 - e^2 sin^2 phi)` with `(N + h) cos phi cos lambda` and
  `(N (1 - e^2) + h) sin phi`. `propagate_pass` normalises `site_up` defensively and raises on
  a zero vector. The maximum geodetic-minus-geocentric elevation difference I measured across
  200 observations is 0.1915 degrees, matching the 0.1924 figure the docstring quotes.

- **The Doppler computation and its sign.** `dop = -range_rate * 1000 / c * freq_hz` is the
  correct one-way first-order expression, and one-way is the right choice for a receive-only
  ground station; two-way would be wrong here. The negation is right: approaching gives a
  negative range rate and a positive shift. Checked the magnitude independently: the measured
  range-rate extremes across 200 observations are -7.373 to +7.367 km/s, which at 436 MHz is
  plus or minus 10.7 kHz, consistent with the 16.6 to 19.5 kHz swings the gate-3 observations
  carry.

- **TLE epoch parsing.** Columns `tle1[18:32]` are the 14-character epoch field, verified
  against the fixed-column layout. The two-digit year window (57 to 99 to 1957 to 1999, 00 to
  56 to 2000 to 2056) matches the propagator library's own `epochyr < 57` branch, so the two
  cannot disagree about which century a TLE is from. Day-of-year 1.0 mapping to 1 January
  00:00 via `timedelta(days=day_frac - 1)` is right. Taking the absolute value of the epoch age
  is right, because SGP4 error grows in both directions from epoch and a retro-fitted TLE is
  not privileged.

- **The local East/North/Up basis and the azimuth convention.** Derived both:
  `east = z_hat x up_hat` reduces to `(-sin lambda, cos lambda, 0)`, and
  `north = up x east` reduces to `(-sin phi cos lambda, -sin phi sin lambda, cos phi)`, which
  are the textbook ENU vectors. `az = atan2(los . east, los . north) mod 360` is clockwise from
  true north. Then validated against the API's own `rise_azimuth` and `set_azimuth` on 200
  observations: median absolute difference 0.27 degrees, maximum 1.96, 100 percent within 3
  degrees, against 27.0 and 93.9 degrees for the two plausible wrong conventions. The comment
  explaining that east is taken from the spin axis because it is invariant under either
  latitude definition is correct.

- **The axis sign convention is correct.** Ran the inversion the gate's null suite omits.
  Sigma falls from 2.024, 1.539 and 1.652 to 0.590, 0.398 and 0.411, at or below the maximum
  of 200 scrambled nulls on all three observations. `AXIS_SIGN_CONVENTION = -1` is right on
  these three. See the fifth SERIOUS finding for the scope of that evidence and the fifth
  BLOCKING finding for the wrong reason given for not running this test.

- **The subsatellite point and the geodetic conversion.** `ecef_to_geodetic` takes longitude
  exactly from `atan2(y, x)`, iterates the standard fixed point
  `lat = atan2(z + N e^2 sin lat, p)` from a geocentric start, and takes height as
  `p / cos(lat) - N`, with a pole guard on `p_xy`. Reporting the subsatellite point in geodetic
  rather than geocentric latitude is the right choice for a track read against a coastline, and
  the docstring's 21 km figure for the difference at mid latitudes is correct. I did not re-run
  the convergence sweep; see "Limits".

- **The horizon-circle mathematics.** `arccos(Re / (Re + h))` is the correct central half-angle
  for a zero-elevation footprint, and the walk
  `lat = asin(sin phi cos theta + cos phi sin theta cos b)` with
  `lon = lam + atan2(sin b sin theta cos phi, cos theta - sin phi sin lat)` is the standard
  spherical destination-point formula. Reimplemented it and confirmed the latitude extremes
  come out at `sub_lat +/- half_angle` on non-polar cases (28.0 to 72.0 degrees for a 50 degree
  subpoint at a 21.99 degree half-angle). Walking it rather than drawing an ellipse is the
  right call. The framing defect is in how the output is consumed, not in the formula.

- **The sky-plot projection.** `projectSky` puts azimuth 0 at the top, 90 to the right, 180 at
  the bottom and 270 to the left, with radius linear in (90 minus elevation) and the zenith at
  the centre. Verified numerically at all four cardinals. This is the convention operations
  tools use. Dropping below-horizon samples with a path break rather than clamping them is
  correct and is the behaviour the corridor scorer should copy.

- **The intra-class correlation.** `queue.py:218` implements the one-way random-effects ICC(1)
  correctly, including the size-adjusted `n0` for unequal groups, reporting a negative ICC as
  measured and clamping only where it feeds the design effect. The zero-denominator branch
  reasons correctly that a constant outcome makes the correlation undefined rather than
  perfect. Checked the algebra against the ANOVA definition line by line.

- **Gate 6's clustering treatment.** Reporting `episode_clustering.measurable: false` with the
  group count as the reason, publishing both the episode and the station interval, and taking
  `governing_interval = "union_of_episode_and_station"` is the right answer to a grouping that
  turned out to be inert. Confirmed the published `lift_ci95` is genuinely the union of the two
  component intervals on both splits. Gate 5 should copy it.

- **The two-directional multiplicity correction.** The correction is applied to measured harms
  as well as measured wins, and it is live: the `physics` block reaches DROP on
  `worse_on: ["cold_station/image_physics"]`, so the DROP branch is not dead code. The AURC
  comparisons are folded into the family, so the statistic a reader leans on hardest is not the
  one held to the weakest standard. Correcting only the distinguishable comparisons is right,
  because a widened interval that already spanned zero still spans it.

- **The corrected-corridor exclusion.** `calibrate_against_nulls` returns early when the
  corridor span is zero, reasoning that every null reproduces a flat corridor exactly. That is
  right, and the receipt records the four excluded observations as a scope limit rather than as
  passes. The `min_swing_hz = 3000` floor is right for the same reason and is correctly
  reported as not live on this set; I confirmed the three swings are 17,290, 19,480 and
  18,628 Hz.

- **Negligible physics is genuinely negligible.** Computed the second-order Doppler (0.140 Hz),
  the gravitational shift (0.022 Hz), the ionospheric contribution (0.31 Hz at 436 MHz, 0.98 Hz
  at 137 MHz) and the tropospheric contribution (under 1 Hz) against half-widths of 1,200 and
  2,000 Hz. Omitting them is correct; only the acknowledgement is missing.

- **Honest reporting where it costs something.** Gates 5 and 6 read NOT ESTABLISHED with the
  point estimate in the favourable direction and the interval spanning the threshold. The
  withdrawn earlier gate-3 result is documented with the reason it was wrong, including that it
  compared two constants and could not fail. The `physics` block is dropped on its own measured
  harm. `ablation_conclusion.caveat` states that the retain decision reads test-set comparisons
  and is therefore optimistic. `why_the_corrected_rule_decides` admits the rule was tightened
  after seeing a number. That is the right register throughout, and gate 3's PASSED is the one
  place it is not applied.

---

## Limits of this review

Everything below was outside what I executed. None of it is asserted correct or incorrect.

- **`pipeline/tracetriage/waterfall.py` beyond its calling convention.** The crop-box
  detection, the axis-tick OCR that produces `hz_per_px`, the `centre_px` derivation, and the
  per-client-family layout handling are all unverified. I called `parse_waterfall` and used its
  output. This is the single largest unchecked input to gate 3, because every corridor position
  depends on `hz_per_px` and `centre_px`. The 123.76 Hz/px figure, the argument against
  substituting `samp-rate-rx`, and the claim that the derivation is stable within a client
  family are taken as given.

- **`ecef_to_geodetic`'s convergence claims.** The docstring states 1.3 mm of height error at
  three iterations, 0.007 mm at four, and 8e-13 degrees of latitude at five, over eight cases
  from the equator to 89.9 degrees and sea level to 400 km. The formula is the standard fixed
  point and I checked the algebra, but I did not re-run the sweep, so the specific figures and
  the claim that four iterations would pass the 1e-6 round-trip assertion while three would not
  are unchecked.

- **Most of `scripts/run_queue.py` and `pipeline/tracetriage/queue.py`.** I read
  `intraclass_correlation`, the concentration-cap record, and the gate-6 receipt. The conflict
  definition, `is_conflict` and `classify_reasons`, the deduplication, the entity-concentration
  cap logic, the replay against baselines, and the lift bootstrap itself are unverified. The
  gate-6 numbers are quoted from the receipt, not recomputed.

- **The test suite.** I did not run `pytest`. Every claim about what
  `tests/test_physics.py`, `tests/test_corridor_fit.py` and the rest pin is unchecked,
  including `test_pass_geometry_elevation_matches_propagate_pass`,
  `test_thresholds_are_the_documented_values` and
  `test_a3_offset_relates_by_exactly_minus_one_not_by_identity`.

- **Gate 4, blinded human decidability.** Marked OPEN with no artifact, so there was nothing
  to review. The protocol design in `docs/KILL_GATE.md` and `docs/LABEL_PROVENANCE.md` was not
  assessed.

- **`episode_bootstrap_ensemble`, `seed_sensitivity`, the calibration block, the
  out-of-distribution detector, and the selective-prediction threshold selection.** Read the
  call sites in `scripts/run_fusion.py` and not the implementations. The calibration slope and
  intercept, the expected calibration error, and the risk-coverage curve construction are
  unverified.

- **Whether the shipped pages render as the components imply.** I read the component source
  and the generated data under `apps/web/public/data/` and did not build or open the site, so
  the ground-track framing defect is established from the data and the projection code rather
  than from a rendered page. I would expect it to be visible on the observation page for
  14744250, and I did not look.

- **The snapshot builder, the provenance chain and the leakage audit.**
  `pipeline/tracetriage/snapshot.py`, `provenance.py` and `splits.py` were read only where they
  touch the fields the physics consumes. Gate 1's preservation obligations, the hashes, the
  retrieval times and the licence terms were not checked against the stored snapshot.

- **Whether the 3.44 degree validation outlier is explained by a TLE change at scheduling
  time.** That is my reading of the evidence (azimuths agree to 2 degrees, epoch age is
  0.46 days, the window is asymmetric about the culmination), and I did not retrieve the
  scheduling-time TLE to confirm it.
