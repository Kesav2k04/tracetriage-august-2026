"""Every public number must come from a generated artifact, not a keyboard.

Two checks, and the difference between them is the whole point of this file.

``test_readme_has_no_unbacked_numbers`` is a presence check: every metric quoted in
the README results tables must have a row in ``docs/CLAIM_REGISTER.md``. It says
nothing about the value. Its docstring used to claim otherwise ("the value quoted in
README.md must equal the value in the artifact the row points at"), and the test
ended at ``assert cells[0] in registered``, so the AUC row could be changed from
0.875 to 0.999 and the whole suite stayed green. A test whose docstring overstates it
is worse than an absent test, because it is why nobody looked here.

``test_every_registered_claim_matches_its_artifact`` is the value check that was
missing, marked xfail against a task that had already passed. Every number quoted in
a results row must appear in the artifact that row cites, at the precision it is
quoted to. What that catches: a number edited by hand, a number carried over after
the model was retrained, a receipt regenerated while the prose stayed. What it cannot
catch, stated because a limit nobody wrote down is a limit nobody remembers: a number
that coincidentally appears elsewhere in the same artifact, a claim whose receipt is
an image, and a wrong number that happens to round to a right one.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")

# Rows whose value cannot be compared against a JSON field, with the reason. This is
# a closed list, asserted by name below: a new unresolvable row fails the test rather
# than quietly leaving the compared set.
_UNCOMPARABLE = {
    "Strongest corrected match": "receipt is an overlay PNG",
    "Strongest uncorrected match": "receipt is an overlay PNG",
    "Human minutes per confirmed finding": "gate 4 was never run; the cell is prose",
    "Blinded human decidability rate": "gate 4 was never run; the cell is prose",
}

# Measured on 2026-08-19: 15 rows, 49 numbers. The floors sit just below that, so
# losing a whole row or a third of the numbers fails here instead of passing over a
# table that quietly stopped being checked.
_MIN_ROWS = 14
_MIN_NUMBERS = 45


def _results_section(readme: str) -> str:
    section = re.search(r"## Measured results(.*?)(?=\n## (?!#))", readme, re.S)
    assert section, "README lost its Measured results section"
    return section.group(1)


def _numbers_in(text: str) -> list[str]:
    """Numeric literals in the order they appear, thousands separators removed."""
    out: list[str] = []
    for match in _NUMBER.finditer(text):
        token = match.group(0).rstrip(".").replace(",", "")
        if token and token not in out:
            out.append(token)
    return out


def _numeric_leaves(node: object, acc: list[float]) -> None:
    """Every number in an artifact's summary, excluding its per-record rows.

    Strings are read because several receipts carry a formatted interval or a
    sentence quoting their own numbers, and a claim citing one of those is still
    citing the artifact.

    Per-record rows are read as well, and that is this check's weakness rather than an
    oversight. PHYSICS_VALIDATION.json carries 200 per-observation records of four
    numbers each, so almost any three-decimal value can be found somewhere in it: the
    README quoted a median of 0.21 and a p99 of 0.61 against an artifact whose
    distribution says 0.2249 and 0.5276, and both stale figures matched some row.
    Excluding record arrays was tried and it produces false alarms instead, because
    FUSION_RECEIPT.json keeps its per-split summaries in an array of objects too and
    the selective-risk claim really does cite one point of a curve. So this stays the
    broad net, and the exact checks are elsewhere:
    sync_readme_results.py --check for the generated table, and
    test_established_claims_are_derived_from_their_artifacts below for the
    hand-written one.
    """
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        acc.append(float(node))
    elif isinstance(node, dict):
        for value in node.values():
            _numeric_leaves(value, acc)
    elif isinstance(node, list):
        for value in node:
            _numeric_leaves(value, acc)
    elif isinstance(node, str):
        for token in _numbers_in(node):
            try:
                acc.append(float(token))
            except ValueError:
                continue


def _found(quoted: str, pool: list[float]) -> bool:
    """Is a quoted number present in the artifact at the precision it is quoted to?

    Comparison is at the quoted precision, not exact: the README rounds. A percentage
    quoted against a stored fraction counts as found, because "99.5% within 1 deg" and
    0.995 are the same measurement written two ways.
    """
    try:
        value = float(quoted)
    except ValueError:
        return False
    decimals = len(quoted.split(".")[1]) if "." in quoted else 0
    for candidate in pool:
        if round(candidate, decimals) == round(value, decimals):
            return True
        if round(candidate * 100, decimals) == round(value, decimals):
            return True
    return False


def _resolve(receipt_cell: str) -> Path | None:
    """The artifact a receipt cell points at, or None if it names no file.

    The cell is a code span, sometimes followed by the sub-object the claim reads
    ("`FUSION_RECEIPT.json` gate5"), and sometimes a bare filename under artifacts/.
    """
    span = re.search(r"`([^`]+)`", receipt_cell)
    if not span:
        return None
    path = span.group(1).strip()
    target = REPO / path
    if not target.exists() and "/" not in path:
        target = REPO / "artifacts" / path
    return target if target.exists() else None


def _rows(readme: str) -> list[tuple[str, str, str]]:
    rows = []
    for line in _results_section(readme).splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Metric", ""):
            continue
        rows.append((cells[0], cells[1], cells[2]))
    return rows


def compare(readme: str) -> dict[str, object]:
    """Compare every quoted number against its cited artifact.

    Returns the counts and the misses rather than asserting, so the test below can
    assert on them and a second test can prove the comparison actually bites.
    """
    compared_rows = 0
    compared_numbers = 0
    misses: list[str] = []
    uncomparable: list[str] = []
    for metric, value, receipt in _rows(readme):
        target = _resolve(receipt)
        if target is None or target.suffix != ".json":
            uncomparable.append(metric)
            continue
        quoted = _numbers_in(value)
        if not quoted:
            uncomparable.append(metric)
            continue
        pool: list[float] = []
        _numeric_leaves(json.loads(target.read_text(encoding="utf-8")), pool)
        compared_rows += 1
        compared_numbers += len(quoted)
        for number in quoted:
            if not _found(number, pool):
                misses.append(
                    f"{metric}: README quotes {number} but it does not appear in "
                    f"{target.relative_to(REPO).as_posix()}"
                )
    return {
        "rows": compared_rows,
        "numbers": compared_numbers,
        "misses": misses,
        "uncomparable": uncomparable,
    }


def test_readme_has_no_unbacked_numbers():
    """Presence only: every quoted metric has a row in the claim register.

    This checks the label, never the value. The value is checked by
    ``test_every_registered_claim_matches_its_artifact`` below.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    register = REPO / "docs" / "CLAIM_REGISTER.md"
    registered = register.read_text(encoding="utf-8") if register.exists() else ""

    for metric, value, _ in _rows(readme):
        if value.strip("`") == "[UNMEASURED]":
            continue
        assert metric in registered, (
            f"README quotes {metric!r} = {value!r} but that metric has no row in "
            f"docs/CLAIM_REGISTER.md. Generate the receipt or revert the number."
        )


