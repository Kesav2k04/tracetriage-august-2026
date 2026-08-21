# Independent review: engineering

Scope was the data path (`scripts/build_console_data.py`, `scripts/run_queue.py`,
`scripts/run_fusion.py`, `pipeline/tracetriage/splits.py`), the JSON Schema contracts, the console
under `apps/web/`, the test suite, and release hygiene (`scripts/gate.py`, `.gitignore`,
`apps/web/vercel.json`). Commands run, all from the repository root unless noted:
`.venv/Scripts/python.exe -m pytest -q` (744 passed, 1 xfailed, 158 s);
`npx tsc --noEmit -p tsconfig.json` in `apps/web` (exit 0, no diagnostics);
`npx next build` in `apps/web` (exit 0, 33 pages);
`git check-ignore -v` against five representative tracked paths;
`jsonschema.Draft202012Validator` over each receipt and over three hand-built mutations of
`artifacts/FUSION_RECEIPT.json`;
`scripts/build_console_data.py` re-run with `_DATA_DIR` and `_IMG_DIR` rebound to a scratch directory,
so the committed export was never overwritten;
`pipeline.tracetriage.splits.check_field_classification` called directly against a non-existent path;
`curl -I` against the deployed console for the header claims;
and one mutation of `README.md`, reverted with `git checkout -- README.md`, to test whether the drift
test can fail. Analysis began at 7fbb980 and every finding below was re-verified against 9256bef after
four commits landed mid-review; where a commit changed a file a finding lives in, the re-verification
is quoted. `git status` is clean apart from this file.

## Findings

Three BLOCKING, ten SERIOUS, thirteen MINOR.

### [BLOCKING] A missing corridor fit is published as a measured zero offset

- **Where**: `scripts/build_console_data.py:234`
- **What is wrong**: `offset_hz = (corridor_row or {}).get("fitted_offset_hz") or 0.0`.
  `corridor_row` is `corridor_by_obs.get(obs_id)` (line 647), and `artifacts/corridor_features.json`
  covers 743 of 2,500 observations because it was built with `decisive_only: true`. Of the 407 entries
  in `artifacts/QUEUE_RECEIPT.json`, 320 have no corridor row, starting at rank 61. For any of them
  the card is written with `fitted_offset_hz: 0.0`, with `fitted_px` identical to `predicted_px`
  element for element, and with `corridor.note` still reading "the gap between them is the
  measurement". `fitted_offset_ppm`, `offset_at_bound`, `sigma_curved` and `sigma_vertical` are all
  null on the same card, so the receipt says nothing was fitted while the offset says zero was.
  The console then presents that as fact: `WaterfallViewer.tsx:98-103` builds the canvas text from the
  same field, so a reader using assistive technology is told the corridor "sits 0 hertz from the
  commanded receive frequency", and `app/observation/[id]/page.tsx:308` prints 0 in the Frequency
  offset stat under the detail line "no catalogue frequency to express this as a fraction", which
  names the wrong cause. This is the defect class `_require` was added to stop, described in the first
  person in that helper's own docstring 130 lines above.
- **How I know**: I imported the module, rebound `_IMG_DIR` to a scratch directory, and called
  `export_observation` on the first queue entry with no corridor row and an image on disk:

  ```
  target (61, 14732116)
  degraded: None corridor_note: None
     fitted_offset_hz = 0.0
     fitted_offset_ppm = None
     offset_at_bound = None
     sigma_curved = None
     sigma_vertical = None
     fitted_px == predicted_px ? True
     first 3 fitted [363.0, 362.63, 362.27] predicted [363.0, 362.63, 362.27]
  ```

  It does not fire on the committed `cards.json` only because all 25 shipped observations sit inside
  the top 60 of the queue or in `NAMED_OBSERVATIONS`. `--showcase` is a documented flag with a default
  of 24 (line 492), so `--showcase 100` publishes 40 fabricated zeros. The 27 rows that exist but are
  degraded (`NO_IMAGE`, `PHYSICS_STALE_TLE`) carry a null `fitted_offset_hz` and reach the same
  `or 0.0`. `scripts/build_console_data.py` is untouched by the four commits since 7fbb980, so this
  holds at HEAD.
- **How to reproduce**:
  ```
  .venv/Scripts/python.exe -c "import sys,json,pathlib; sys.path.insert(0,'.'); \
    import scripts.build_console_data as B; B._IMG_DIR=pathlib.Path('<scratch>'); \
    from pipeline.tracetriage.splits import _PAGES_DIR,_load_raw_pages; \
    raw=_load_raw_pages(_PAGES_DIR); \
    c=B.export_observation(14732116, raw[14732116], None); \
    print(c['corridor']['fitted_offset_hz'], c['corridor']['fitted_offset_ppm'], \
          c['corridor']['fitted_px']==c['corridor']['predicted_px'])"
  ```
- **Suggested fix**: treat absence as a withheld overlay and route it through the existing guard.
  ```python
  if corridor_row is None or corridor_row.get("fitted_offset_hz") is None:
      out["corridor_note"] = (
          "No corridor fit exists for this observation: it is outside the decisive pool "
          "corridor_features.json was built over, so there is no fitted offset to draw. The "
          "predicted curve is not shown alone, because one curve under this caption reads as a "
          "measured zero."
      )
      return out
  offset_hz = float(corridor_row["fitted_offset_hz"])
  ```
  Then drop the `(corridor_row or {})` pattern from the four sibling reads on lines 260, 261, 270
  and 271, which have the same shape.

### [BLOCKING] The time-series accessible label asserts a zero crossing that did not happen

- **Where**: `apps/web/components/PassTimeSeries.tsx:138-141`
- **What is wrong**: the sentence is built from the two endpoints and the crossing is never checked.
  On observation 14744250 the recording window lies entirely on one side of closest approach in
  Doppler terms: the curve runs from -5870.4 Hz to -7227.6 Hz and never changes sign. The label says
  it crosses zero. A sighted reader sees a curve that stays below the zero line and can discount the
  sentence; a reader using a screen reader gets only the sentence. The page-level caption at
  `app/observation/[id]/page.tsx:188-194` repeats the claim in prose, so the console asserts as
  measured fact something its own data contradicts for one of its 25 observations.
- **How I know**: `npx next build` at HEAD, then reading the built page:

  ```
  'Elevation and Doppler shift against pass time over 284 seconds. Elevation rises to 37.1
   degrees and falls back. The Doppler shift runs from -5870 Hz down through zero to -7228 Hz,
   crossing zero at the same instant elevation peaks.'
  ```

  and from `cards.json` for the same observation: `first -5870.4 last -7227.6 min -7227.6 max
  -5870.4`. Commit 9256bef rewrote this file's viewBox constants and text offsets and did not touch
  the label, so the sentence is unchanged and the quotation above is from a build at HEAD. Scanning
  all 25 cards, exactly one has a Doppler series with no sign change.
