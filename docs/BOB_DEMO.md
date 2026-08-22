# Ten minutes in IBM Bob

Clone the repository, open it in Bob, paste the prompt below. **No configuration edit.**
`.bob/mcp.json` registers both servers and pre-approves the tools this session uses, so
nothing here waits on a permission click.

One requirement, and it is the only one: the live server measures rather than reads, so it
needs this project's virtual environment.

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .[ocr]
```

`.bob/run-evidence.cmd` and `.bob/run-live.cmd` are the launchers Bob starts. Each moves to
the repository root itself and picks an interpreter in this order: `TRACETRIAGE_PYTHON` if
set, then `.venv\Scripts\python.exe`, then `py -3`, then `python`. That order exists because
bare `python` on Windows can resolve to the Microsoft Store alias, a stub that exits
immediately, and inside Bob that failure looks like a project whose MCP does not work. If
no interpreter is found the launcher says so on stderr instead of leaving Bob holding a
server that never answers `initialize`.

---

## The prompt

```
You are in the TraceTriage repository. Use MCP tools only. Do not invent numbers.
Quote tool output fields verbatim, and name the tool you got each number from.

1. tools/list on tracetriage-evidence. Name all seven tools.
2. tools/list on tracetriage-live. Confirm live_triage_observation,
   live_check_claim, live_station, live_list_observations,
   live_rank_observations.
3. queue_top limit=5. Report rank 1's obs_id, score, and which reason code
   fired on it.
4. observation on that rank-1 id. Report fitted_offset_hz and network_label.
5. check_claim observation_id=14740031 text="The downlink is 437.2 MHz."
   Expect REFUSED and the code UNGROUNDED_NUMBER. Quote the code.
6. check_claim on the rank-1 id, using its exact fitted_offset_hz from step 4,
   in a sentence of your own. Expect GROUNDED.
7. queue_size. Report available, cap and review_budget.n_observations, and say
   which one is the number of ranked rows.
8. gate_status. Report n_met and the verdicts for gates 4 and 6. Do not
   upgrade a NOT_ESTABLISHED to anything.
9. live_list_observations limit=5 status="good". Pick one id whose
   has_waterfall is true. If none of the five has one, ask again with
   status="bad": that is a real recording the network's vetting did not
   like, which is the kind of pass this queue exists to rank.
10. live_triage_observation on that id, n_nulls=99. Report mode.verdict,
    measurement.offset_ppm, nulls.p_value, provenance.waterfall_sha256 and
    provenance.measured_at_utc. If the verdict is UNRESOLVED, report it as the
    result: it means the image does not settle the Doppler convention, which is
    the common case on a real queue.
11. live_check_claim on that same id, text="The downlink is 437.2 MHz."
    Expect REFUSED and UNGROUNDED_NUMBER, and report whether the measurement
    came from cache or was taken now.