def test_every_registered_claim_matches_its_artifact():
    """Every number in the results tables is in the artifact its row cites."""
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    result = compare(readme)

    assert not result["misses"], "README numbers not found in their receipts:\n  " + "\n  ".join(
        result["misses"]  # type: ignore[arg-type]
    )
    # A comparison that compared nothing would pass the assertion above. These are
    # what stop that: the counts, and the closed list of rows that cannot be compared.
    assert result["rows"] >= _MIN_ROWS, (
        f"only {result['rows']} rows were compared, below the {_MIN_ROWS} measured on "
        "2026-08-19. A row that stopped being checkable has to be explained, not lost."
    )
    assert result["numbers"] >= _MIN_NUMBERS, (
        f"only {result['numbers']} numbers were compared, below the {_MIN_NUMBERS} "
        "measured on 2026-08-19."
    )
    assert set(result["uncomparable"]) == set(_UNCOMPARABLE), (  # type: ignore[arg-type]
        "the set of rows that cannot be compared changed. Now: "
        f"{sorted(set(result['uncomparable']))}. Expected: {sorted(_UNCOMPARABLE)}. "
        "Each one needs a reason in _UNCOMPARABLE, because an exemption with no "
        "reason outlives the reason."
    )


def test_the_generated_table_is_what_the_receipts_produce():
    """The exact check: regenerate the table and compare it to the committed one.

    scripts/sync_readme_results.py writes the "Measured, with receipts" table from
    FUSION_RECEIPT.json and QUEUE_RECEIPT.json. Until D3 nothing ran it in check mode,
    so the table was correct only while someone remembered to run it. This is stronger
    than the number search above, because it compares the rendered row rather than
    asking whether a number appears somewhere in a large receipt.
    """
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "sync_readme_results.py"), "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, (
        "README results are stale against the receipts: "
        + (proc.stdout or proc.stderr)
    )