- **How to reproduce**:
  ```
  cd apps/web && npx next build
  python -c "import re;h=open('out/observation/14744250/index.html',encoding='utf-8').read(); \
    print(re.search(r'aria-label=\"([^\"]*Doppler shift runs[^\"]*)\"',h).group(1))"
  ```
- **Suggested fix**: derive the sentence from the series.
  ```tsx
  const crosses = dops
    ? dops.some((v, i) => i > 0 && (v >= 0) !== ((dops[i - 1] ?? v) >= 0))
    : false;
  ```
  Keep the current wording when `crosses`, and otherwise say the recording window lies entirely on one
  side of closest approach so the curve does not cross zero inside it. Reword the page-level caption to
  describe the design of the plot rather than assert an outcome, since it cannot be conditioned on the
  data where it sits.

### [BLOCKING] The leakage audit reads a hardcoded absolute path, and a missing snapshot there is a silent pass

- **Where**: `pipeline/tracetriage/splits.py:1295`, inside `build_leakage_audit`
- **What is wrong**: `field_check = check_field_classification(_PAGES_DIR)`. The function's signature
  takes `rows` and four partition maps and no `pages_dir`, and `_PAGES_DIR` is
  `Path("D:/tracetriage_data/snap-stage1/pages")`, a machine-specific absolute path.
  `scripts/build_splits.py` exposes `--pages-dir` (lines 48-53), threads it into `build_splits` and
  into `_build_obs_table`, and then calls `build_leakage_audit`, which ignores it. So the manifest is
  built from the snapshot the caller named while the audit's field-classification row is measured
  against whatever sits on that one drive path. The failure mode when the path is absent is silent:
  `_load_raw_pages` uses `pages_dir.glob("*.json")`, which yields nothing for a missing directory
  rather than raising, so the check returns a pass over zero fields and the audit records
  `result: PASS, n_examined: 0, n_violators: 0` with the detail string "Classified all 0 fields on the
  raw record". `reject_vacuous_checks` exists to refuse exactly this and is applied only to the
  manifest's `leakage_checks` dict at line 1133, never to the audit list. The one artifact a reader
  opens to check for leakage is the one with no vacuity gate on it.
- **How I know**: calling the function directly against a path that does not exist:

  ```
  missing pages_dir -> {'passed': True, 'n_examined': 0, 'n_records': 0, 'unclassified': []}
  signature: (rows, chron_map, station_map, transmitter_map, combined_map) -> list[dict[str, Any]]
  _PAGES_DIR = D:\tracetriage_data\snap-stage1\pages | exists: True
  ```

  The committed `LEAKAGE_AUDIT.json` is correct because it was produced where that path happens to
  exist. `splits.py` is untouched since 7fbb980.
- **How to reproduce**:
  ```
  .venv/Scripts/python.exe -c "import sys,pathlib; sys.path.insert(0,'.'); \
    from pipeline.tracetriage.splits import check_field_classification as c; \
    print(c(pathlib.Path('Z:/does/not/exist')))"
  ```
- **Suggested fix**: three parts. Add `pages_dir: Path` to `build_leakage_audit` and pass
  `args.pages_dir` from `scripts/build_splits.py:86`. Make `check_field_classification` raise when it
  loaded no records, because a classification over zero records is never a pass. Apply a vacuity gate
  to the audit list before writing it, so any row with `result: PASS` and `n_examined: 0` stops the
  write.

### [SERIOUS] Six of eight contracts have an open root, and only two pin their version

- **Where**: `contracts/fusion_receipt.schema.json`, `split_manifest.schema.json`,
  `triage_receipt.schema.json`, `waterfall_geometry.schema.json`, `source_observation.schema.json`,
  `dataset_manifest.schema.json`
- **What is wrong**: a receipt written by an older script validates against the current schema and is
  read as current.

  | Contract | root `additionalProperties` | `schema_version` subschema | required |
  | --- | --- | --- | --- |
  | `queue_receipt` | `false` | `{"const": "0.3.0"}` | yes |
  | `annotation_record` | `false` | `{"pattern": "^\\d+\\.\\d+\\.\\d+$"}` | yes |
  | `fusion_receipt` | absent | `{"type": "string"}` | yes |
  | `dataset_manifest` | absent | `{"const": "0.2.1"}` | yes |
  | `split_manifest` | absent | not declared | no |
  | `waterfall_geometry` | absent | not declared | no |
  | `triage_receipt` | absent | not declared | no |
  | `source_observation` | absent | not declared | no |

  `artifacts/SPLIT_MANIFEST.json` is the sharpest case: it carries no `schema_version` key at all and
  validates, because the schema neither declares nor requires the property, while the provenance page
  prints 0.3.0 for that contract read from the contract file's own metadata. So a reader sees a
  version the manifest never claimed.
- **How I know**: three mutations of the fusion receipt, validated with
  `jsonschema.Draft202012Validator`:

  ```
  baseline receipt: VALID
  MUT1 schema_version=0.0.1-prehistoric  -> VALID  (no const pin)
  MUT2 extra root key gate5_FINAL_v2      -> VALID  (open root)
  ```

  and, reading the documents against their schemas:
  `SPLIT_MANIFEST.json VALID / declared schema_version in doc: None, in contract: 0.3.0`.
  `tests/test_console_export.py:163` already writes the correct test for the queue receipt; the
  pattern was established and not applied to the other seven.
- **How to reproduce**:
  ```
  .venv/Scripts/python.exe -c "import json,copy,jsonschema as j; \
    s=json.load(open('contracts/fusion_receipt.schema.json')); \
    d=json.load(open('artifacts/FUSION_RECEIPT.json')); \
    m=copy.deepcopy(d); m['schema_version']='0.0.1'; m['junk']=1; \
    j.Draft202012Validator(s).validate(m); print('accepted an old version and a junk key')"
  ```
- **Suggested fix**: add `"additionalProperties": false` to each root, add a `schema` const and a
  `schema_version` const to each schema, add `schema_version` to each `required` list, emit it from
  each writer, and generalise `test_schema_version_is_pinned_so_an_old_writer_cannot_pass` into a
  parametrised test over `contracts/*.schema.json`. Closing the fusion contract will surface two
  undeclared keys immediately: `$defs/split_result` does not declare `test_positive_rate` or
  `train_positive_rate`, and the receipt carries both.

### [SERIOUS] Nested receipt reads bypass `_require`, and a null block silently deletes a section

- **Where**: `scripts/build_console_data.py:538-551`, and `apps/web/app/evaluation/page.tsx:541`
- **What is wrong**: `_require` guards the `splits` list and nothing inside it; the eight per-split
  fields are read with `.get()`. The contract requires only `split`, `degraded` and `counts` outright,
  adds `arms` and `comparisons` conditionally when `degraded` is null, and leaves the rest optional on
  an object with no `additionalProperties`. So five measured blocks can be renamed, validate cleanly,
  and be published as null. The consumer then differs by field: `chrono.selective?.curve` removes the
  entire risk and coverage section with no note, no warning tone and nothing in the DOM, while
  `Object.entries(chrono.arms)` at line 259 throws during the export, which is at least loud.