12. Read the resource receipt://GATE6 and quote its verdict.
```

**Step 9 needs `status`, and this document did not say so until 2026-08-21.** Without it
the network answers with the newest observations it holds, and the newest are passes that
have not happened yet: `status: future`, dated days ahead, `has_waterfall: false` on every
one, because a waterfall exists only after a station has recorded something. A session that
followed the earlier wording stopped at step 9 with nothing to measure and no reason why.
Found by `scripts/run_operator_session.py`, which runs these twelve steps as a client.

Steps 1 to 8 read committed receipts and are instant. Step 10 downloads one waterfall and
fits one corridor, so it takes tens of seconds. Step 11 costs nothing extra, because it
checks the sentence against the measurement step 10 just took.

---

## What each step is there to show

**Steps 5 and 11 are the same refusal on two different kinds of data.** Step 5 refuses an
invented downlink frequency on a frozen observation. Step 11 refuses the same invention on
a pass that was recorded while the demo was running. The second one is the harder claim: it
means the guardrail is a property of the system rather than of the corpus.

**Step 6 is the control.** A checker that refuses everything catches every invention and is
useless. The rank-1 observation's own fitted offset, quoted in a sentence, has to pass.

**Step 7 is a fixed defect.** In the agent study the tool arm was asked how many
observations the queue ranks and answered 50, which is the per-call cap and also the review
budget. The answer is 407. Two of the three numbers are 50, and until `queue_size` existed
nothing named them apart.

**Step 8 has to come back with three of six gates met, and three unmet.** Gate 3, gate 5
and gate 6 are `NOT_ESTABLISHED`. Gate 4 is `PASSED`, on a blinded review a person answered;
the other two met gates are `PRE_PASSED`, which counts as met and is not the same as
measured. All six verdicts are published in `docs/KILL_GATE.md` and in the console. A
session that reports six of six met has been told something false by somebody.

Do not check that tally against this paragraph. It has been wrong twice: once when it said
two gates were unmet and four were, and once when it still said gate 4 was open after a
person had answered it. Check it against `gate_status`, which reads the receipts.
`scripts/run_operator_session.py` renders both its assertion and the sentence beside it from
those verdicts for the same reason.

**Step 12 uses a resource rather than a tool.** `resources/list` on this server used to
answer `-32601`, method not found, which is the right answer for a server with no resources
and the wrong one for a server whose subject is receipts.

---

## The same twelve steps, without Bob

`scripts/run_operator_session.py` runs this prompt as a client rather than as a model. It
launches both servers through the same two launchers `.bob/mcp.json` names, speaks JSON-RPC
on their stdin and stdout, and writes every call and every reading to
`artifacts/OPERATOR_SESSION.json`. The last run came back twelve of twelve, and its live
half measured observation 14839732 from station PF_DE_UHF_X_DIPOLE, recorded
at 2026-08-21T05:15:44Z and measured at 2026-08-21T05:23:48+00:00: UNRESOLVED,
because no signal stands out: best path is 1.5 sigma against a 8 sigma floor, over a 1,733,330 byte image whose sha256 is in
the receipt.

**It is not a substitute for the paste and the receipt says so in a field.** What Bob adds
is the choice: reading twelve tool descriptions and deciding which tool answers each step.
Here the calls are a list in a Python file. What the run does establish is everything under
that choice, which is where a demo actually breaks. The launchers resolve an interpreter.
Both servers answer `initialize`. Twelve tools exist under the names printed above. The
frozen refusal refuses, the control passes, and the live refusal holds against a
measurement taken minutes earlier.

It has already earned its place twice. Step 9 had no `status` argument, so the network
answered with passes scheduled for two days later, every one with no image, and the demo
stopped there with no reason given. And the paragraph about step 8 said two gates were
unmet when four are. Both were found by running the document instead of reading it.

## What this session proves that a build log cannot

`docs/BOB_BUILD_LOG.md` records that Bob built the pipeline: ten dated units with the files
they changed, the commands run, the Bob task id, and what failed before each was accepted.
That is the record of construction.

This session is a different claim. Bob **operates** the product: the same tools a reviewer
would use, over a network that exists, on a pass recorded today, with the grounding checker
refusing a sentence about a measurement that did not exist when the session started.

After running it, paste the step 5 codes and the step 10 provenance into a dated entry in
`docs/BOB_BUILD_LOG.md`. A transcript of tool calls is the evidence. A count of markdown
headings is not, which is why the number quoted in `FOR_JUDGES.md` now comes from a regex
over dated Bob-account units rather than from `line.startswith("## ")`.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| Neither server appears | Bob read a different config | `.bob/mcp.json` is the project file Bob reads. The root `.mcp.json` is for Cursor and Claude Code and Bob never loads it. |
| `tracetriage-live` has no tools | the virtual environment is missing | Run the two commands at the top of this file, or set `TRACETRIAGE_PYTHON`. |
| Step 10 times out | one waterfall is a few megabytes | Retry with another id from step 9. The endpoint and the tool both cache per id, so a retry on the same id is cheap. |
| Step 10 returns `NO_WATERFALL` | that observation stored no image | Pick another id from step 9. `has_waterfall` is in the listing for this reason. |
| Every live call returns `NO_AXIS` | the OCR extra is not installed | `pip install -e .[ocr]`. The axis reader falls back to a template matcher, and an axis that cannot be read is a named refusal rather than a wrong number. |