def test_the_comparison_catches_an_edited_number():
    """The reviewer's mutation, as a test.

    They changed the AUC row from 0.875 to 0.999 and 0.842 to 0.111, ran the drift
    test, and it passed, then ran the whole suite, and it passed. This is the check
    that now fails on exactly that edit.
    """
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "| 0.875, against 0.842 image-only |" in readme, (
        "the AUC row moved; point this test at whatever row now quotes a fitted number"
    )
    mutated = readme.replace(
        "| 0.875, against 0.842 image-only |",
        "| 0.999, against 0.111 image-only |",
        1,
    )
    result = compare(mutated)
    # 0.999 is caught. 0.111 is not, and that is measured rather than assumed: some
    # value in FUSION_RECEIPT.json rounds to 0.111 at three decimals, so "appears
    # anywhere in the cited artifact" cannot separate it from a real reading. This is
    # the collision named in the module docstring, and it is why the exact check is
    # scripts/sync_readme_results.py --check, which regenerates the row from the
    # receipt and compares text: that one catches both. This test pins the weaker net
    # that also covers the hand-written table above the generated one.
    assert result["misses"], "an edited number was not caught at all"
    assert any("0.999" in m for m in result["misses"])  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# The exact check for the hand-written table: recompute, do not search.
#
# The number search above is a broad net over a large receipt, and the generated
# table has sync_readme_results.py --check. The "Established, with receipts" table
# had neither, and it drifted: commit 0f21ce7 measured a median of 0.2082 and a p99
# of 0.6060, the README quoted 0.21 and 0.61, then commit 7fbb980 (the C7 geodetic
# normal fix) regenerated the artifact to 0.2249 and 0.5276 and neither the README nor
# the register moved. Both stale figures passed the search, because a 200-row receipt
# contains almost any three-decimal number somewhere. These recompute the claim.
# ---------------------------------------------------------------------------

_A3_SUMMARY = REPO / "artifacts" / "a3_overlays" / "summary.json"
_PHYSICS = REPO / "artifacts" / "PHYSICS_VALIDATION.json"


def _established_row(metric: str) -> str:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    for name, value, _ in _rows(readme):
        if name == metric:
            return value
    raise AssertionError(f"README has no row named {metric!r}")