- **How I know**: renaming each optional key in a copy of the receipt and revalidating:

  ```
  rename selective              -> VALID  <- schema accepts the rename
  rename ood                    -> VALID
  rename multiplicity_adjusted  -> VALID
  rename ensemble               -> VALID
  rename test_positive_rate     -> VALID
  ```

  The attempt to rename `arms` was correctly rejected with `'arms' is a required property`, which is
  the conditional working.
- **How to reproduce**:
  ```
  .venv/Scripts/python.exe -c "import json,copy,jsonschema as j; \
    s=json.load(open('contracts/fusion_receipt.schema.json')); \
    d=json.load(open('artifacts/FUSION_RECEIPT.json')); m=copy.deepcopy(d); \
    m['splits'][0]['selective_X']=m['splits'][0].pop('selective'); \
    j.Draft202012Validator(s).validate(m); print('a renamed selective block still validates')"
  ```
- **Suggested fix**: mirror the contract's own conditional in the export, using `_require` for every
  field that must exist when the split is not degraded and `.get()` only for the genuinely optional
  `ensemble` and `ood`. Change the evaluation page to render a stated absence rather than nothing.

### [SERIOUS] Below-horizon elevation is rendered three different ways on the same page

- **Where**: `apps/web/components/SkyPlot.tsx:41`, `apps/web/components/PassTimeSeries.tsx:96`,
  `apps/web/lib/projection.ts:33` with `apps/web/components/PassReplay.tsx:200-203`
- **What is wrong**: three consumers of the same `elevation_deg` series disagree. The sky plot breaks
  the polyline at a negative sample and its comment says why: "clamping would draw a segment along the
  rim that never happened". The time series clamps with `Math.max(0, deg) / 90`, drawing a flat
  segment along the zero line for exactly those samples. `projectSky` clamps with
  `Math.max(0, Math.min(90, elDeg))`, and the replay calls it behind only a `Number.isFinite` guard,
  so during playback the sky cursor sits pinned on the horizon ring while the track it is tracing has
  a gap there. The projection module's docstring says it exists so that "a cursor does not sit on the
  line it is supposed to be tracing", and the shared projection is what breaks that property, because
  the plot applies a policy the projection does not know about.
- **How I know**: scanning the exported geometry of all 25 shipped cards:

  ```
  cards with a below-horizon sample: 3
  (14742034, 5 negatives, min -0.609)
  (14742036, 5 negatives, min -0.579)
  (14736746, 1 negative,  min -0.017)
  ```

  Both plot files were touched by 9256bef and 5fe3141; neither change altered the clamp or the break,
  which I confirmed by reading the diff.
- **How to reproduce**:
  ```
  python -c "import json; d=json.load(open('apps/web/public/data/cards.json')); \
    print([(c['obs_id'], min(c['geometry']['elevation_deg'])) for c in d['cards'] \
           if c.get('geometry') and not c['geometry'].get('degraded') \
           and min(c['geometry']['elevation_deg'])<0])"
  ```
  then open `/observation/14742034/` and compare the sky track's gap against the elevation panel.
- **Suggested fix**: move the policy into the projection so all three consumers inherit it. Return
  `null` from `projectSky` below the horizon and make each caller handle it: the sky plot breaks the
  run as it already does, the replay hides the cursor for that instant instead of moving it, and the
  time series breaks its polyline the same way. Add a test that one negative sample produces a gap in
  all three.

### [SERIOUS] The claim-drift test asserts the metric name, not its value, and the generator is ungated

- **Where**: `tests/test_claim_drift.py:44`, and `scripts/sync_readme_results.py`
- **What is wrong**: this is separate from the declared `xfail`. The test that does run,
  `test_readme_has_no_unbacked_numbers`, ends at `assert cells[0] in registered`, which checks only
  that the metric's name appears somewhere in `docs/CLAIM_REGISTER.md`. The value is parsed into
  `value` on line 41 and then never compared to anything. So any published number in the README
  results table can be changed to any other number and the test passes, as long as the row label is
  untouched. The file's own docstring claims the opposite: "the value quoted in README.md must equal
  the value in the artifact the row points at" and "When a model improves and the README is updated by
  hand but the artifact is not regenerated, this test is what catches it." It does not catch it.
  The second half compounds it: `scripts/sync_readme_results.py` generates that table, has no
  `--check` mode (no `add_argument` anywhere, `main()` takes no argv), and is referenced by nothing
  except a prompt document. It is not run by `scripts/gate.py`, not run by CI, and not asserted by any
  test, so the generated table stays correct only for as long as someone remembers to run the script.
- **How I know**: I changed one row of the README from the receipt's real value to a fabricated one,
  ran the drift test, then ran the whole suite, then reverted.

  ```
  mutated AUC 0.875 -> 0.999 and 0.842 -> 0.111
  tests/test_claim_drift.py: .x                                    [100%]
  full suite: 744 passed, 1 xfailed, 5 warnings in 158.00s
  ```

  The `.` is `test_readme_has_no_unbacked_numbers` passing on the fabricated figure and the `x` is the
  known D2 placeholder. The whole suite is blind to it. And:
  `git grep -nI "sync_readme_results"` returns only the script's own usage line and one mention in
  the Wave D build prompt, which is kept outside this repository because its test   counts are frozen at the day it was written and the tree has passed them.
- **How to reproduce**:
  ```
  python - <<'PY'
  import io
  p='README.md'; s=io.open(p,encoding='utf-8').read()
  io.open(p,'w',encoding='utf-8',newline='').write(
      s.replace('| AUC, chronological holdout | 0.875, against 0.842 image-only |',
                '| AUC, chronological holdout | 0.999, against 0.111 image-only |',1))
  PY
  .venv/Scripts/python.exe -m pytest -q      # 744 passed, 1 xfailed
  git checkout -- README.md
  ```
- **Suggested fix**: two changes, neither of which needs D2. Give
  `sync_readme_results.py` a `--check` flag that regenerates into memory, compares against the file
  and exits non-zero on a difference, then add it to `scripts/gate.py` and to CI beside the lint step.
  That closes the hole mechanically and independently of the value-comparison work. Separately,
  correct the docstring of `test_readme_has_no_unbacked_numbers` so it describes the presence check it
  performs rather than the value check it does not, because a test whose docstring overstates it is
  worse than an absent test: it is why nobody looked here.

### [SERIOUS] The replay readout is a live region mutated up to sixty times a second

- **Where**: `apps/web/components/PassReplay.tsx:347`
- **What is wrong**: `<dl className="replay-readout" aria-live="polite">` wraps seven `<dd>` nodes
  written by `textContent` inside the animation-frame loop. The comment says polite was chosen because
  assertive "would interrupt on every frame of playback", which addresses interruption and not volume.
  `REPLAY_MS` is 12,000, so one press queues on the order of 700 mutation batches across seven nodes.
  The `write` helper suppresses identical text, which trims the elapsed field slightly and does nothing
  for elevation, azimuth, Doppler, range or the subpoint, all of which change every frame.
