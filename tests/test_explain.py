"""The grounding checker, measured in both directions (unit E1).

A checker that refuses every draft catches every adversarial one, and a checker that
accepts every draft catches none. Reporting only the first number would make a broken
implementation look perfect, so both sets run here: the drafts that each break one rule
have to be caught, and the drafts that break nothing have to pass.

The live model is not called. One test is marked ``llm`` and excluded from the offline
gate; everything else runs against the committed console data and a fixture, which is the
same arrangement the OCR-dependent tests use.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from pipeline.tracetriage.explain import (
    _NUMBER_RE,
    ADVERSARIAL_DRAFTS,
    CONTROL_DRAFTS,
    MAX_CHARS,
    _grounded_number,
    build_packet,
    build_prompt,
    control_drafts,
    deterministic_note,
    prompt_contract_sha256,
    verify_note,
)

REPO = Path(__file__).resolve().parents[1]
_DATA = REPO / "apps" / "web" / "public" / "data"


def _cards_and_entries() -> tuple[list[dict], dict[int, dict]]:
    cards = json.loads((_DATA / "cards.json").read_text(encoding="utf-8"))["cards"]
    entries = json.loads((_DATA / "queue.json").read_text(encoding="utf-8"))["entries"]
    by_id = {int(e["obs_id"]): e for e in entries}
    return [c for c in cards if int(c["obs_id"]) in by_id], by_id


@pytest.fixture(scope="module")
def packets():
    cards, by_id = _cards_and_entries()
    assert cards, "no console card has a queue entry, so nothing could be grounded"
    return [build_packet(c, by_id[int(c["obs_id"])]) for c in cards]


# ---------------------------------------------------------------------------
# The packet
# ---------------------------------------------------------------------------


def test_a_packet_refuses_a_mismatched_pair():
    cards, by_id = _cards_and_entries()
    other = next(e for e in by_id.values() if int(e["obs_id"]) != int(cards[0]["obs_id"]))
    with pytest.raises(ValueError, match="grounded in neither"):
        build_packet(cards[0], other)


def test_every_packet_carries_the_fields_a_note_needs(packets):
    required = {
        "network_label",
        "model_probability",
        "queue_rank",
        "queue_reason_codes",
        "fitted_offset_hz",
        "sigma_curved",
        "sigma_vertical",
        "max_elevation_deg",
    }
    for packet in packets:
        missing = sorted(required - set(packet.printed))
        assert not missing, f"observation {packet.obs_id} packet is missing {missing}"


def test_the_prompt_carries_the_packet_and_nothing_else_changes(packets):
    prompt = build_prompt(packets[0])
    assert packets[0].as_text() in prompt
    # The instruction text is versioned by digest, so a silent edit is detectable.
    assert len(prompt_contract_sha256()) == 64
    for rule in ("Do not introduce any number", "At most four sentences"):
        assert rule in prompt


# ---------------------------------------------------------------------------
# The checker, in both directions
# ---------------------------------------------------------------------------


def test_the_deterministic_note_passes_its_own_checker(packets):
    """The fallback has to be publishable, or refusal has nothing to fall back to.

    This is also the strongest available test of the checker's calibration: the template
    is built by format string from the packet, so every number in it is grounded by
    construction. Any violation reported here is the checker's fault, not the note's.
    """
    for packet in packets:
        note = deterministic_note(packet)
        result = verify_note(note, packet)
        assert result.ok, f"observation {packet.obs_id}: {result.violations}"
        assert len(note) <= MAX_CHARS, f"{len(note)} characters"


@pytest.mark.parametrize("draft,expected", ADVERSARIAL_DRAFTS)
def test_a_draft_with_a_known_defect_is_caught(draft, expected, packets):
    result = verify_note(draft, packets[0])
    assert not result.ok, f"the checker accepted a draft that breaks {expected}"
    assert expected in result.codes, (
        f"caught the draft but reported {result.codes} instead of {expected}, so the "
        f"receipt would attribute the refusal to the wrong rule"
    )


def test_a_clean_draft_is_not_refused(packets):
    """Without this, refusing everything would score perfectly on the set above.

    Run against every packet, not just the first, because the frequency control is
    formatted from the packet and a conversion that only works for one observation is not
    a working conversion.
    """
    for packet in packets:
        for draft in control_drafts(packet):
            result = verify_note(draft, packet)
            assert result.ok, (
                f"observation {packet.obs_id} refused a grounded draft for "
                f"{result.violations}: {draft[:80]!r}"
            )


def test_the_checker_is_not_vacuous():
    """Both suites have to be non-trivial and the codes they cover have to be distinct."""
    assert len(ADVERSARIAL_DRAFTS) >= 8
    assert len(CONTROL_DRAFTS) >= 3
    covered = {code for _, code in ADVERSARIAL_DRAFTS}
    assert covered >= {
        "UNGROUNDED_NUMBER",
        "UNGROUNDED_ENTITY",
        "OVERCLAIM",
        "ABSOLUTE_CLAIM",
        "WRONG_VOICE",
        "EMPTY",
        "TOO_MANY_SENTENCES",
    }, sorted(covered)


def test_a_number_from_another_observation_is_ungrounded(packets):
    """The check is per-observation, which is the case a global vocabulary would miss.

    This asserted only that the other observation's note was refused, which it was for the
    wrong reason: the differing label and reason codes raised UNGROUNDED_ENTITY, so stubbing
    the number check to accept everything left the test green. The assertion is now on the
    code, and it runs over every pair that differs numerically rather than the first two.
    """
    checked = 0
    for a in packets:
        for b in packets:
            if a.obs_id == b.obs_id:
                continue
            foreign = {
                literal
                for literal in _NUMBER_RE.findall(deterministic_note(b))
                if not _grounded_number(literal, "", a)
            }
            if not foreign:
                continue
            result = verify_note(deterministic_note(b), a)
            assert "UNGROUNDED_NUMBER" in result.codes, (
                f"observation {b.obs_id}'s note carries {sorted(foreign)}, which is not in "
                f"observation {a.obs_id}'s packet, and the checker did not say so: "
                f"{result.codes}"
            )
            checked += 1
    assert checked >= 20, f"only {checked} pairs differed numerically, so this proves little"


def test_a_percentage_is_allowed_and_an_invented_one_is_not(packets):
    packet = packets[0]
    pct = round(packet.exact["model_probability"] * 100.0)
    assert verify_note(f"The model puts this near {pct}% positive.", packet).ok
    wrong = (pct + 37) % 100
    assert not verify_note(f"The model puts this near {wrong}% positive.", packet).ok


# ---------------------------------------------------------------------------
# The verifier cannot reach the network
# ---------------------------------------------------------------------------


def _imports_of(path: Path) -> set[str]:
    """Modules named by an import in one file, relative forms included.

    ``from . import granite`` gives ``module=None`` with ``level=1``. A walker that guards
    on ``node.module`` skips it, which would make the closure check below blind to the one
    import it exists to forbid.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = ".".join(path.relative_to(REPO).with_suffix("").parts[:-1])
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = f"{package}.{base}" if base else package
            if base:
                found.add(base)
                for alias in node.names:
                    found.add(f"{base}.{alias.name}")
    return found


