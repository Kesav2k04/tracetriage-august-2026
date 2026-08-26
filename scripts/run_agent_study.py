"""Ask the same questions twice, with the evidence server and without it, and grade both.

An agent demonstration is a transcript, and a transcript cannot tell a policy that read the
tool output from one that guessed. So this runs a paired study: 24 questions whose answers are
derived from the files the console ships, each put to the same local Granite model twice, once
with the seven MCP tools available over real stdio JSON-RPC and once with no tools at all.

    .venv/Scripts/python.exe scripts/run_agent_study.py --freeze   # runs the model, writes the
                                                                   # fixture and the receipt
    .venv/Scripts/python.exe scripts/run_agent_study.py            # republishes from the
                                                                   # fixture, no model needed

What is measured, per arm: the rate of exactly correct answers with an exact 95 percent
interval, the rate at which every number in the answer appeared in something the arm was shown,
and, for the tool arm, whether the tool the question needs was called at all and how many calls
the server refused. Then the two arms are compared as a paired exact test over the questions
where they disagreed, because 22 unpaired proportions would throw away the pairing the design
paid for.

The frozen fixture is what the receipt is published from, for the same reason the reviewer notes
are frozen: a receipt that needs a running model to regenerate cannot be reproduced by anyone
who does not have one, and the model's own run-to-run instability is already a measured finding
in this project rather than an assumption.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from run_gate3 import rate_lower_bound, rate_upper_bound  # noqa: E402

from pipeline.tracetriage.agent import (  # noqa: E402
    MAX_STEPS,
    PROMPT_VERSION,
    EvidenceClient,
    is_grounded,
    numbers_in,
    run_task,
    unwrap,
)

ARTIFACTS = REPO / "artifacts"
DATA = REPO / "apps" / "web" / "public" / "data"
FIXTURE = REPO / "tests" / "fixtures" / "agent_runs.json"
RECEIPT = ARTIFACTS / "AGENT_RECEIPT.json"

#: Both arms get the same cap. The control needs one step; the tool arm is allowed six.
CONTROL_STEPS = 1


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def build_tasks() -> list[dict[str, Any]]:
    """The question set, with every answer derived from a file rather than typed here.

    A hand-typed expected answer is a claim about the data that nothing checks, and this project
    has already published two of those. Each entry reads its ground truth out of the same JSON
    the tools serve, by a different code path, so a task whose answer drifts fails at build time
    instead of grading a correct answer wrong. Each entry also carries a ``reference`` call, and
    :func:`verify_answerable` requires the expected answer to be a value in that call's result
    before any model is graded on the question.
    """
    queue = _read(DATA / "queue.json")
    cards = {int(card["obs_id"]): card for card in _read(DATA / "cards.json")["cards"]}
    explain = _read(ARTIFACTS / "EXPLAIN_RECEIPT.json")
    queue_receipt = _read(ARTIFACTS / "QUEUE_RECEIPT.json")
    gate3 = _read(ARTIFACTS / "GATE3_RECEIPT.json")
    gate4 = _read(ARTIFACTS / "GATE4_RECEIPT.json")

    entries = queue["entries"]
    top = entries[0]
    with_packet_top10 = sum(1 for row in entries[:10] if row["obs_id"] in cards)

    # Four observations with packets, chosen by rank so the set is stable across rebuilds.
    ranked = [row["obs_id"] for row in entries if row["obs_id"] in cards]
    a, b, c, d = ranked[0], ranked[1], ranked[2], ranked[3]

    # Ground truth for the observation questions comes out of the console's own card, by a
    # named transformation, and is then cross-checked against the packet the tool serves. Taking
    # it from the packet alone would grade the tool against itself; taking it from the card
    # alone would fail the moment the packet rounds a value, which it does. Both, and any
    # disagreement is the failure.
    from pipeline.tracetriage.explain import build_packet  # noqa: PLC0415

    by_id = {int(row["obs_id"]): row for row in entries}
    packets = {obs: build_packet(cards[obs], by_id[obs]).printed for obs in (a, b, c, d)}
    derived = {
        obs: {
            "ground_station_name": str(cards[obs]["station_name"]),
            "transmitter_mode": str(cards[obs]["transmitter_mode"]),
            "network_label": str(cards[obs]["waterfall_status"]),
            "axis_derivation": str(cards[obs]["derivation"]),
            "hz_per_pixel": f"{cards[obs]['hz_per_px']:.1f}",
            "max_elevation_deg": f"{cards[obs]['geometry']['max_elevation_deg']:.1f}",
        }
        for obs in (a, b, c, d)
    }
    for obs, fields in derived.items():
        for field, value in fields.items():
            if packets[obs][field] != value:
                raise SystemExit(
                    f"observation {obs}: the card gives {field} as {value!r} and the evidence "
                    f"packet prints {packets[obs][field]!r}. The study would grade against a "
                    f"value the tool does not serve, so fix the transformation rather than the "
                    f"expectation."
                )

    ungrounded_sentence = "The fitted offset is 999 Hz."
    grounded_sentence = f"The fitted offset is {packets[a]['fitted_offset_hz']} Hz."
    top10 = {"limit": 10}

    tasks: list[dict[str, Any]] = [
        {
            "id": "queue-rank-1",
            "question": "Which observation id is ranked first in the review queue?",
            "expected": str(top["obs_id"]),
            "tool": "queue_top",
            "reference": top10,
        },
        {
            "id": "queue-rank-1-score",
            "question": (
                "What is the queue score of the top-ranked observation, as the queue reports it?"
            ),
            "expected": f"{top['score']:.6f}".rstrip("0").rstrip("."),
            "tool": "queue_top",
            "reference": top10,
        },
        {
            "id": "queue-total",
            "question": "How many observations does the review queue rank in total?",
            "expected": str(len(entries)),
            "tool": "queue_top",
            "reference": top10,
        },
        {
            "id": "queue-packets-top-10",
            "question": (
                "Of the ten highest-ranked queue rows, how many have an evidence packet?"
            ),
            "expected": str(with_packet_top10),
            "tool": "queue_top",
            "reference": top10,
        },
        {
            "id": "queue-reason-rank-1",
            "question": (
                "What single reason code does the top-ranked observation carry in the queue?"
            ),
            "expected": top["reasons"][0],
            "tool": "queue_top",
            "reference": top10,
        },
        {
            "id": "obs-station-name",
            "question": f"What is the ground station name for observation {a}?",
            "expected": derived[a]["ground_station_name"],
            "tool": "observation",
            "reference": {"observation_id": a},
        },
        {
            "id": "obs-fitted-offset",
            "question": f"What is the fitted offset in Hz for observation {a}?",
            "expected": packets[a]["fitted_offset_hz"],
            "tool": "observation",
            "reference": {"observation_id": a},
        },
        {
            "id": "obs-hz-per-pixel",
            "question": f"How many Hz does one pixel span for observation {b}?",
            "expected": derived[b]["hz_per_pixel"],
            "tool": "observation",
            "reference": {"observation_id": b},
        },
        {
            "id": "obs-network-label",
            "question": f"What network label does observation {b} carry?",
            "expected": derived[b]["network_label"],
            "tool": "observation",
            "reference": {"observation_id": b},
        },
        {
            "id": "obs-transmitter-mode",
            "question": f"What is the transmitter mode for observation {c}?",
            "expected": derived[c]["transmitter_mode"],
            "tool": "observation",
            "reference": {"observation_id": c},
        },
        {
            "id": "obs-axis-derivation",
            "question": f"How was the frequency axis derived for observation {c}?",
            "expected": derived[c]["axis_derivation"],
            "tool": "observation",
            "reference": {"observation_id": c},
        },
        {
            "id": "obs-max-elevation",
            "question": f"What was the maximum elevation in degrees for observation {d}?",
            "expected": derived[d]["max_elevation_deg"],
            "tool": "observation",
            "reference": {"observation_id": d},
        },
        {
            "id": "claim-refused",
            "question": (
                f'For observation {a}, is the sentence "{ungrounded_sentence}" grounded in the '
                f"evidence packet? Answer GROUNDED or REFUSED."
            ),
            "expected": "REFUSED",
            "tool": "check_claim",
            "reference": {"observation_id": a, "text": ungrounded_sentence},
        },
        {
            "id": "claim-refused-code",
            "question": (
                f'For observation {a}, which single violation code does the sentence '
                f'"{ungrounded_sentence}" produce?'
            ),
            "expected": "UNGROUNDED_NUMBER",
            "tool": "check_claim",
            "reference": {"observation_id": a, "text": ungrounded_sentence},
        },
        {
            "id": "claim-grounded",
            "question": (
                f'For observation {a}, is the sentence "{grounded_sentence}" grounded in the '
                f"evidence packet? Answer GROUNDED or REFUSED."
            ),
            "expected": "GROUNDED",
            "tool": "check_claim",
            "reference": {"observation_id": a, "text": grounded_sentence},
        },
        {
            "id": "gates-met",
            "question": "How many of this project's kill gates are met?",
            "expected": None,
            "tool": "gate_status",
            "reference": {},
        },
        {
            "id": "gates-total",
            "question": "How many kill gates does this project define?",
            "expected": None,
            "tool": "gate_status",
            "reference": {},
        },
        {
            "id": "gate-6-verdict",
            "question": "What is the verdict of kill gate 6?",
            "expected": None,
            "tool": "gate_status",
            "reference": {},
        },
        {
            "id": "gate-4-verdict",
            "question": "What is the verdict of kill gate 4?",
            "expected": None,
            "tool": "gate_status",
            "reference": {},
        },
        {
            "id": "receipt-queue-schema-version",
            "question": "What schema version does the receipt QUEUE_RECEIPT.json carry?",
            "expected": str(queue_receipt["schema_version"]),
            "tool": "receipt",
            "reference": {"name": "QUEUE_RECEIPT.json"},
        },
        {
            "id": "receipt-gate3-verdict",
            "question": "What verdict does the receipt GATE3_RECEIPT.json record?",
            "expected": str(gate3["verdict"]),
            "tool": "receipt",
            "reference": {"name": "GATE3_RECEIPT.json"},
        },
        {
            "id": "receipt-gate4-verdict",
            "question": "What verdict does the receipt GATE4_RECEIPT.json record?",
            "expected": str(gate4["verdict"]),
            "tool": "receipt",
            "reference": {"name": "GATE4_RECEIPT.json"},
        },
        {
            "id": "receipt-explain-unit",
            "question": "Which unit produced the receipt EXPLAIN_RECEIPT.json?",
            "expected": str(explain["unit"]),
            "tool": "receipt",
            "reference": {"name": "EXPLAIN_RECEIPT.json"},
        },
        {
            "id": "receipt-explain-per-observation",
            "question": (
                "How many per-observation rows does the receipt EXPLAIN_RECEIPT.json carry?"
            ),
            "expected": str(len(explain["per_observation"])),
            "tool": "receipt",
            "reference": {"name": "EXPLAIN_RECEIPT.json"},
        },
    ]

    # The gate questions are answered from the same summary the gate_status tool serves, so a
    # gate that changes verdict moves the tool and the ground truth in one step.
    from mcp_server import tool_gate_status  # noqa: PLC0415

    status = tool_gate_status()
    by_gate = {row["gate"]: row for row in status["gates"]}
    filled = {
        "gates-met": str(status["n_met"]),
        "gates-total": str(status["n_gates"]),
        "gate-6-verdict": by_gate[6]["verdict"],
        "gate-4-verdict": by_gate[4]["verdict"],
    }
    for task in tasks:
        if task["expected"] is None:
            task["expected"] = filled[task["id"]]

    for task in tasks:
        if not task["expected"]:
            raise SystemExit(f"task {task['id']} has no ground truth, so it cannot be graded")
        if "reference" not in task:
            raise SystemExit(
                f"task {task['id']} has no reference call, so nothing establishes that the tools "
                f"can answer it at all"
            )
    return tasks


def _leaves(value: Any) -> list[str]:
    """Every scalar in a payload, as a string. Substring matching is too weak here: the digits
    of a refused count appear inside an observation id, and a check that passes on that would
    let an unanswerable question into the study."""
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_leaves(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_leaves(item))
        return out
    return [str(value)]


def verify_answerable(tasks: list[dict[str, Any]], client: EvidenceClient) -> list[dict[str, Any]]:
    """Run one reference call per task and require the expected answer to be a value in it.

    Without this, a question whose answer the tools do not serve grades as a model failure. One
    was: the receipt tool publishes a receipt's top-level scalars and the sizes of its
    collections, so "how many drafts did the checker refuse" was unanswerable, and the model's
    wrong answer to it would have been counted against the policy rather than against the study.
    A study that cannot tell those two apart is measuring its own question set.
    """
    proofs = []
    for task in tasks:
        refused, payload = unwrap(client.call_tool(task["tool"], task["reference"]))
        if refused:
            raise SystemExit(
                f"task {task['id']}: the reference call to {task['tool']} was refused: "
                f"{json.dumps(payload)[:200]}"
            )
        values = {normalise(leaf) for leaf in _leaves(payload)}
        if normalise(task["expected"]) not in values:
            raise SystemExit(
                f"task {task['id']}: {task['expected']!r} is not a value in the result of "
                f"{task['tool']}({json.dumps(task['reference'])[:80]}), so no policy could "
                f"answer it from that tool. Fix the question or drop it."
            )
        proofs.append(
            {
                "task_id": task["id"],
                "tool": task["tool"],
                "arguments": task["reference"],
                "expected_is_a_value_in_the_result": True,
            }
        )
    return proofs


def normalise(text: str | None) -> str:
    """Compare answers as claims rather than as strings.

    A model that answers "0.88" where the queue says "0.879634" is wrong, and one that answers
    "REFUSED." or "refused" is right. Numbers are normalised through the same function the
    grounding check uses, so a trailing zero is not a different claim.
    """
    if text is None:
        return ""
    value = text.strip().strip(".").strip().lower()
    value = " ".join(value.split())
    numbers = numbers_in(value)
    if numbers and value.replace(" ", "").strip("+-").replace(".", "").isdigit():
        return numbers[0]
    return value


def grade(run: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """One run, graded, with the pieces a reader needs to disagree with the grade."""
    answer = run.get("answer")
    correct = normalise(answer) == normalise(task["expected"])
    read = [json.loads(blob) for blob in run.get("read") or []]
    if run["arm"] == "control":
        # Nothing was read, so the only corpus a control answer can be grounded in is the
        # question it was asked. That is the honest analogue rather than an automatic zero.
        read = [{"question": run["question"]}]
    grounded, missing = is_grounded(answer or "", read)
    calls = [step for step in run["steps"] if step.get("tool")]
    repeats = [
        step for step in calls if (step.get("error") or "").startswith("repeated call")
    ]
    refusals = [step for step in calls if step.get("error") and step not in repeats]

    # The distinction that makes a wrong answer diagnostic. A policy that never fetched the
    # value and a policy that had it in front of it and picked a neighbouring field are two
    # different failures, and only the second is about reading rather than about planning.
    values = {
        normalise(leaf)
        for blob in run.get("read") or []
        for leaf in _leaves(json.loads(blob))
    }
    return {
        "task_id": task["id"],
        "arm": run["arm"],
        "question": run["question"],
        "answer": answer,
        "expected": task["expected"],
        "correct": correct,
        "grounded": grounded,
        "ungrounded_numbers": missing,
        "expected_tool": task["tool"],
        "expected_tool_called": task["tool"] in (run.get("tools_called") or []),
        "tool_calls": len(calls),
        "repeated_calls": len(repeats),
        "server_refusals": len(refusals),
        "answer_was_in_what_it_read": normalise(task["expected"]) in values,
        "unparseable_steps": sum(
            1 for step in run["steps"] if step.get("error") and not step.get("tool")
        ),
        "stopped_because": run["stopped_because"],
    }


def _rate(successes: int, trials: int) -> dict[str, Any]:
    return {
        "successes": successes,
        "trials": trials,
        "rate": None if not trials else round(successes / trials, 4),
        "lower_95": None if not trials else round(rate_lower_bound(successes, trials), 4),
        "upper_95": None if not trials else round(rate_upper_bound(successes, trials), 4),
    }


def _binomial_tail(k: int, n: int, p: float = 0.5) -> float:
    """P(X >= k) for X ~ Binomial(n, p), exactly, with no dependency.

    The paired comparison needs one number and it is a sum of binomial terms. scipy is a
    dependency this file does not need for arithmetic a reader can check by hand at n = 12.
    """
    from math import comb

    return sum(comb(n, i) * (p**i) * ((1 - p) ** (n - i)) for i in range(k, n + 1))


def summarise(graded: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[dict[str, Any]]] = {"tools": [], "control": []}
    for row in graded:
        by_arm[row["arm"]].append(row)

    arms = {}
    for arm, rows in by_arm.items():
        arms[arm] = {
            "correct": _rate(sum(1 for r in rows if r["correct"]), len(rows)),
            "grounded": _rate(sum(1 for r in rows if r["grounded"]), len(rows)),
            "answered": sum(1 for r in rows if r["answer"]),
            "declined_unknown": sum(
                1 for r in rows if (r["answer"] or "").strip().lower() == "unknown"
            ),
            "unparseable_steps": sum(r["unparseable_steps"] for r in rows),
        }
    tool_rows = by_arm["tools"]
    wrong = [r for r in tool_rows if not r["correct"]]
    arms["tools"] |= {
        "expected_tool_called": _rate(
            sum(1 for r in tool_rows if r["expected_tool_called"]), len(tool_rows)
        ),
        "tool_calls": sum(r["tool_calls"] for r in tool_rows),
        "repeated_calls": sum(r["repeated_calls"] for r in tool_rows),
        "server_refusals": sum(r["server_refusals"] for r in tool_rows),
        "hit_the_step_cap": sum(1 for r in tool_rows if r["stopped_because"] == "step cap"),
        "fetched_the_answer": _rate(
            sum(1 for r in tool_rows if r["answer_was_in_what_it_read"]), len(tool_rows)
        ),
        "wrong_with_the_answer_in_front_of_it": sorted(
            r["task_id"] for r in wrong if r["answer_was_in_what_it_read"]
        ),
        "wrong_and_never_fetched_it": sorted(
            r["task_id"] for r in wrong if not r["answer_was_in_what_it_read"]
        ),
        "reading": (
            "Repeated calls are ones the loop refused because the policy had already made "
            "them, and server refusals are ones the server itself rejected; the first is a "
            "planning failure and the second is an argument failure, and summing them into one "
            "number would hide which. The fetch rate is the share of questions where the "
            "value ended up in something the policy read, so the two wrong answers can be "
            "separated into one that never looked and one that looked and chose a neighbouring "
            "field."
        ),
    }

    tools_by_task = {r["task_id"]: r for r in by_arm["tools"]}
    control_by_task = {r["task_id"]: r for r in by_arm["control"]}
    tools_only = [
        t["id"]
        for t in tasks
        if tools_by_task[t["id"]]["correct"] and not control_by_task[t["id"]]["correct"]
    ]
    control_only = [
        t["id"]
        for t in tasks
        if control_by_task[t["id"]]["correct"] and not tools_by_task[t["id"]]["correct"]
    ]
    discordant = len(tools_only) + len(control_only)
    return {
        "arms": arms,
        "paired": {
            "tasks": len(tasks),
            "both_correct": sum(
                1
                for t in tasks
                if tools_by_task[t["id"]]["correct"] and control_by_task[t["id"]]["correct"]
            ),
            "neither_correct": sum(
                1
                for t in tasks
                if not tools_by_task[t["id"]]["correct"]
                and not control_by_task[t["id"]]["correct"]
            ),
            "tools_only": tools_only,
            "control_only": control_only,
            "discordant_pairs": discordant,
            "exact_p_one_sided": (
                None
                if discordant == 0
                else round(_binomial_tail(len(tools_only), discordant), 6)
            ),
            "method": (
                "McNemar's exact test on the discordant pairs: under the null that the tools "
                "make no difference, the number of tasks the tool arm alone gets right is "
                "Binomial(discordant, 0.5), and the reported p is the one-sided upper tail. "
                "Computed with math.comb so a reader can check it by hand."
            ),
            "reading": (
                "The pairing is the design. Two independent proportions over this many questions "
                "would have intervals wide enough to hide the effect, and the questions are not "
                "interchangeable: some are answerable from a model's general knowledge and some "
                "are about this snapshot alone. Read the control's successes rather than only "
                "its rate: a question with two allowed answers can be got right by guessing, "
                "and a guessed number shows up in this receipt as an ungrounded answer whether "
                "or not it happened to be correct."
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--freeze",
        action="store_true",
        help="run the model against both arms and rewrite the fixture. Needs a local runtime.",
    )
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--out", type=Path, default=RECEIPT)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    args = ap.parse_args(argv)

    tasks = build_tasks()

    if args.freeze:
        from pipeline.tracetriage.granite import MODEL, SEED, generate, model_identity

        def policy(prompt: str) -> str:
            return generate(prompt, max_tokens=200)

        identity = model_identity()
        runs: list[dict[str, Any]] = []
        with EvidenceClient() as client:
            proofs = verify_answerable(tasks, client)
            print(f"  every one of {len(proofs)} questions has a single-call answer")
            for task in tasks:
                print(f"  tools   {task['id']}")
                runs.append(
                    run_task(task, policy, client, max_steps=args.max_steps).as_json()
                )
        for task in tasks:
            print(f"  control {task['id']}")
            runs.append(run_task(task, policy, None).as_json())

        args.fixture.parent.mkdir(parents=True, exist_ok=True)
        args.fixture.write_text(
            json.dumps(
                {
                    "schema": "AGENT_RUNS",
                    "schema_version": 1,
                    "model": {
                        "name": identity.name,
                        "digest": identity.digest,
                        "parameter_size": identity.parameter_size,
                        "quantization": identity.quantization,
                        "context_length": identity.context_length,
                        "seed": SEED,
                        "temperature": 0.0,
                        "model_argument": MODEL,
                    },
                    "max_steps": args.max_steps,
                    "control_steps": CONTROL_STEPS,
                    "prompt_version": PROMPT_VERSION,
                    "answerable": proofs,
                    "tasks": tasks,
                    "runs": runs,
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"froze {len(runs)} runs into {args.fixture}")

    if not args.fixture.exists():
        raise SystemExit(
            f"{args.fixture} does not exist, so there is nothing to publish. Run with --freeze "
            f"and a local model runtime."
        )
    frozen = _read(args.fixture)
    frozen_tasks = {task["id"]: task for task in frozen["tasks"]}
    if {t["id"] for t in tasks} != set(frozen_tasks):
        raise SystemExit(
            "the task set has changed since the fixture was frozen, so the frozen answers were "
            "given to different questions. Re-freeze."
        )
    for task in tasks:
        if task["expected"] != frozen_tasks[task["id"]]["expected"]:
            raise SystemExit(
                f"task {task['id']} expects {task['expected']!r} now and "
                f"{frozen_tasks[task['id']]['expected']!r} when the fixture was frozen. The "
                f"data moved under the study; re-freeze rather than regrading old answers."
            )

    graded = [grade(run, frozen_tasks[run["task_id"]]) for run in frozen["runs"]]
    payload = {
        "schema": "AGENT_RECEIPT",
        "schema_version": 1,
        "unit": "E7",
        "model": frozen["model"],
        "design": (
            "Paired. Every question is put to the same model twice: once with the seven MCP "
            "tools of scripts/mcp_server.py available over stdio JSON-RPC, once with no tools. "
            "Ground truth is derived from the files the console ships, by a different code path "
            "than the tools use, and checked against the frozen fixture before grading."
        ),
        "tasks": len(frozen["tasks"]),
        "max_steps": frozen["max_steps"],
        "prompt_version": frozen.get("prompt_version"),
        "every_question_has_a_single_call_answer": len(frozen.get("answerable") or []),
        "frozen_runs_sha256": None,
        **summarise(graded, frozen["tasks"]),
        "per_run": graded,
        "what_this_does_not_measure": [
            "Whether the answers are useful to a reviewer. These are lookups with a single "
            "correct token, chosen so grading is mechanical, and a real question is not.",
            "Whether a different model would behave the same way. One model, one seed, "
            "temperature zero, and this project has already measured that the same runtime is "
            "not reproducible run to run.",
            "Whether the tool arm would survive questions the tools cannot answer. Every task "
            "here is answerable from five of the seven tools offered, so the study measures "
            "whether the policy uses them and not whether it knows when to stop.",
        ],
    }
    import hashlib

    payload["frozen_runs_sha256"] = hashlib.sha256(
        args.fixture.read_bytes()
    ).hexdigest()
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline="\n")

    tools = payload["arms"]["tools"]
    control = payload["arms"]["control"]
    print(
        f"tools   {tools['correct']['successes']}/{tools['correct']['trials']} correct, "
        f"grounded {tools['grounded']['rate']}, "
        f"{tools['repeated_calls']} repeated calls, {tools['server_refusals']} refused"
    )
    print(f"control {control['correct']['successes']}/{control['correct']['trials']} correct, "
          f"grounded {control['grounded']['rate']}, unknown {control['declined_unknown']}")
    print(f"paired  p = {payload['paired']['exact_p_one_sided']} over "
          f"{payload['paired']['discordant_pairs']} discordant pairs")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