- **How I know**: read from the source. `REPLAY_MS = 12_000` at line 94, `paint` writes all seven keys
  at lines 236-252, and `step` calls `paint` then re-requests a frame at lines 285-297. I did not
  measure a screen reader, so the consequence is reasoned from the code and the specification rather
  than observed; see Limits.
- **How to reproduce**: read `paint` and `step`, then count the `write` calls per invocation. For an
  observed result, load `/observation/14746092/` with a screen reader running and press Replay.
- **Suggested fix**: keep the region announced for deliberate reads and silent during playback:
  `aria-live={playing ? "off" : "polite"}` with `aria-atomic="true"`, and call `paint` once more after
  `setPlaying(false)` so the final state is announced. Keyboard scrubbing produces one event per key,
  which polite handles correctly; throttle the drag case to about 200 ms.

### [SERIOUS] A released WebGL context cannot be re-acquired, so any effect re-run is permanent fallback

- **Where**: `apps/web/components/WaterfallCanvas.tsx:399`, with the dependency list at line 404
- **What is wrong**: cleanup calls `gl.getExtension("WEBGL_lose_context")?.loseContext()`. When the
  init effect re-runs with the same canvas still mounted, the previous cleanup runs first, so
  `canvas.getContext("webgl2", ...)` is called on a canvas whose context was force-lost. That returns
  the cached, still-lost context, because nothing calls `restoreContext`, so `compile` returns null
  and the component lands in the shader-compile failure branch permanently, showing the plain image and
  hiding the controls. Two ways in: `next.config.mjs:23` sets `reactStrictMode: true`, so in the dev
  server every effect is mounted, cleaned up and mounted again, which means the shader path is dead in
  development and a developer reading this file would conclude the opposite; and any change to `src`
  on a mounted instance, which is not reachable from the current call site and is one prop rename away.
- **How I know**: read from the source, against the specified behaviour that a force-lost context stays
  lost until restored and that `getContext` returns the existing context for a canvas. The production
  build is unaffected, which is why `npx next build` and the deployed site both work. I did not
  instrument a browser, so this is reasoned rather than observed; see Limits.
- **How to reproduce**: `cd apps/web && npx next dev`, open any observation page, and confirm the
  contrast controls are absent and the fallback note is shown. Compare against the same page in
  `npx next build && npx next start`.
- **Suggested fix**: separate acquisition from release. Acquire once per canvas and keep it in the ref
  across effect runs; in the per-`src` cleanup delete the texture, buffer, vertex array and program but
  do not lose the context; call `loseContext` only from a `useEffect(() => () => ..., [])` that runs on
  true unmount. Note also that the `event.preventDefault()` on `webglcontextlost` at line 382 is what
  asks for a restore event that nothing listens for.

### [SERIOUS] `test_set_untouched` publishes a hardcoded pass whose `n_examined` measures something else

- **Where**: `pipeline/tracetriage/splits.py:1110-1123` and `1339-1360`
- **What is wrong**: `passed` and `n_violators` are constants, and `n_examined` is
  `sum(len(ids["test"]) for ...)`, which is 1,349, the number of emitted test ids across the four
  splits. Counting emitted ids says nothing about whether the test set was touched. Both gates the
  module relies on pass on this row: `reject_vacuous_checks` is satisfied by an `n_examined` that
  measures a different property, and `split_manifest.schema.json` pins `passed` to `const: true`, so a
  false is not representable. Anyone tallying six of six leakage checks from `LEAKAGE_AUDIT.json`
  counts one row that measured nothing about its own claim. The `rationale` string is honest about this
  and the per-split test digests are the real mechanism, which is good design; the problem is the
  tally, not the intent.
- **How I know**: read the two code paths, then read the artifact:
  `test_set_untouched all PASS 1349 0`, against the test partition sizes 410 + 403 + 353 + 183 = 1349
  from `SPLIT_MANIFEST.json`.
- **How to reproduce**:
  ```
  python -c "import json; a=json.load(open('artifacts/LEAKAGE_AUDIT.json')); \
    r=[x for x in a if x['check']=='test_set_untouched'][0]; \
    print(r['result'], r['n_examined'], r['n_violators'])"
  ```
- **Suggested fix**: `build_leakage_audit` already solved this shape once by introducing `BY_DESIGN` as
  a third outcome that carries a measured number. Do the same here: give the row a distinct result such
  as `ASSERTED_NOT_MEASURABLE_HERE`, drop the `n_violators: 0`, set `n_examined` to null with a stated
  reason, and add the value to the audit's result vocabulary and to anything that tallies it. Keep the
  digests, which are the part that actually binds a later evaluation.

### [SERIOUS] No mechanical gate covers the console: no type check, no build, no tests at all

- **Where**: `scripts/gate.py`, `.github/workflows/ci.yml`, `apps/web/package.json`
- **What is wrong**: the standing gate runs pytest, ruff, a contract status check, a clean-tree check,
  a gate 6 verdict check, a secret grep, a build-log check and a commit-identity check. CI runs the
  same test suite plus a secret scan, with `mypy pipeline` marked `continue-on-error: true`. Neither
  runs `tsc --noEmit`, neither runs `next build`, and `apps/web` has no test framework: `package.json`
  declares `dev`, `build`, `start`, `lint` and `typecheck`, and no `test`. Five of the last five
  commits touch the console. It is green today, which I verified, and nothing in the repository would
  notice if it stopped being green. The evaluation page does real work at module scope
  (`app/evaluation/page.tsx:33`, `55-58`, `259-264`), all of which runs during the export and would
  fail the build rather than degrade.
- **How I know**: read both files, and `git grep -nI "tsc\|next build" .github scripts` returns
  nothing. `ls apps/web` shows no vitest, jest or playwright configuration.
- **How to reproduce**: `grep -n "run:" .github/workflows/ci.yml` and
  `python -c "import json;print(json.load(open('apps/web/package.json'))['scripts'])"`.
- **Suggested fix**: add a console job to CI running `npm ci`, `npm run typecheck` and `npm run build`,
  and add both to `scripts/gate.py` beside the existing lint step.

### [SERIOUS] Every pure function in the console is untested

- **Where**: `apps/web/lib/projection.ts` and the pure helpers in the plot components
- **What is wrong**: nothing anywhere exercises `unwrapLongitudes`, `horizonCircle`, `groundBounds`,
  `stationLonInFrame`, `projectSky`, `projectGround`, `niceStep`, `sampleAt`, `timeSeriesCursorX`,
  `pathFrom`, `niceCeil` or `boundsForPass`. These are where the degenerate cases live, and several are
  one input away from a wrong picture (the three MINOR items below on the pole seam, the `L`-first
  path, and the shortening unwrap). The functions are pure and import nothing by design, which the
  module docstring calls out, so they are unusually cheap to test.