def test_established_claims_are_derived_from_their_artifacts():
    """Recompute all six checkable established claims and compare to the README."""
    a3 = json.loads(_A3_SUMMARY.read_text(encoding="utf-8"))
    verdicts = [r["verdict"] for r in a3]
    n_corrected = verdicts.count("CORRECTED")
    n_uncorrected = verdicts.count("UNCORRECTED")
    n_unresolved = verdicts.count("UNRESOLVED")

    row = _established_row("Corrected and uncorrected captures both occur")
    assert f"{n_corrected} corrected" in row
    assert f"{n_uncorrected} uncorrected" in row
    assert f"{n_unresolved} undecidable" in row
    assert f"of {len(a3)} vetted" in row
    assert n_corrected + n_uncorrected + n_unresolved == len(a3), (
        "the three verdicts no longer partition the pool, so the row's arithmetic is "
        "no longer the artifact's"
    )

    # Metadata cannot reveal correction status.
    ports = {str(r.get("rigctl-port")) for r in a3}
    dopplers = {r.get("doppler-correction-per-sec") for r in a3}
    row = _established_row("Metadata cannot reveal correction status")
    assert ports == {"4532"}, f"rigctl-port is no longer constant: {sorted(ports)}"
    assert dopplers == {None}, "doppler-correction-per-sec is no longer always null"
    assert "4532" in row and f"on {len(a3)} of {len(a3)}" in row

    # The two strongest matches. The README cites the overlay PNG, and the numbers
    # come from the summary beside it, which is what makes them checkable at all.
    strongest_corrected = max(a3, key=lambda r: r["sigma_vertical"])
    row = _established_row("Strongest corrected match")
    assert f"{strongest_corrected['sigma_vertical']:.1f} sigma" in row
    assert f"{strongest_corrected['sigma_curved']:.1f}" in row
    assert strongest_corrected["verdict"] == "CORRECTED"

    strongest_uncorrected = max(a3, key=lambda r: r["sigma_curved"])
    row = _established_row("Strongest uncorrected match")
    assert f"{strongest_uncorrected['sigma_curved']:.1f} sigma" in row
    assert f"{strongest_uncorrected['sigma_vertical']:.1f}" in row
    assert strongest_uncorrected["verdict"] == "UNCORRECTED"

    # The unresolved pool and its score range. The range is over every score the 17
    # observations produced, both orientations, which is the reading the row states:
    # the best-per-observation range starts at 0.98 rather than 0.7.
    unresolved = [r for r in a3 if r["verdict"] == "UNRESOLVED"]
    scores = [v for r in unresolved for v in (r["sigma_vertical"], r["sigma_curved"])]
    row = _established_row("Observations with no measurable narrowband trace")
    assert f"{len(unresolved)} of {len(a3)}" in row
    assert f"{min(scores):.1f} to {max(scores):.1f} sigma" in row, (
        f"the row quotes a range the artifact no longer holds: measured "
        f"{min(scores):.1f} to {max(scores):.1f}"
    )

    # The physics validation, which is the row that drifted.
    dist = json.loads(_PHYSICS.read_text(encoding="utf-8"))["distribution"]
    row = _established_row("Pass geometry against reported max_altitude")
    assert f"median {dist['median_abs_error_deg']:.2f} deg" in row, (
        f"README quotes a median the artifact does not: artifact says "
        f"{dist['median_abs_error_deg']:.4f}"
    )
    assert f"p99 {dist['p99_abs_error_deg']:.2f} deg" in row, (
        f"README quotes a p99 the artifact does not: artifact says "
        f"{dist['p99_abs_error_deg']:.4f}"
    )
    assert f"{dist['pct_within_1deg']:.1f}% within 1 deg" in row
    assert f"{dist['n_success']} of {dist['n_total']}" in row


def test_the_elevation_reference_is_declared_as_quantised():
    """The artifact must say what its reference can resolve.

    Every max_altitude in the corpus is an integer, so a mean absolute error of 0.243
    degrees is close to the 0.250 that pure rounding would produce on its own. Read as
    agreement to a quarter of a degree it claims a resolution the reference does not
    have, and it is the reason the elevation check could not see the geocentric
    up-vector defect at all: 1.4 sigma in the mean and a variance ratio of 1.035.
    """
    dist = json.loads(_PHYSICS.read_text(encoding="utf-8"))["distribution"]
    quant = dist.get("reference_quantisation")
    assert quant, "PHYSICS_VALIDATION.json does not state its reference quantisation"
    assert quant["n_reported"] > 0
    assert quant["n_integer_valued"] == quant["n_reported"]
    assert quant["all_integer"] is True
    assert "cannot resolve anything finer" in quant["implication"]


def test_the_azimuth_agreement_is_measured_and_scaled():
    """The unrounded check the recon required, with the counterfactuals that scale it.

    rise_azimuth and set_azimuth are present on every record and were never validated
    against, although docs/SATNOGS_API_RECON.md required it. They are the only
    independent check on the azimuth convention and the local East/North/Up basis.
    """
    az = json.loads(_PHYSICS.read_text(encoding="utf-8"))["azimuth_agreement"]
    for key in ("rise", "set"):
        d = az[key]
        assert d["n"] >= 200, f"{key}: only {d['n']} records compared"
        assert d["median_abs_deg"] < 0.5, f"{key}: median {d['median_abs_deg']}"
        assert d["pct_within_3deg"] == 100.0, (
            f"{key}: {d['pct_within_3deg']}% within 3 deg"
        )

    # Without these the agreement has no scale. Both are convention errors a reader
    # might suspect, and both are two orders of magnitude worse than the shipped one.
    swapped = az["counterfactuals"]["atan2_arguments_swapped"]
    mirrored = az["counterfactuals"]["azimuth_mirrored_about_north"]
    assert swapped["median_abs_deg"] > 50.0, swapped["median_abs_deg"]
    assert mirrored["median_abs_deg"] > 10.0, mirrored["median_abs_deg"]
    assert swapped["median_abs_deg"] > 100 * az["rise"]["median_abs_deg"]
