"""An agent that can only answer from the evidence server, and a control arm that cannot.

The project already has two halves of this: a read-only MCP server that answers five questions
about the queue, the evidence packets, the gates and the receipts, and a local Granite model
that writes a reviewer note and is refused most of the time for writing numbers nothing
supports. This joins them into a loop and then measures the join, which is the part that is
usually skipped: an agent demonstration shows a transcript, and a transcript cannot separate a
model that read the tool output from a model that guessed and happened to be right.

So every question here is asked twice. Once with the tools, where the policy may call
``queue_top``, ``observation``, ``check_claim``, ``gate_status`` and ``receipt`` over real
stdio JSON-RPC against ``scripts/mcp_server.py``, and once with no tools at all and the same
question, where the same model must answer from what it knows. Both arms are graded against
ground truth derived from the same files the console ships, both report the rate at which the
final answer's numbers appear in something the agent actually read, and the two arms are
compared as a paired test over the tasks where they disagreed. If the tools are doing the work,
the difference is large and the control's grounding rate collapses. If they are decoration,
this file says so.

Nothing in the loop is a framework. The transport is 90 lines because the server speaks
newline-delimited JSON-RPC and that is all it speaks, and the policy is one prompt with a
parser that records what it could not parse instead of retrying until something works.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "scripts" / "mcp_server.py"

#: The step cap. A loop that may call tools forever cannot be measured, because a run that
#: never finished and a run that failed produce the same empty answer.
MAX_STEPS = 6

#: What the policy is allowed to do. Read from the server at run time rather than typed here,
#: so a tool the server stops advertising cannot survive in a prompt.
_TOOL_ORDER = ("queue_top", "observation", "check_claim", "gate_status", "receipt")


class ServerFailed(RuntimeError):
    """The evidence server did not start, or died mid-conversation."""


@dataclass
class Step:
    """One turn of the loop, including the turns that went wrong."""

    index: int
    raw: str
    parsed: dict[str, Any] | None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    answer: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "raw": self.raw,
            "tool": self.tool,
            "arguments": self.arguments,
            "error": self.error,
            "answer": self.answer,
            "result_bytes": None if self.result is None else len(json.dumps(self.result)),
        }


@dataclass
class Run:
    """One question, one arm, and everything the grader needs to be unable to flatter it."""

    task_id: str
    question: str
    arm: str
    steps: list[Step] = field(default_factory=list)
    answer: str | None = None
    tools_called: list[str] = field(default_factory=list)
    read: list[str] = field(default_factory=list)
    stopped_because: str = "answered"

    def as_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "question": self.question,
            "arm": self.arm,
            "answer": self.answer,
            "tools_called": self.tools_called,
            "stopped_because": self.stopped_because,
            "steps": [step.as_json() for step in self.steps],
            "read": self.read,
        }


class EvidenceClient:
    """A JSON-RPC client for the project's own MCP server, over the transport it speaks.

    Deliberately not an MCP library. The server has no dependencies and is tested under an
    interpreter started with -S -E; a client that needed a package to talk to it would make
    that property unobservable from the one place it matters.
    """

    def __init__(self, python: str | None = None) -> None:
        self._python = python or sys.executable
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self.tools: list[dict[str, Any]] = []

    def __enter__(self) -> EvidenceClient:
        self._proc = subprocess.Popen(
            [self._python, str(SERVER)],
            cwd=str(REPO),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._call("initialize", {})
        listed = self._call("tools/list", {})
        self.tools = listed.get("tools", [])
        return self

    def __exit__(self, *exc: object) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()
        finally:
            self._proc = None

    def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise ServerFailed("the evidence server is not running")
        self._next_id += 1
        frame = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._proc.stdin.write(json.dumps(frame) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            stderr = "" if self._proc.stderr is None else self._proc.stderr.read()
            raise ServerFailed(
                f"the server closed the connection during {method}. stderr: {stderr[:400]}"
            )
        reply = json.loads(line)
        if "error" in reply:
            # Not raised. A tool call that the server refuses is a measurement about the
            # policy, and the loop has to be able to show the refusal to it.
            return {"__error__": reply["error"]}
        return reply.get("result", {})

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._call("tools/call", {"name": name, "arguments": arguments})


def unwrap(result: dict[str, Any]) -> tuple[bool, Any]:
    """Pull the payload out of an MCP tool result, and say whether it was a refusal.

    The server answers in the protocol's own shape, ``{"content": [{"type": "text", "text":
    ...}], "isError": bool}``, so a tool that refuses returns a *result* rather than a JSON-RPC
    error. Reading only the transport's error field would have counted every BAD_ARGUMENTS as a
    successful call, which is the direction that flatters the policy.
    """
    if "__error__" in result:
        return True, result["__error__"]
    text = ""
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text") or ""
    try:
        payload: Any = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text
    return bool(result.get("isError")), payload


def tool_menu(tools: list[dict[str, Any]]) -> str:
    """The tool list as the policy sees it, ordered so two runs get the same prompt."""
    by_name = {tool["name"]: tool for tool in tools}
    lines = []
    for name in _TOOL_ORDER:
        tool = by_name.get(name)
        if tool is None:
            continue
        schema = tool.get("inputSchema", {})
        params = sorted((schema.get("properties") or {}).keys())
        required = sorted(schema.get("required") or [])
        lines.append(
            f"- {name}({', '.join(params) or 'no arguments'})"
            f"{'  required: ' + ', '.join(required) if required else ''}"
            f"\n    {tool.get('description', '').strip().splitlines()[0]}"
        )
    return "\n".join(lines)


#: Bumped whenever the wording changes, and recorded in the receipt. Two runs of a study
#: whose prompt moved in between are not two runs of one study.
PROMPT_VERSION = 2

TOOL_PROMPT = """You answer questions about a satellite observation review queue by calling \
tools. You have no knowledge of this dataset and must not guess.