- **How I know**: `git grep -nI "projectSky\|unwrapLongitudes\|horizonCircle\|groundBounds" tests/`
  returns nothing, and there is no JavaScript test runner in the repository.
- **How to reproduce**: `git grep -lI "projection" tests/ ; ls apps/web/*.config.* apps/web/*test*`.
- **Suggested fix**: add a test runner and cover, at minimum, a single-sample series, an all-equal
  series, a pass crossing the antimeridian, a station at a pole (both the `east_norm < 1e-12` branch in
  `pass_geometry` and `stationLonInFrame` across a frame that straddles 180), a zero-length pass, a
  horizon circle that encloses a pole, and a negative-elevation sample through all three consumers.

### [SERIOUS] `_require` is tested in isolation, never at its call sites

- **Where**: `tests/test_console_export.py:52-86`
- **What is wrong**: five tests cover the helper with a present value, a missing key, a null, three
  empty containers, and a legitimate zero and false. They are correct and they pass. None touches
  `export_observation`, `build_pass_geometry`, `build_gate_summary`, `trim_queue_entry` or the
  `fusion_splits` comprehension, which is where the same defect class survives. The file's docstring
  describes the original bug precisely, and the tests pin the fix to the helper rather than to the
  behaviour, so the two live instances of that bug pass the suite.
- **How I know**: read the file; the module is loaded only through `_load_export_module()._require`.
- **How to reproduce**: `grep -n "_load_export_module()" tests/test_console_export.py`, and note every
  hit is followed by `._require`.
- **Suggested fix**: assert on the exported artifact rather than the guard. Two tests would have caught
  both blocking defects: one that no card publishes a corridor without a fit, and one that every
  non-degraded fusion split in `evaluation.json` has a non-null value for `counts`, `arms`,
  `comparisons`, `selective` and `test_positive_rate`.

### [SERIOUS] Two type declarations that a cast and three assertions paper over

- **Where**: `apps/web/lib/data.ts:103-130` with `app/observation/[id]/page.tsx:118-120`, and
  `lib/data.ts:254-259` with `app/page.tsx:256-259`
- **What is wrong**: two separate wrong declarations, both hidden from the compiler.
  First, `Card` types `image`, `width` and `height` as optional, and the observation page asserts past
  that with `card.image!`, `card.width!`, `card.height!` after checking `degraded`. The invariant holds
  in the exporter, so this is not live, but the same file already contains the right answer:
  `PassGeometry` at lines 99-101 is a discriminated union written specifically so that reading a field
  without checking `degraded` is a type error, with a docstring saying two absences have already been
  published here as measurements. If the assertion ever becomes wrong, `width!` and `height!` produce
  `aspectRatio: "undefined / undefined"` and `viewBox="0 0 undefined undefined"`, which renders as a
  collapsed box rather than an error.
  Second, `threshold` is declared `string | number` and is an object in every case. The home page
  renders it correctly only by casting past its own type inside a branch the compiler believes is
  unreachable: with `threshold: string | number`, `typeof x === "object"` narrows to `never`, a cast on
  `never` is permitted, and the only branch that ever executes is the one the compiler thinks is dead.
  Anyone acting on an "always false" hint and deleting it makes all three thresholds render as
  `[object Object]`.
- **How I know**: reading the receipt:
  ```
  MODEL_LABEL_DISAGREE -> dict {'prob_positive_floor': 0.75, 'prob_negative_ceiling': 0.25}
  STALE_CATALOGUE_FREQ -> dict {'abs_offset_ppm_min': 20.0}
  DEAD_CAPTURE         -> dict {'flat_row_frac_min': 0.15}
  ```
  and `npx tsc --noEmit` exits 0 with both in place.
- **How to reproduce**:
  ```
  python -c "import json; q=json.load(open('artifacts/QUEUE_RECEIPT.json')); \
    print([(c['reason_code'], type(c['threshold']).__name__) \
           for c in q['conflict_definition']['criteria']])"
  ```
- **Suggested fix**: give `Card` the same union treatment `PassGeometry` has, which deletes the three
  assertions; and correct `threshold` to `string | number | Record<string, number>`, which turns the
  runtime `typeof` guard into a real narrowing and lets the cast go.

### [MINOR] The new elapsed overlay reveals every subpath at once when the sky track has a gap

- **Where**: `apps/web/components/SkyPlot.tsx:184` and `apps/web/components/PassReplay.tsx:156-166`,
  `229-236`
- **What is wrong**: the trail is `<path d={path}>` where `path` comes from `polyline`, which emits one
  `M ... L ...` run per above-horizon segment joined by spaces, so it is a multi-subpath path whenever
  the track breaks. The replay sets `strokeDasharray` to `getTotalLength()` and animates
  `strokeDashoffset` from that length to zero. A dash pattern restarts at the start of each subpath, so
  with two or more subpaths every segment receives the same dash phase and they reveal simultaneously
  rather than in time order, while the offset is computed against the summed length. The overlay would
  then not represent elapsed time. The ground-track trail is a `<polyline>`, which is always one
  subpath, so it is unaffected.
- **How I know**: latent, not live. Replaying the run-splitting logic over all 25 shipped cards, every
  card with negative samples has them contiguous at the ends, so each produces exactly one subpath:
  ```
  obs 14742034: 5 negatives at indices [0, 1, 101, 102, 103] of 104 -> 1 subpath(s) [99]
  obs 14742036: 5 negatives at indices [0, 1, 101, 102, 103] of 104 -> 1 subpath(s) [99]
  obs 14736746: 1 negatives at indices [0] of 104 -> 1 subpath(s) [103]
  ```
  An interior dip below the horizon, which a grazing pass or a different showcase selection produces,
  splits the path and the defect fires. The zero-length guard at line 163 and the sub-unit write
  threshold at line 231 are both correct and I found no fault with either.
- **How to reproduce**: replay the run-splitting from `SkyPlot.polyline` over
  `cards.json`, or construct a card with one interior negative sample and count subpaths in the emitted
  `d`.
- **Suggested fix**: since fixing the S3 inconsistency means deciding the break policy in one place
  anyway, do both together: keep the trail as a single subpath by drawing it per run, one trail element
  per run with its own measured length and its own share of the pass, or accept the gap and set the dash
  phase per subpath from the cumulative length preceding it.

### [MINOR] The horizon circle draws a seam above roughly 66 degrees of latitude

- **Where**: `apps/web/lib/projection.ts:103-132`
- **What is wrong**: the small circle is walked with an `atan2` longitude offset, correct away from the
  poles and discontinuous when the circle encloses one. For a 700 km orbit the half angle is about 24
  degrees, so a closest-approach subpoint above about 66 degrees produces a polygon with a band across
  the plot, the artefact the module docstring says walking the sphere avoids.
- **How I know**: latent. The highest closest-approach sub-latitude among the shipped cards is 64.2
  degrees (observation 14735743) and the highest sub-latitude on any shipped track is 75.8 degrees.
  High-latitude ground stations exist in the source network, so a different selection reaches it.
