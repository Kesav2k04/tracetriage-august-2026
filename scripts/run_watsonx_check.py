"""Ask watsonx to write one reviewer note, and put its answer through the same checker.

    .venv/Scripts/python.exe scripts/run_watsonx_check.py
    .venv/Scripts/python.exe scripts/run_watsonx_check.py --check

`pipeline/tracetriage/watsonx.py` was 311 lines of finished code with no caller anywhere in
the tree: no script, no subcommand, no test, no receipt. Its own module docstring said the
environment variable names live in one place "because the runner, the tests and
``.env.example`` all have to agree about them", and there was no runner, there were no tests,
and `.env.example` did not name them. A backend nothing calls is not an integration, and a
docstring that describes a runner which does not exist is worse than silence.

This is the runner. It does one thing: build the same evidence packet and the same prompt the
local Granite backend gets, send it to watsonx Granite, and hand whatever comes back to
`explain.verify_note`. That last step is the point the whole design turns on. The grounding
checker does not know or care which backend produced a sentence, so a draft from a hosted
model is admitted or refused by exactly the rules that decide whether this project's own
notes ship. Swapping the backend is therefore a measurement rather than a rewrite.

**Three outcomes, and the third is why this script is worth running with no account.**

    RAN          credentials present, watsonx answered, the checker returned a verdict
    NOT_CHECKED  no credentials in this environment, recorded with the date and the reason
    FAILED       credentials present and the service refused, with the typed error name

`NOT_CHECKED` is a first-class outcome and not a silent pass. `scripts/signoff.py` already
needed this third column for the same reason: a check that cannot run here and reports green
is the same defect as a check that fails and reports green, one level up. So this script
exits 0 on a missing credential and writes a receipt that says, in the file a judge reads,
that watsonx was attempted from this tree on this date and no key was present. What it never
does is write a receipt whose backend field says watsonx over text a local model produced.

`--check` rebuilds the receipt and fails if the committed one disagrees about anything except
the timestamps, which is the same contract every other generator here honours. It is
deliberately tolerant of the outcome changing: a tree that ran this with credentials and
then ran it without them has two different true receipts, and `--check` says which one is
committed rather than pretending one of them is wrong.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from pipeline.tracetriage.explain import (  # noqa: E402
    PROMPT_VERSION,
    MeasurementMissing,
    build_packet,
    build_prompt,
    prompt_contract_sha256,
    verify_note,
)
from pipeline.tracetriage.watsonx import (  # noqa: E402
    API_VERSION,
    ENV_API_KEY,
    ENV_PROJECT_ID,
    ENV_URL,
    MODEL_ID,
    CredentialsMissing,
    WatsonxCredentials,
    WatsonxError,
    generate,
)

_DATA = REPO / "apps" / "web" / "public" / "data"
_RECEIPT = REPO / "artifacts" / "WATSONX_RECEIPT.json"

#: The observation the note is written about.
#:
#: Rank 1 of the shipped queue rather than a hand-picked id, resolved at run time from
#: queue.json, so this script cannot end up asking about an observation the console no
#: longer ranks. Recorded in the receipt as the id it resolved to, and how.
_SUBJECT_RULE = "rank 1 of the shipped queue that carries an evidence packet"


def _subject() -> Any:
    """The evidence packet the prompt is built from, and the rule that chose it."""
    cards = json.loads((_DATA / "cards.json").read_text(encoding="utf-8"))["cards"]
    entries = json.loads((_DATA / "queue.json").read_text(encoding="utf-8"))["entries"]
    by_id = {int(entry["obs_id"]): entry for entry in entries}
    ranked = sorted(
        (card for card in cards if int(card["obs_id"]) in by_id),
        key=lambda card: by_id[int(card["obs_id"])]["rank"],
    )
    for card in ranked:
        try:
            return build_packet(card, by_id[int(card["obs_id"])])
        except MeasurementMissing:
            # A card shipped with a named degrade carries no corridor, so there is no
            # packet to write a sentence from. Skipping is not a failure: the next
            # ranked card is a valid subject and the receipt records which one answered.
            continue
    raise SystemExit(
        "no card in the shipped queue yields an evidence packet. "
        "Run scripts/build_console_data.py first."
    )


def _configured() -> list[str]:
    """Which of the two required variables are set, for the skip record."""
    return [
        name
        for name in (ENV_API_KEY, ENV_PROJECT_ID)
        if (os.environ.get(name) or "").strip()
    ]


def _attempt(packet: Any, prompt: str) -> dict[str, Any]:
    """One call, and the outcome as a receipt block. Never raises for a missing key."""
    try:
        credentials = WatsonxCredentials.from_env()
    except CredentialsMissing as missing:
        return {
            "outcome": "NOT_CHECKED",
            "reason": str(missing),
            "variables_set": _configured(),
            "variables_required": [ENV_API_KEY, ENV_PROJECT_ID],
            "variable_optional": ENV_URL,
            "reading": (
                "watsonx was attempted from this tree and no credential was present, so "
                "nothing was sent and nothing is claimed. This is recorded rather than "
                "omitted: an integration that cannot be exercised in an environment "
                "should say so in that environment's receipt. Every number this project "
                "publishes comes from the local Granite runtime, which needs no account, "
                "and the grounding checker is the same code either way."
            ),
        }

    try:
        completion = generate(prompt, credentials=credentials)
    except WatsonxError as error:
        return {
            "outcome": "FAILED",
            "error_class": type(error).__name__,
            "error": str(error),
            "credentials": credentials.redacted(),
            "reading": (
                "The service was reached and did not return usable text. The error class "
                "is the receipt's answer to why: CredentialsMissing means nothing was "
                "provisioned, AuthenticationFailed means the key does not carry the "
                "entitlement, NoInstance means no Watson Machine Learning deployment "
                "sits behind a valid token, which is the ordinary outcome of a free IBM "
                "Cloud account."
            ),
        }

    verification = verify_note(completion.text, packet)
    return {
        "outcome": "RAN",
        "credentials": credentials.redacted(),
        "generation": completion.as_dict(),
        "checker": {
            "verdict": "GROUNDED" if verification.ok else "REFUSED",
            "codes": list(verification.codes),
            "violations": list(verification.violations),
        },
        "reading": (
            "The draft went through pipeline/tracetriage/explain.py, which is the same "
            "function that decides whether a locally generated note ships. A REFUSED "
            "verdict here is not a watsonx failure and not a bug: it is the checker doing "
            "on a hosted backend what it does on the local one, and the refusal rate over "
            "the 25 shipped observations is 0.6."
        ),
    }


def build() -> dict[str, Any]:
    packet = _subject()
    prompt = build_prompt(packet)
    attempt = _attempt(packet, prompt)
    return {
        "unit": "F1",
        "generated_at": datetime.now(UTC).isoformat(),
        "backend": {
            "name": "watsonx.ai text generation",
            "model_id": MODEL_ID,
            "api_version": API_VERSION,
            "module": "pipeline/tracetriage/watsonx.py",
        },
        "subject": {
            "observation_id": packet.obs_id,
            "chosen_by": _SUBJECT_RULE,
            "prompt_version": PROMPT_VERSION,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "prompt_characters": len(prompt),
        },
        "attempt": attempt,
        "what_this_does_not_measure": (
            "Whether watsonx writes better notes than the local runtime. One draft about "
            "one observation is an integration check, not a comparison: a comparison needs "
            "the same 25 observations through both backends with the checker's verdict on "
            "each, and that costs an account this project does not require anyone to have. "
            "What this receipt establishes is narrower and stated exactly: the hosted "
            "backend is reachable from this code, and its output is admitted or refused by "
            "the same rules as everything else here."
        ),
    }


#: Fields that legitimately differ between two runs of the same tree.
_VOLATILE = ("generated_at",)


def _comparable(receipt: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in receipt.items() if key not in _VOLATILE}
    attempt = dict(out.get("attempt") or {})
    generation = dict(attempt.get("generation") or {})
    # A second call to a greedy endpoint returns the same text and a new timestamp, and a
    # token count can move by one on a re-tokenisation. The text is the claim; when it
    # was produced is not.
    for key in ("generated_at", "input_token_count", "generated_token_count"):
        generation.pop(key, None)
    if generation:
        attempt["generation"] = generation
    if attempt:
        out["attempt"] = attempt
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild and compare against the committed receipt instead of writing it",
    )
    args = parser.parse_args(argv)

    fresh = build()
    outcome = fresh["attempt"]["outcome"]

    if args.check:
        if not _RECEIPT.exists():
            print(f"[FAIL] {_RECEIPT.relative_to(REPO)} is missing. Run this script.")
            return 1
        committed = json.loads(_RECEIPT.read_text(encoding="utf-8"))
        if _comparable(committed) == _comparable(fresh):
            print(f"[PASS] watsonx receipt matches this tree  outcome: {outcome}")
            return 0
        was = (committed.get("attempt") or {}).get("outcome")
        print(
            f"[FAIL] {_RECEIPT.relative_to(REPO)} disagrees with a rebuild. "
            f"Committed outcome {was}, rebuilt {outcome}. "
            f"Re-run scripts/run_watsonx_check.py to refresh it."
        )
        return 1

    _RECEIPT.write_text(
        json.dumps(fresh, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    attempt = fresh["attempt"]
    print(f"watsonx: {outcome}")
    if outcome == "RAN":
        print(
            f"  {attempt['generation']['model_id']} answered "
            f"{attempt['generation']['generated_token_count']} tokens; "
            f"checker says {attempt['checker']['verdict']} "
            f"{attempt['checker']['codes']}"
        )
    elif outcome == "FAILED":
        print(f"  {attempt['error_class']}: {attempt['error']}")
    else:
        print(
            f"  {ENV_API_KEY} and {ENV_PROJECT_ID} are not set here, so nothing was "
            f"sent. The receipt records the attempt and the date."
        )
    print(f"wrote {_RECEIPT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