Tools:
{menu}

Reply with exactly one JSON object and nothing else. To call a tool:
{{"tool": "<name>", "arguments": {{...}}}}
To finish:
{{"answer": "<the shortest exact answer, a number or a single word>"}}

Rules:
- One JSON object per reply. No prose, no markdown fence, no second object.
- Never put a number in an answer unless it appeared in a result below.
- If a tool returns an error, read it and call a different tool or different arguments.
- Do not repeat a call you have already made. Its result is already below.

Question: {question}

{history}Reply with one JSON object now. If a result above already contains the answer, give \
the answer rather than calling another tool."""

CONTROL_PROMPT = """You answer questions about a satellite observation review queue. You have \
no tools and no files.

Reply with exactly one JSON object and nothing else:
{{"answer": "<the shortest exact answer, a number or a single word>"}}

If you do not know, answer {{"answer": "unknown"}}. A wrong number is worse than "unknown".

Question: {question}
"""


def parse_action(raw: str) -> dict[str, Any] | None:
    """The first JSON object in the reply, or nothing.

    Forgiving about what surrounds the object and strict about what it contains. A policy that
    emits prose around its JSON is doing something a parser can recover; a policy that emits
    two objects is doing something a parser should not guess at, so only the first is read and
    the raw text is kept in the receipt either way.
    """
    depth = 0
    start = None
    for index, char in enumerate(raw):
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    value = json.loads(raw[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[str]:
    """Every numeric token, normalised so 0.50 and 0.5 are the same claim."""
    out = []
    for match in _NUMBER.findall(text or ""):
        try:
            value = float(match)
        except ValueError:
            continue
        out.append(f"{value:.6f}".rstrip("0").rstrip("."))
    return out


def is_grounded(answer: str, results: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Whether every number in the answer appears in something the agent was shown.

    The same test the reviewer-note checker applies to a sentence, applied to an agent's final
    answer: the tool results are the corpus, and a number that is not in them is invented no
    matter how plausible it looks. Returns the ungrounded tokens so the receipt can name them.
    """
    corpus = set()
    for result in results:
        corpus.update(numbers_in(json.dumps(result)))
    missing = [token for token in numbers_in(answer) if token not in corpus]
    return (not missing), missing


def run_task(
    task: dict[str, Any],
    generate: Any,
    client: EvidenceClient | None,
    *,
    max_steps: int = MAX_STEPS,
) -> Run:
    """One question, to one arm, with every step recorded including the useless ones.

    ``generate`` is injected rather than imported so the offline tests can drive the whole
    loop with a scripted policy: the loop's behaviour on a malformed reply, a refused tool call
    and a step cap are properties of this function and must be testable without a model.
    """
    arm = "control" if client is None else "tools"
    run = Run(task_id=task["id"], question=task["question"], arm=arm)

    if client is None:
        raw = generate(CONTROL_PROMPT.format(question=task["question"]))
        parsed = parse_action(raw)
        step = Step(index=1, raw=raw, parsed=parsed)
        if parsed is None or "answer" not in parsed:
            step.error = "no answer object in the reply"
            run.stopped_because = "unparseable"
        else:
            step.answer = str(parsed["answer"])
            run.answer = step.answer
        run.steps.append(step)
        return run

    menu = tool_menu(client.tools)
    history: list[str] = []
    seen_calls: set[str] = set()
    for index in range(1, max_steps + 1):
        prompt = TOOL_PROMPT.format(
            menu=menu,
            question=task["question"],
            history=("\n".join(history) + "\n\n") if history else "",
        )
        raw = generate(prompt)
        parsed = parse_action(raw)
        step = Step(index=index, raw=raw, parsed=parsed)

        if parsed is None:
            step.error = "no JSON object in the reply"
            run.steps.append(step)
            history.append(f"Your reply {index} could not be parsed as JSON. Send one object.")
            continue

        if "answer" in parsed and "tool" not in parsed:
            step.answer = str(parsed["answer"])
            run.answer = step.answer
            run.steps.append(step)
            return run

        name = parsed.get("tool")
        arguments = parsed.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            step.error = f"malformed call: tool={name!r} arguments={type(arguments).__name__}"
            run.steps.append(step)
            history.append(f"Reply {index} was not a tool call. Send tool and arguments.")
            continue

        step.tool = name
        step.arguments = arguments
        signature = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        if signature in seen_calls:
            # The same call twice is the loop this policy falls into. Answering it from a cache
            # would hide that it happened and paying the server twice would not help either, so
            # the step is recorded as a repeat and the policy is told plainly. Six of these in a
            # row is a run that hit the step cap, which the receipt reports rather than smooths.
            step.error = "repeated call, the earlier result is already in the history"
            run.steps.append(step)
            run.tools_called.append(name)
            history.append(
                f"You already called {name} with those arguments. Do not call it again. Read "
                f"its result above and answer."
            )
            continue
        seen_calls.add(signature)
        refused, payload = unwrap(client.call_tool(name, arguments))
        run.tools_called.append(name)
        if refused:
            step.error = json.dumps(payload)[:300]
            run.steps.append(step)
            history.append(f"Tool {name} returned an error: {step.error}")
            continue

        step.result = payload if isinstance(payload, dict) else {"payload": payload}
        run.steps.append(step)
        run.read.append(json.dumps(payload))
        history.append(f"Result of {name}: {json.dumps(payload)[:3000]}")

    run.stopped_because = "step cap"
    return run