- **How to reproduce**: call `horizonCircle(80, 0, 700)` and look for a longitude jump near 180 in the
  returned `lon` array.
- **Suggested fix**: detect pole enclosure with `Math.abs(latDeg) + halfAngleDeg > 90` and either clip
  to the plot's latitude edge or withhold the circle with a stated reason.

### [MINOR] `pathFrom` can emit a path that begins with a lineto

- **Where**: `apps/web/components/WaterfallViewer.tsx:46-55`
- **What is wrong**: the command is chosen by loop index, `i === 0 ? "M" : "L"`, while an undefined
  entry is skipped with `continue`. If element 0 were skipped the path would start with `L`, which is
  an error in the path grammar and renders nothing at all, so the guard that exists to satisfy
  `noUncheckedIndexedAccess` would be wrong in the one case it fires.
- **How I know**: read from the source. Not reachable: the exporter always emits `rows` and
  `fitted_px` at equal length with no holes.
- **How to reproduce**: call `pathFrom([0,1,2], [undefined as any, 5, 6])` and inspect the result.
- **Suggested fix**: track whether a point has been written and emit `M` on the first one.

### [MINOR] `unwrapLongitudes` silently shortens the series

- **Where**: `apps/web/lib/projection.ts:73-74`
- **What is wrong**: an undefined element is skipped, so the output can be shorter than the input.
  `sub_lat_deg` is not filtered the same way, and the replay samples `groundLons` and
  `geometry.sub_lat_deg` at the same `t`, so a single hole would put the cursor off the track.
- **How I know**: read from the source. Not reachable from the exporter.
- **How to reproduce**: `unwrapLongitudes([10, undefined as any, 12]).length` returns 2, not 3.
- **Suggested fix**: iterate by index and either propagate a hole or raise.

### [MINOR] Two definitions of the receive frequency in one script, and a comment that is wrong about it

- **Where**: `scripts/build_console_data.py:158` against line 341, and
  `pipeline/tracetriage/splits.py` `FIELD_CLASSIFICATION["center_frequency"]`
- **What is wrong**: line 158 uses `record.get("center_frequency") or
  record.get("observation_frequency")` and publishes the result as `rx_freq_hz`, rendered as "Receive
  frequency"; line 341 uses `rx_freq_of(record)`, which prefers
  `client_metadata.radio.parameters.rx-freq`, for the Doppler curve. Separately, the classification
  entry describes `center_frequency` as "Null in this snapshot" and 7 records carry a value.
- **How I know**: I compared both derivations across every snapshot record:
  ```
  0 of 25 shipped cards publish an rx_freq_hz different from rx_freq_of()
  0 of 2750 snapshot records would publish a mismatched rx_freq_hz
  center_frequency non-null count: 7
  ```
  So no page currently states a frequency the physics did not use, and the value reaches
  `parse_waterfall` only as a presence test (`waterfall.py:794`) rather than as a scale, so the derived
  axis is unaffected. The divergence is waiting rather than active, and the comment is already wrong.
- **How to reproduce**: the loop above over `_load_raw_pages(_PAGES_DIR)`, comparing
  `r.get("center_frequency") or r.get("observation_frequency")` against `rx_freq_of(r)`.
- **Suggested fix**: call `rx_freq_of` on line 158, and correct the classification description.

### [MINOR] `rx_freq_of` treats a zero frequency as absent

- **Where**: `pipeline/tracetriage/physics.py:309` and `314`
- **What is wrong**: `if v:` and `return float(v) if v else None`. A recorded `rx-freq` of `"0"`
  becomes `None` and the observation is reported `MISSING_FREQ`, which is a different fact from a
  nonsense value.
- **How I know**: read from the source.
- **How to reproduce**: `rx_freq_of({"client_metadata": '{"radio":{"parameters":{"rx-freq":"0"}}}'})`
  returns `None`.
- **Suggested fix**: test `is not None` and check positivity separately, with distinct reason codes.

### [MINOR] The pass summary and the plotted markers use different sample resolutions

- **Where**: `scripts/build_console_data.py:329` and `350`, against `SkyPlot.tsx:88-95`,
  `GroundTrack.tsx:61-66`, `PassTimeSeries.tsx:124-129` and `app/observation/[id]/page.tsx:168-172`
- **What is wrong**: the export computes `max_elevation_deg`, `tca_frac` and `tca_azimuth_deg` from all
  512 propagated samples and then subsamples the series to about 90 points. Each plot deliberately
  recomputes the peak from the subsampled series so the marker sits on the drawn track, and the page
  caption takes the altitude at a third index. The label and table therefore state the full-resolution
  peak while the marker sits at the subsampled one.
- **How I know**: read the export and the three components; the exported series are 104 points long
  where `n_samples_propagated` is 512.
- **How to reproduce**: compare `geometry.max_elevation_deg` against
  `max(geometry.elevation_deg)` for any card in `cards.json`.
- **Suggested fix**: export the subsampled peak alongside the full-resolution one and name which is
  which, or subsample so the peak sample is always retained.

### [MINOR] Dead failure-state code on the observation page

- **Where**: `apps/web/app/observation/[id]/page.tsx:51-64`
- **What is wrong**: under a static export, `generateStaticParams` returns `showcaseIds`, which
  `lib/data.ts:451-458` has already filtered to cards without a `degraded` reason, so neither the
  "not in the shipped set" branch nor the `card.degraded` note can be reached. An unlisted id is a host
  404 instead.
- **How I know**: read both files, and the build emits 25 observation routes matching `showcaseIds`.
- **How to reproduce**: `ls apps/web/out/observation` and compare against
  `python -c "import json;d=json.load(open('apps/web/public/data/cards.json'));print(len(d['cards']))"`.
- **Suggested fix**: either route to it deliberately or delete it and rely on the not-found page.

### [MINOR] `scripts/gate.py` gaps

- **Where**: `scripts/gate.py:53-62`, `87-89`, `93`
- **What is wrong**: line 93 reads `docs/BOB_BUILD_LOG.md` unguarded, so a missing file crashes the
  gate instead of reporting a failure. The secret pattern covers repository tokens and private key
  headers only, and `git grep` searches the working tree rather than history, so a secret committed and
  later removed is invisible. The contract check verifies only that `status` does not begin with
  `DRAFT`; it checks neither root closure nor a version pin, which is how the contract finding above
  survived.
- **How I know**: read the file. Its own pattern is the only match in the tracked tree, which is a
  self-match on the detector.
- **How to reproduce**: `.venv/Scripts/python.exe scripts/gate.py` and read the printed checks.
- **Suggested fix**: guard the read, and add closure and version-pin assertions to the contract check,
  since this gate stands in for a self-report.

### [MINOR] A bare non-null assertion where the file's own helper exists

