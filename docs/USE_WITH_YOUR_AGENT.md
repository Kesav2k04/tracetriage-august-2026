# Use TraceTriage with your own agent

TraceTriage measures how far a recorded radio trace sits from where the satellite's own
orbit says it should be, and scores that against nulls built from the same pass. This page
is how you point it at your own observations, from your own agent, in about a minute.

Everything here reads public data. No account, no API key, no credential of any kind: the
SatNOGS read API is open, this project holds no token, and nothing in it can write to
SatNOGS even if you asked it to.

## In IBM Bob, which is what this project was built with

Clone it, open the folder in Bob, and paste the prompt in `docs/BOB_DEMO.md`. Nothing else.
`.bob/mcp.json` registers both servers and pre-approves the read-only tools, so a session
can rank the queue, refuse an invented downlink frequency, measure a pass recorded in the
last hour and refuse a sentence about that measurement too.

That file is the one to copy. The root `.mcp.json` is the same two servers in the generic
shape a stdio MCP client reads, and Bob never loads it: a judge who follows the wrong file
gets a project that looks like it has no tools.

| Client | File it reads |
|---|---|
| IBM Bob | `.bob/mcp.json` |
| Any other MCP client over stdio | `.mcp.json` |
| LangFlow | `flows/tracetriage_grounding.json`, `flows/tracetriage_granite_agent.json` |

This table had a fourth row until 2026-08-22, reading `watsonx Orchestrate` against
`orchestrate/toolkits/*.yaml`. **No such directory has ever existed in this repository.** It
is removed rather than built, because a document written for a judge that points at an
absent path is the one defect that makes every other path in it worth doubting, and this
project's whole argument is that its claims can be opened. What watsonx actually is here
is one text-generation backend with a runner and a dated receipt:
`scripts/run_watsonx_check.py`.

## The one-minute version

```bash
git clone https://github.com/Kesav2k04/tracetriage-august-2026
cd tracetriage-august-2026
pip install -e .
tracetriage triage 14740031
```

Not on PyPI, so `pip install tracetriage` will not find it. Four lines rather than two, and
the clone is worth having anyway: the offline server answers from the receipts inside it.

```
observation 14740031  0 OBJECT E  station 91 (M0EYT / 2E0NOG)  2026-08-09T23:50:08Z
  mode      UNCORRECTED: energy follows the predicted Doppler curve: 25.1 sigma against 2.8 for the best vertical line
  offset    13,985 Hz  (32.05 ppm of 436,400,000 Hz)
  evidence  p = 0.0050 over 200 own-Doppler nulls  (true 2.02 sigma against a null max of 0.57)
  support   32 of 1532 rows above the detection floor (2.1%), flagged TRACE_NOT_MEASURABLE
  axis      123.76 Hz/px from glyph_templates at 0.94 confidence
  source    https://s3.eu-central-1.wasabisys.com/.../waterfall_14740031_2026-08-09T23-50-08.png
            sha256 e496d34e0021e6d7306ffc9602f062a56a8403feed58b0ae866be7c5825ae0cd
```

Add `--json` for the whole record, which is what an agent should read.

## Two servers, and which one you want

| Server | What it answers from | Needs |
|---|---|---|
| `tracetriage-live` | the public SatNOGS API, now | this package and a network |
| `tracetriage` | committed receipts in a clone | a `git clone` of this repository |

They are separate on purpose. The offline server advertises five properties and each one is
a test in `tests/test_mcp_server.py`: read-only, offline, no invented numbers, every error a
named reason, bounded output. "Offline" is checked by parsing that file's imports and
refusing `httpx`. Putting a network tool in it would not weaken that claim by degrees, it
would delete it. So the boundary lives in your config, where you can see it: register the
live server and you get measurements taken now, register the other and you get numbers that
were scored against a frozen corpus, and no tool call can confuse the two.

The live tools are prefixed `live_` for the same reason.

### Any MCP client that speaks stdio

Both servers go in one config. This is `.mcp.json` at the root of your project, and the
same block works wherever your client keeps its server list:

```json
{
  "mcpServers": {
    "tracetriage-live": {
      "command": "tracetriage",
      "args": ["mcp-live"]
    },
    "tracetriage": {
      "command": "tracetriage",
      "args": ["mcp", "--repo", "/path/to/tracetriage-august-2026"]
    }
  }
}
```

If `tracetriage` is not on your PATH, use the interpreter that installed it. The module is
`tracetriage.mcp_live` from an install and `pipeline.tracetriage.mcp_live` from a clone of
this repository, because the wheel ships `pipeline/tracetriage` as the top-level package:

```json
{
  "mcpServers": {
    "tracetriage-live": {
      "command": "/full/path/to/python",
      "args": ["-m", "tracetriage.mcp_live"]
    }
  }
}
```

The server reads newline-delimited JSON-RPC 2.0 on stdin and writes it to stdout, with no
SDK dependency: `initialize`, `tools/list`, `tools/call`. You can drive it by hand, which
is the fastest way to check a config problem is yours and not the server's:

