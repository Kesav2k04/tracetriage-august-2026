"""Build the LangChain adapter, call every tool through it, and write the receipt.

The claim this checks is narrow and it is the only one worth making: the tools a LangChain
agent gets are the tools the MCP server registered, not a second implementation that happens
to have the same names. So this builds each one, calls it, and records the fully qualified
name of the callable behind it.

It also calls them. A wrapper that constructs and never runs is a wrapper that fails on the
first agent turn, and the argument unpacking is exactly the kind of thing that only shows up
when something calls it: the MCP transport hands each handler an arguments dict and unpacks
it there, so passing the dict through raised "takes 0 positional arguments" on the two tools
that take none.

    .venv/Scripts/python.exe scripts/run_langchain_check.py
    .venv/Scripts/python.exe scripts/run_langchain_check.py --check

Nothing here reaches the network and nothing here needs a model. `langchain-core` is an
optional extra: without it this exits 0 and writes a receipt that says so, because a missing
optional integration is a fact about the environment and not a failure of the project.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.langchain_tools import (  # noqa: E402
    OFFERED,
    LangChainMissing,
    receipt,
    tools,
)

OUT = REPO / "artifacts" / "LANGCHAIN_RECEIPT.json"

#: One call per offered tool, with arguments that are valid and cheap. Each is a read of a
#: committed file, so this whole script is milliseconds and no call has a side effect.
#:
#: `check_claim` is called with the sentence the whole project turns on. It has to come back
#: REFUSED with `UNGROUNDED_NUMBER`, and the receipt records the codes, so this file also
#: checks that the grounding checker is reachable through the adapter rather than only that
#: the adapter builds.
CALLS: tuple[tuple[str, dict], ...] = (
    ("queue_top", {"limit": 3}),
    ("queue_size", {}),
    ("observation", {"observation_id": 14740031}),
    (
        "check_claim",
        {"observation_id": 14740031, "text": "The downlink is 437.2 MHz."},
    ),
    ("gate_status", {}),
    ("receipt", {"name": "QUEUE_RECEIPT.json"}),
)


def exercise() -> dict:
    """Call every tool through the adapter and record what came back, in one place."""
    built = {tool.name: tool for tool in tools()}
    if set(built) != set(OFFERED):
        raise SystemExit(
            f"the adapter built {sorted(built)} and offers {sorted(OFFERED)}. One of the "
            f"two is wrong."
        )
    called = []
    for name, arguments in CALLS:
        payload = json.loads(built[name].invoke(dict(arguments)))
        called.append(
            {
                "tool": name,
                "arguments": arguments,
                "returned_keys": sorted(payload),
                "bytes": len(json.dumps(payload)),
            }
        )
    covered = {entry["tool"] for entry in called}
    if covered != set(OFFERED):
        raise SystemExit(
            f"{sorted(set(OFFERED) - covered)} were offered and never called, so this "
            f"receipt would report a tool as working on the strength of it existing."
        )

    refusal = json.loads(
        built["check_claim"].invoke(
            {"observation_id": 14740031, "text": "The downlink is 437.2 MHz."}
        )
    )
    if refusal.get("verdict") == "GROUNDED" or "UNGROUNDED_NUMBER" not in refusal.get(
        "codes", []
    ):
        raise SystemExit(
            f"check_claim through the adapter did not refuse an invented downlink "
            f"frequency: {refusal}. The wrapper is reaching something other than "
            f"explain.verify_note."
        )

    return {
        "n_called": len(called),
        "calls": called,
        "refusal_through_the_adapter": {
            "text": "The downlink is 437.2 MHz.",
            "observation_id": 14740031,
            "verdict": refusal.get("verdict"),
            "codes": refusal.get("codes"),
        },
    }


def build() -> dict:
    payload = receipt()
    try:
        payload["exercised"] = exercise()
        payload["langchain"] = "installed"
    except LangChainMissing as error:
        # Not a failure. The receipt says the adapter was not exercised and why, which is
        # the same shape the vector index uses when chromadb is absent.
        payload["exercised"] = None
        payload["langchain"] = "not installed"
        payload["reading_on_absence"] = str(error)
    return payload


def render() -> str:
    return json.dumps(build(), indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="build in memory and compare against the committed receipt, writing nothing",
    )
    args = parser.parse_args(argv)

    rendered = render()
    payload = json.loads(rendered)
    if args.check:
        if not OUT.exists():
            print(f"{OUT} does not exist. Run scripts/run_langchain_check.py.")
            return 1
        if OUT.read_text(encoding="utf-8") == rendered:
            print(
                f"{OUT.name} is current: {payload['n_offered']} tools offered, "
                f"{payload['langchain']}"
            )
            return 0
        print(f"{OUT.name} is stale. Run scripts/run_langchain_check.py.")
        return 1

    OUT.write_text(rendered, encoding="utf-8", newline="\n")
    exercised = payload["exercised"]
    print(
        f"{OUT.name} written: {payload['n_offered']} of "
        f"{payload['n_registered_by_the_mcp_server']} MCP tools offered, "
        f"{len(payload['withheld'])} withheld, langchain {payload['langchain']}"
    )
    if exercised:
        print(
            f"  {exercised['n_called']} tools called, and check_claim came back "
            f"{exercised['refusal_through_the_adapter']['verdict']} with "
            f"{exercised['refusal_through_the_adapter']['codes']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