- **Where**: `apps/web/app/evaluation/page.tsx:33`
- **What is wrong**: `evaluation.fusion_splits.find((s) => s.split === "chronological")!` at module
  scope. `lib/data.ts` provides `requireGate6Split` and `requireQueueSplit`, both of which throw an
  error naming what the receipt does carry. A renamed split here produces a property-of-undefined
  error from line 259 instead.
- **How I know**: read both files.
- **How to reproduce**: `grep -n "find((s) => s.split" apps/web/app/evaluation/page.tsx`.
- **Suggested fix**: add `requireFusionSplit(name)` beside the other two and use it.

### [MINOR] The three evidence links download a file rather than opening a document

- **Where**: `apps/web/components/Colophon.tsx:86-90`, `apps/web/app/provenance/page.tsx:239-257`,
  `apps/web/vercel.json`
- **What is wrong**: the three documents are served as `text/markdown` with `nosniff`, which the most
  common browser does not render, so following the footer's "Gates" link downloads a 34 kB file. One
  other browser family renders it as plain text, so the behaviour differs for the links a judge is most
  likely to follow.
- **How I know**: `curl -I` against the deployed console:
  ```
  HTTP/1.1 200 OK
  Content-Disposition: inline; filename="KILL_GATE.md"
  Content-Type: text/markdown; charset=utf-8
  X-Content-Type-Options: nosniff
  ```
- **How to reproduce**: `curl -sS -I https://tracetriage.vercel.app/data/KILL_GATE.md`
- **Suggested fix**: add a header rule setting `Content-Type: text/plain; charset=utf-8` on
  `/data/(.*).md`, or render the three documents as pages. While in that file, note that
  `public/data/cards.json` (614 kB), `queue.json` (188 kB) and `evaluation.json` (215 kB) are served
  publicly and referenced by no page, since the console imports them at build time: about 1.0 MB of the
  deploy that nothing requests.

### [MINOR] `preventDefault` on context loss with no restore path

- **Where**: `apps/web/components/WaterfallCanvas.tsx:382`
- **What is wrong**: `preventDefault` on `webglcontextlost` is what asks the browser to fire
  `webglcontextrestored`, and nothing listens for it, so the call suggests a recovery path that does
  not exist.
- **How I know**: read from the source; there is no `webglcontextrestored` listener in the file.
- **How to reproduce**: `grep -n "webglcontext" apps/web/components/WaterfallCanvas.tsx`.
- **Suggested fix**: add the listener or drop the call and keep the documented image fallback.

### [MINOR] Degenerate Doppler axis labels

- **Where**: `apps/web/components/PassTimeSeries.tsx:205`
- **What is wrong**: the axis is formatted as `${Math.abs(hz) / 1000}k`, which reads `+0.001k` when
  `niceCeil` floors the range at 1 for an all-zero Doppler series, and `+0.2k` for a 200 Hz range.
- **How I know**: read from the source, following `niceCeil` at lines 70-77 for a zero input.
- **How to reproduce**: render `PassTimeSeries` with `doppler_hz` all zeros.
- **Suggested fix**: choose the unit from the magnitude.

## Checked and found correct

- **The test suite is green and the count matches.** `.venv/Scripts/python.exe -m pytest`:
  `744 passed, 1 xfailed, 5 warnings in 158.00s`. The `xfail` is the declared D2 placeholder.
- **The console type-checks and builds.** `npx tsc --noEmit -p tsconfig.json` exits 0 with no
  diagnostics under `strict` and `noUncheckedIndexedAccess`. `npx next build` exits 0, emits 33 pages
  and reports 102 kB shared first-load JavaScript.
- **No receipt JSON crosses the client boundary.** The six client modules are Nav, Rail, QueueTable,
  WaterfallCanvas, WaterfallViewer and PassReplay. None imports `lib/data` as a value:
  `WaterfallViewer.tsx:30` uses `import type`, which is erased, and the labels and formatters live in
  `lib/queue-view.ts` and `lib/format.ts`, which import nothing. `PassTimeSeries` enters the client
  graph through the value import of `timeSeriesCursorX` and imports only a React type. Grepping
  `out/_next/static/` for "unweighted mean of the R, G and B", "episode_key" and "n_boot_effective"
  returns nothing. The 306 kB regression the two module docstrings describe is fixed structurally.
- **The JSON export is byte-for-byte reproducible.** Re-running `main(["--skip-images"])` against a
  scratch directory produced `queue.json`, `evaluation.json` and `provenance.json` with SHA-256 digests
  identical to the committed files.
- **Determinism holds where it matters.** `run_queue.py:440` and `473` sort with `obs_id` as an explicit
  tiebreak, `run_fusion.py:736-737` sorts before seeding the generator it shuffles with, estimators
  receive `random_state=seed`, and both scripts validate against their contract before the write
  (`run_queue.py:937` then `940`; `run_fusion.py:684` then `685`).
- **All four receipts validate against their contracts today**, and the queue receipt is the model the
  others should follow: closed root, `schema` and `schema_version` both pinned, `deduplication.key`
  pinned by value, and `tests/test_console_export.py:132-149` proving both pins bite by mutation.
- **The fusion contract's conditional requirement works.** `$defs/split_result.allOf[0]` requires `arms`
  and `comparisons` when `degraded` is null, and my attempt to rename `arms` was rejected with
  `'arms' is a required property`. `allOf[1]` requires `note` when `degraded` is a string.
- **`_require` itself is correct**, including the part that is easy to get wrong: zero and `False` pass,
  and only `None` or an empty list, dict or string fail.
- **`build_gate_summary` cannot silently miscount.** An unrecognised verdict raises rather than being
  counted as not met, and the met set deliberately excludes `NOT_ESTABLISHED` and `OPEN` with the
  reason stated in the emitted note. The tally is derived, not typed.
- **`.gitignore` negations are all live.** `artifacts/**/*` is followed by `!artifacts/**/` before any
  file negation, with a comment naming the trap. `git check-ignore -v` on
  `artifacts/a3_overlays/summary.json`, `artifacts/QUEUE_RECEIPT.json`,
  `apps/web/public/waterfalls/14732518.webp`, `docs/BOB_BUILD_LOG.md` and
  `tests/fixtures/waterfall_836px_client_v2.3.png` reports nothing, so none is ignored.
- **No secret and no build artefact is tracked.** The only environment file is `.env.example`, which
  holds a contact address, a user agent, a delay and two paths. Scanning the tracked tree for
  repository tokens, model-provider keys, cloud access key ids, private key headers and chat tokens
  matches only `scripts/gate.py`, which contains the detector pattern. `.next/`, `apps/web/out/` and
  `node_modules/` are all ignored and absent from `git ls-files`.
- **The budget document rename left no stale path.** `git grep -nI "BOBCOIN"` returns two hits, both in
  `docs/BOB_BUILD_LOG.md`, and both are that log narrating the rename itself rather than pointing at a
  file. Nothing references the old path as a location.