```bash
printf '%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | tracetriage mcp-live
```

### OpenAI Agents SDK, LangChain, or your own loop

There is no adapter to install. The CLI is the interface:

```python
import json, subprocess

def triage(observation_id: int) -> dict:
    out = subprocess.run(
        ["tracetriage", "triage", str(observation_id), "--json"],
        capture_output=True, text=True, check=False,
    )
    return json.loads(out.stdout)["measured"][0]
```

Exit codes are meant for this: `0` measured, `1` refused with a reason, `2` usage error,
`3` nothing to measure.

## The tools

### `live_triage_observation(observation_id, n_nulls=99)`

One observation, measured now. Returns `mode`, `measurement`, `nulls`, `second_trace` and
`provenance`.

When `nulls.p_value` is null, read `nulls.not_tested` before reading anything else. It holds one
of five strings and they do not mean the same thing. `flat_corridor` and `swing_below_floor` are
refusals: the first because a Doppler-corrected capture has no curve shape to scramble, the
second because a pass swinging under 3 kHz cannot be told from a permutation of itself. So is
`mode_unresolved`, where the two shapes were never separated and no corridor was selected.
`no_offset_fit` and `no_null_scored` are failures to measure, and nothing in that result is
evidence in either direction. `nulls.reading` says the same thing in a sentence you can quote.

### `live_list_observations(norad_cat_id, ground_station, status, limit)`

Recent observations matching a filter. Metadata only. Nothing here is measured, and
SatNOGS's own `waterfall_status` flag is not a detection: observation 14745984 is flagged
`with-signal` and this project's matched filter puts its best path at 2.5 sigma against an
8 sigma floor.

### `live_rank_observations(norad_cat_id, ground_station, budget=5)`

Measure a handful and rank them: settled first, then by the size of the frequency offset.
This is the triage question, asked of today's captures.

## Reading a result

**`mode` first.** It decides whether anything else means what you think it does.

| Verdict | What it means | What you get |
|---|---|---|
| `UNCORRECTED` | the trace follows the pass's whole Doppler S-curve | an offset and a p-value |
| `CORRECTED` | the station corrected for Doppler, so the trace is a vertical line | an offset, and no p-value |
| `UNRESOLVED` | the image does not settle which | neither, and the two sigmas that say how close it came |

`UNRESOLVED` is the common case and it is not an error. Most observations on a real queue
carry nothing measurable, so the tool returns a value for them rather than raising: a
ranking needs a comparable result for every entry, including the ones worth skipping.

A `CORRECTED` capture gets no p-value and that is not a gap in the implementation. The
corrected corridor is flat, permuting a flat corridor in time leaves it unchanged, so every
null reproduces the hypothesis exactly and the comparison would be vacuous. The offset is
still the useful number, and for a station operator it is arguably the more useful one: it
is the receiver's own frequency error with the orbit already taken out.

**Then `measurement.fit`.** An offset can come with `detect_frac: 0.0` and
`degraded: TRACE_NOT_MEASURABLE`, and that combination is not a contradiction: the null
comparison scores a whole path's mean brightness and never asks any single pixel to clear a
detection floor. It means the offset stands and no residual spread can be measured. Two of
the three uncorrected observations in this project's own gate 3 receipt read exactly that.

**Then `axis.reader`.** Every offset is in Hz because something read the frequency axis off
the image, and this says what: `glyph_templates` for the template matcher, `easyocr` for the
neural reader, `caller_supplied` when you passed labels in. Read it rather than
`axis.derivation`, which has said `axis_ticks_ocr` since before there was a second reader and
keeps that value because frozen comparisons are made against it. A base install has no
easyocr in it, so `glyph_templates` is what a base install reports, and that is the whole
reason 166 MB is enough to answer in Hz.

**Then `provenance`.** Every result carries the API URL, the waterfall's sha256, the two TLE
lines used and the time of measurement, so any number here can be recomputed by someone who
does not believe it.

## What a station operator can actually act on

```bash
tracetriage station 1696 --budget 6
```

```
station 1696: 5 observations measured, 2 decisive        # 2026-08-09
  median offset   -28.26 ppm over 2 distinct satellites [38756, 64534]
  spread          -28.43 to -28.10 ppm  (-28.43, -28.10)
```

Two different satellites, agreeing to a third of a part per million. A receiver's frequency
error is common to everything it hears and an orbit's error is not, so agreement across
distinct satellites is the part that points at the receiver rather than at the orbits. With
one satellite this is not a calibration and the command says so.

**You will not get those numbers.** `station` measures the station's recent queue, so it
measures whatever that station has been hearing lately. The same command eleven days later:

```
station 1696: 6 observations measured, 3 decisive        # 2026-08-20
  median offset   -16.42 ppm over 3 distinct satellites [39440, 59775, 64577]
  spread          -34.48 to +5.37 ppm  (-34.48, -16.42, +5.37)
```