def _first_party_closure(entry: Path) -> tuple[set[str], set[Path]]:
    seen = {entry}
    found: set[str] = set()
    frontier = [entry]
    while frontier:
        current = frontier.pop()
        for module in _imports_of(current):
            found.add(module)
            if not module.startswith("pipeline"):
                continue
            candidate = REPO / Path(module.replace(".", "/") + ".py")
            if candidate.exists() and candidate not in seen:
                seen.add(candidate)
                frontier.append(candidate)
    return found, seen


def test_the_decision_to_publish_has_no_network_capability():
    """explain.py decides whether a generated note ships. It must not be able to fetch.

    The model call is a separate module imported by the runner. Folding it in here would
    put the code that can POST inside the closure of the code that judges its output,
    which is the arrangement this separation exists to prevent.
    """
    entry = REPO / "pipeline" / "tracetriage" / "explain.py"
    imports, files = _first_party_closure(entry)
    offenders = sorted(
        m
        for m in imports
        if m.split(".")[0] in {"httpx", "requests", "socket", "urllib", "http"}
        or "granite" in m
    )
    assert not offenders, f"explain.py's closure reaches {offenders}"

    # The closure is one file, and that is the claim rather than an accident of the walk:
    # explain.py imports the standard library and nothing else. Asserting the file count
    # says so, where a lower bound on the number of imports would have passed on the entry
    # file alone and read as a graph proof.
    assert files == {entry}, f"the closure grew to {sorted(p.name for p in files)}"
    first_party = sorted(m for m in imports if m.startswith("pipeline"))
    assert not first_party, f"explain.py now imports {first_party}; re-argue the closure"
    assert len(imports) >= 4, f"only {sorted(imports)} examined, so the walk found nothing"


# ---------------------------------------------------------------------------
# The loopback guard
# ---------------------------------------------------------------------------


def test_a_remote_model_endpoint_is_refused():
    """A literal off-machine address, so the test needs no resolver and no network."""
    from pipeline.tracetriage.granite import RemoteModelRefused, resolve_model_endpoint

    for bad in (
        "http://8.8.8.8:11434",
        "https://203.0.113.7/api",
        "http://[2001:db8::1]:11434",
        "ftp://127.0.0.1:11434",
        "http://:11434",
    ):
        with pytest.raises(RemoteModelRefused):
            resolve_model_endpoint(bad)


def test_a_loopback_endpoint_is_accepted():
    from pipeline.tracetriage.granite import resolve_model_endpoint

    for good in ("http://127.0.0.1:11434", "http://[::1]:11434"):
        assert resolve_model_endpoint(good) == good


# ---------------------------------------------------------------------------
# The live model, excluded from the offline gate
# ---------------------------------------------------------------------------


@pytest.mark.llm
def test_the_installed_model_produces_a_note_the_checker_judges(packets):
    """Not "produces a note that passes". Whether it passes is the measurement."""
    from pipeline.tracetriage.granite import ModelUnavailable, generate, model_identity

    try:
        identity = model_identity()
    except ModelUnavailable as exc:
        pytest.skip(str(exc))

    assert identity.name and identity.digest
    text = generate(build_prompt(packets[0]))
    result = verify_note(text, packets[0])
    # The assertion is that the checker reached a decision with reasons attached, which is
    # what the receipt records. A refusal here is data, not a failure.
    assert isinstance(result.ok, bool)
    assert result.ok or result.violations