- **The third-party font split is real and the disclosure is accurate.** `--font-mono` and
  `--font-sans` resolve to the self-hosted faces, and every selector carrying a value uses the mono:
  `.num` and `.plot-label` are both `var(--font-mono)`. All seven users of `var(--font-label)` are
  label or heading text (`.rail-status dt`, `.lede-kicker`, `.instrument-title`, `.colophon h2`,
  `.replay-scrub`, `.replay-readout dt`, `.plot-cardinal`), and in the readout the `dt` takes the
  licensed face while the `dd` carrying the number takes the mono. So "every digit of every measurement
  is set in IBM Plex from this origin" holds as written. The policy in `vercel.json` names both hosts,
  `use.typekit.net` under `style-src` and `font-src` and `p.typekit.net` under `style-src`, which is the
  right directive for a stylesheet `@import`, so the counter is permitted rather than blocked and the
  claim that both hosts are declared checks out.
- **All three header rules are live on the deployed console**, so the root directory is configured
  correctly. `curl -I` returns the full policy plus `Permissions-Policy`, `Referrer-Policy:
  no-referrer`, `Strict-Transport-Security: max-age=63072000; includeSubDomains` and `nosniff`, and
  `/waterfalls/14732518.webp` returns `Cache-Control: public, max-age=31536000, immutable`. The one
  substantive weakness is `script-src 'self' 'unsafe-inline'`, which the static export's inline
  bootstrap requires.
- **The markdown documents are plain anchors, not runtime fetches**, so the claim that nothing is
  fetched at runtime holds. `git grep -n "fetch(" apps/web/app apps/web/components apps/web/lib`
  returns nothing.
- **The physics geometry is right where it is easy to be wrong.** The semi-major axis is in kilometres
  and every consumer agrees, so the pole branch of `ecef_to_geodetic` and `pass_geometry`'s altitude
  series are consistent. `station_ecef` uses the correct `(N(1-e2) + h)sin(lat)` form. `geodetic_normal`
  is the surface normal rather than the position vector, both propagation loops normalise the local
  vertical defensively, and the polar degeneracy in the east vector is handled explicitly.
  `tests/test_physics.py:799-951` asserts that `pass_geometry` and `propagate_pass` agree sample for
  sample, round-trips the geodetic conversion at 1e-6, and includes a test that fails if the function
  returns the geocentric latitude it starts from. The five iterations are justified with measured
  residuals rather than a round number.
- **`corridor_columns` cannot divide by a null scale.** `parse_waterfall` returns a non-degraded record
  only through one path, where `hz_per_px` is a real float, so the half-width division in the export is
  safe. `centre_px` can be null independently and is checked first. The interpolation receives an
  increasing sample vector.
- **The leakage audit design is better than what it replaced.** Every check runs on every split, the
  by-design rows carry their measured crossing counts (211, 213, 159 and 82) rather than a sentence,
  `entity_spread` reports excluded and no-key skips separately instead of folding either into a pass,
  and the manifest's top-level `n_examined` is the minimum over the guaranteed splits with the per-split
  breakdown preserved. The revolution and duplicate-image checks pass on all four splits with real
  examination counts. Only the `test_set_untouched` row does not earn its pass.
- **The field classification is exhaustive by construction** and the build refuses to freeze on an
  unclassified field. The six fields its docstring says an earlier hand-written list missed are all
  present and all classified as post-observation, with the decoded-frame field correctly identified as
  the most dangerous.
- **`sampleAt` handles the degenerate lengths**, returning `NaN` for an empty series and the single
  value for a one-element series, and every caller checks finiteness before writing a transform.
- **`groundBounds` cannot divide by zero.** Padding of at least 1 on each side before the latitude clamp
  keeps both denominators at least 1 for any input, including an all-equal series and a station at a
  pole.
- **The `PassGeometry` discriminated union is the right shape** and the narrowing works: the observation
  page cannot read a track field without checking `degraded === null` first, and the degraded branch
  renders the stated reason rather than nothing.
- **The canvas render path is careful.** `render` reads uniforms from a ref and is stable, the frame
  request coalesces to one draw, and `onFallback={setFallbackReason}` is a state setter, so the init
  effect does not rebuild the context when a slider moves. Premultiply and colour conversion are both
  switched off before upload, single-channel immutable storage is used, and there is no pixel readback
  anywhere. The intersection gate and the device-ratio cap are both sound.
- **The replay clock does not leak.** The playing effect cancels its frame in cleanup and nulls the ref,
  the start marker is re-seeded from the current position so a re-run resumes rather than restarting,
  the reduced-motion listener is removed, and the ready flag is deleted on unmount. The four element
  lookups are unique per page: the observation page renders one of each plot and the replay page renders
  none of them, so there is no id collision and no cross-page contamination.
- **The new trail overlay guards its own degenerate cases.** A zero or non-finite path length is
  skipped rather than producing `NaN` offsets, the length is measured once at mount rather than per
  frame, and the sub-unit write threshold is the right idea for avoiding a raster on a move nobody can
  see.

## Limits of this review

- **Two SERIOUS findings are reasoned from source and specification rather than observed in a browser.**
  The live-region volume finding counts writes per frame in the code; I did not run a screen reader, so
  the practical severity across assistive technologies is inferred. The context re-acquisition finding
  follows from the specified behaviour of a force-lost context and of `getContext`; I did not
  instrument the development server to watch the fallback appear. Both are cheap to confirm and the
  reproduction steps are given.
- **I did not audit the modelling code.** `pipeline/tracetriage/fusion.py`, `baseline.py`,
  `corridor_fit.py`, `selective.py`, `ood.py`, `queue.py`, `snapshot.py`, `annotate.py` and
  `provenance.py` were read only where the data path or a receipt field led into them. The statistical
  claims themselves, the bootstrap constructions, the calibrator choice and the concentration caps were
  out of scope here and are not covered by anything above.
- **I did not run the tests the standing gate deselects.** The `network` and `ocr` markers were not
  exercised, so anything that only fails with the live source API or with the character-recognition
  backend is unverified.
- **The rendered output was not compared against the measurement.** I verified that the export writes
  the pipeline's own path coordinates and that the overlay geometry is drawn from them, but I did not
  screenshot a waterfall and check that the corridor lands on the visible trace. A pixel-level check of
  the corridor against the image is the one verification that would close the loop on the project's
  central claim, and it is not in this review.
- **Gate 4 is open by declaration.** The blinded human study was never run, which the console records
  honestly. Nothing here evaluates it.
- **The deployed console was checked only at the header level.** I read response headers for five URLs.
  I did not audit the deployed pages for runtime errors, did not run a performance trace, and did not
  verify the measured font byte counts on the provenance page.
- **The repository moved during the review.** Analysis began at 7fbb980; four commits landed before
  this was written, touching the two plot components, the replay, the layout, the policy file, the
  stylesheet and the documents. Every finding above was re-verified against 9256bef, and the one new
  component the commits introduced is covered in the first MINOR item. Anything committed after
  9256bef is unreviewed.