Three satellites this time, spanning 40 ppm and changing sign. Both runs are real and both are
printed here, because the first one on its own would read as the general case when it is one
day's passes. What the agreeing run shows is that this measurement *can* isolate a receiver
error; it does not show that it always does, and a spread this wide is a result rather than a
malfunction. The third confound the command prints is the first thing to suspect: a median
over mixed corrected and uncorrected captures is only sound if the station's own correction is
unbiased, and that is not measured here.

The useful reading of a wide spread is that this station's recent queue does not support a
receiver-error estimate, which is a thing an operator wants told rather than averaged away.

The confounds are printed with the number, every time, and they are real: each offset also
carries that TLE's propagation error, the axis is read from rendered tick labels so every
offset is quantised to whole pixels, and a corrected capture's residual is not the same
quantity as an uncorrected capture's offset.

## In LangChain, without the protocol

Not everything that wants these tools speaks MCP. A LangChain agent wants Python callables
with a JSON schema, so `pipeline/tracetriage/langchain_tools.py` adapts the six read-only
evidence tools into `StructuredTool`s. It is an adapter and not a second implementation:
every tool it returns calls the same function object `scripts/mcp_server.py` registered, and
`tests/test_langchain_tools.py` asserts that on object identity, per tool.

```python
from langchain_ollama import ChatOllama
from pipeline.tracetriage.langchain_tools import tools

agent = ChatOllama(model="granite3.1-dense:8b", temperature=0).bind_tools(tools())
agent.invoke("Which observation is at the top of the review queue, and why?")
```

`pip install -e .[agent]` for the adapter. The chat model is your choice and no part of this
project depends on which one: the same six tools bind to watsonx, to an OpenAI-compatible
endpoint or to anything else LangChain can talk to.

Two things are not offered, and the reason is the same one the auto-approve list in
`.bob/mcp.json` is drawn on. `run_acceptance` runs the repository's gate and writes a build,
which is minutes of CPU. The five `live_*` tools each download a waterfall from a volunteer
network. Both are reachable over MCP, where a human approves the call;
`artifacts/LANGCHAIN_RECEIPT.json` records what was offered, what was withheld and why, and
the fully qualified name of the callable behind each one.

There is no LangFlow graph in this repository. The adapter is what a graph would call, and a
flow file this project has never imported would be a screenshot of an integration rather
than an integration.

## Install sizes, and the one honest limit

| Install | On disk | Can report |
|---|---|---|
| base install | 166 MB | Hz and ppm |
| `pip install 'tracetriage[full]'` | 4,643 MB | the whole reproduction pipeline |

Measured by summing installed files per distribution in this project's own virtualenv. The
base install used to be the second row, because easyocr, torch, torchvision, opencv,
scikit-learn, scikit-image, matplotlib, polars and pyarrow were all base dependencies. Torch
alone is 4,171 MB of that.

Reporting a frequency needs the frequency axis, and the axis is printed on the waterfall as
tick labels. `pipeline/tracetriage/glyph_axis.py` reads them with a template matcher instead
of a neural OCR model, which is what keeps the base install at 166 MB and still able to
answer in Hz. It works because these labels are not photographs of text: a SatNOGS waterfall
is rendered server-side by matplotlib, so every digit comes out as one of a handful of
bitmaps, measured at 10 rows tall across the corpus. Recognising a bitmap that has been seen
before is a dictionary lookup.

Measured over 500 waterfalls drawn at random from the snapshot: an axis is derived on 496 of
them, 99.2 percent, and zero produce a label set that is not an arithmetic progression over
the tick positions. That second number is the one that matters. A missing label costs a tick
and the fit runs on the rest; a wrong label rescales the axis silently. Across 500 images the
failure mode is always the first one.

`pip install 'tracetriage[ocr]'` gets you the neural reader instead, and roughly the full
4.6 GB, because easyocr declares torch, torchvision, opencv and scikit-image as its own
dependencies. You should not need it. Where both readers produce a label set that is a valid
arithmetic progression they derive the same axis; where they differ, the one measured case is
easyocr reading a centre tick as 562 kHz.

## What this will not do

It will not write to SatNOGS. No credential is used, accepted or stored, and no HTTP write
verb is reachable from any code path in this repository.

It will not guess an axis. If the tick labels cannot be read, the answer is `NO_AXIS`, not an
estimate: nothing in an observation's metadata gives frequency per pixel, so a fallback would
be an invented number that looks exactly like a measured one.

It will not tell you a live measurement is one of this project's scored results. The gates
were run against a frozen 2,727-observation snapshot with published receipts. A live
measurement uses the same functions in the same order, and `tests/test_live.py` checks it
reproduces the gate 3 receipt digit for digit on that receipt's own observations, but a
number measured now is a number measured now.

## Licence and courtesy

Observation metadata and waterfall imagery are SatNOGS community data under CC BY-SA 4.0;
see `DATA_LICENSE.md`. The API is run by volunteers. This client sends a User-Agent that
identifies it, sleeps between requests, honours HTTP 429 with backoff, and caps how many
observations one call will measure, and you should not remove any of that.
