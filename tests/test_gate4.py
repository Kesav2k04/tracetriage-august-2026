"""The gate 4 instrument, tested where it could quietly stop being blinded (unit E6).

Gate 4 asks a human whether an image supports a judgment at all, and a study like that fails
in ways its own output cannot show: a sample chosen after the answers were known, a worksheet
that leaks the label it is meant to hide, a repeat sitting next to its twin so the reviewer
recognises it, an unfilled form scored as a failure. None of those produce an error. Each one
produces a number that reads fine.

Everything here runs from the console's tracked waterfalls rather than the snapshot, so the
whole file works in a clean clone with no 4 GB directory anywhere.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from build_gate4_worksheet import MIN_REPEAT_SEPARATION, THRESHOLD  # noqa: E402
from build_gate4_worksheet import main as build_main  # noqa: E402
from run_gate3 import rate_lower_bound, rate_upper_bound  # noqa: E402
from score_gate4 import (  # noqa: E402
    ScoringError,
    _one_axis_against_the_label,
    is_decisive,
    read_responses,
    read_reviewer,
    verify_commitments,
    why_not_run,
)
from score_gate4 import main as score_main  # noqa: E402

_SALT = "0" * 64
_PER_CLASS = 12
_REPEATS = 3


@pytest.fixture(scope="module")
def bundle(tmp_path_factory) -> dict:
    """One build, from the tracked console imagery, with a fixed salt so it is comparable."""
    out = tmp_path_factory.mktemp("gate4")
    manifest = out / "GATE4_WORKSHEET.json"
    code = build_main(
        [
            "--out",
            str(out),
            "--source",
            "console",
            "--per-class",
            str(_PER_CLASS),
            "--repeats",
            str(_REPEATS),
            "--salt",
            _SALT,
            "--manifest",
            str(manifest),
        ]
    )
    assert code == 0
    return {
        "dir": out,
        "manifest_path": manifest,
        "manifest": json.loads(manifest.read_text(encoding="utf-8")),
        "key": json.loads(
            (out / "KEY_do_not_open_until_scored.json").read_text(encoding="utf-8")
        ),
    }


def _write_responses(path: Path, answers: dict[str, tuple[str, str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["item", "artifact_usable", "visible_signal", "target_consistent", "notes"]
        )
        for item, row in answers.items():
            writer.writerow([item, *row, ""])


#: A complete declaration. The tests below that measure rates declare a human reviewer,
#: because that is the arm the gate is about and the one whose numbers land at the top level
#: of the receipt. The model arm has its own tests.
_HUMAN = {
    "kind": "human",
    "identity": "one reviewer, in the fixture",
    "procedure": "the worksheet, in order",
    "independence": "one sitting, no going back",
}


def _write_reviewer(path: Path, declared: dict[str, str] | None) -> Path:
    if declared is not None:
        path.write_text(json.dumps(declared), encoding="utf-8")
    return path


def _score(
    bundle: dict,
    answers: dict[str, tuple[str, str, str]],
    tmp_path: Path,
    reviewer: dict[str, str] | None = None,
) -> dict:
    responses = tmp_path / "responses.csv"
    receipt = tmp_path / "GATE4_RECEIPT.json"
    _write_responses(responses, answers)
    declaration = _write_reviewer(tmp_path / "REVIEWER.json", reviewer or _HUMAN)
    code = score_main(
        [
            "--bundle",
            str(bundle["dir"]),
            "--responses",
            str(responses),
            "--manifest",
            str(bundle["manifest_path"]),
            "--out",
            str(receipt),
            "--reviewer",
            str(declaration),
        ]
    )
    assert code == 0
    return json.loads(receipt.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The blinding
# ---------------------------------------------------------------------------


def test_the_committed_manifest_leaks_nothing_the_reviewer_must_not_see(bundle):
    """What is committed has to be inert on its own.

    A manifest carrying observation ids would let the reviewer look the pass up on the
    network's own site, and one carrying an unsalted image digest would be invertible in a
    minute against this repository's tracked waterfalls, which is the same defect wearing a
    different name.
    """
    text = bundle["manifest_path"].read_text(encoding="utf-8")
    cards = json.loads(
        (REPO / "apps" / "web" / "public" / "data" / "cards.json").read_text(encoding="utf-8")
    )["cards"]
    for card in cards:
        assert str(card["obs_id"]) not in text, f"the manifest names observation {card['obs_id']}"

    # The field-name scan runs over the data and not over the manifest's own account of what
    # it withholds. The first version scanned the whole file and failed on the sentence
    # "network's waterfall_status label" inside what_is_hidden_from_the_reviewer, which is the
    # disclosure rather than the leak. Dropping every prose field (a string, or a list of
    # them) keeps the scan pointed at values; the disclosure is asserted below, positively,
    # because a manifest that hides a field without saying so is worse than one that names it.
    def is_prose(value):
        if isinstance(value, str):
            return True
        return isinstance(value, list) and all(isinstance(item, str) for item in value)

    data = {
        key: value for key, value in bundle["manifest"].items() if not is_prose(value)
    }
    assert "commitments" in data, "the scan dropped the rows it exists to check"
    data_text = json.dumps(data)
    for leak in ("waterfall_status", "model_prob", '"label"', '"obs_id"', "image_sha256"):
        assert leak not in data_text, f"the manifest carries {leak}"

    hidden = " ".join(bundle["manifest"]["what_is_hidden_from_the_reviewer"]).lower()
    for named in ("waterfall_status", "model", "observation id", "repeats"):
        assert named in hidden, f"the manifest hides things without saying it hides {named}"

    # The class names appear once, as the keys of the availability count, which says how many
    # of each class the source held and not which item is which. Per item, only two fields
    # exist, and that is what has to stay true.
    for row in bundle["manifest"]["commitments"]:
        assert set(row) == {"item", "commitment"}, row

    for row in bundle["key"]["items"]:
        assert row["image_sha256"] not in text, (
            "an unsalted image digest is in the committed manifest, so the mapping can be "
            "inverted against the repository's own images"
        )


def test_every_commitment_verifies_and_a_changed_key_does_not(bundle):
    salt = bundle["key"]["salt"]
    for row, committed in zip(
        bundle["key"]["items"], bundle["manifest"]["commitments"], strict=True
    ):
        recomputed = hashlib.sha256(
            f"{salt}|{row['item']}|{row['obs_id']}|{row['image_sha256']}".encode()
        ).hexdigest()
        assert recomputed == committed["commitment"], row["item"]

    tampered = hashlib.sha256(
        f"{salt}|{bundle['key']['items'][0]['item']}|999999|x".encode()
    ).hexdigest()
    assert tampered != bundle["manifest"]["commitments"][0]["commitment"]


def test_a_tampered_key_is_refused_rather_than_scored(bundle, tmp_path):
    """The check that makes this a blinded study rather than a claim of one.

    A mapping chosen after the answers were known would produce a perfectly tidy receipt.
    This has to refuse, and refuse without writing one, which is why it is a hard exit and
    not the NOT_RUN branch.
    """
    forged = tmp_path / "KEY_forged.json"
    key = json.loads(json.dumps(bundle["key"]))
    key["items"][0]["obs_id"] = 999_999
    forged.write_text(json.dumps(key), encoding="utf-8")

    responses = tmp_path / "responses.csv"
    _write_responses(
        responses, {row["item"]: ("yes", "yes", "yes") for row in key["items"]}
    )
    receipt = tmp_path / "receipt.json"
    with pytest.raises(SystemExit) as caught:
        score_main(
            [
                "--bundle",
                str(bundle["dir"]),
                "--responses",
                str(responses),
                "--key",
                str(forged),
                "--manifest",
                str(bundle["manifest_path"]),
                "--out",
                str(receipt),
            "--reviewer",
            str(_write_reviewer(tmp_path / "REVIEWER.json", _HUMAN)),
            ]
        )
    assert "commitment" in str(caught.value)
    assert not receipt.exists(), "a refusal must not leave a receipt behind"


def test_a_repeat_is_the_same_image_and_never_lands_beside_its_twin(bundle):
    positions: dict[int, list[int]] = {}
    for index, row in enumerate(bundle["key"]["items"]):
        positions.setdefault(row["obs_id"], []).append(index)
    repeated = {obs: places for obs, places in positions.items() if len(places) > 1}
    assert len(repeated) == _REPEATS, f"{len(repeated)} observations repeat, expected {_REPEATS}"
    for obs, places in repeated.items():
        assert min(b - a for a, b in zip(places, places[1:], strict=False)) >= (
            MIN_REPEAT_SEPARATION
        ), f"observation {obs} appears at {places}"
        pixels = {bundle["key"]["items"][i]["pixel_sha256"] for i in places}
        assert len(pixels) == 1, "a repeat has to depict the same image, or it measures nothing"

    # The property that matters and the property that leaked are not the same one. Byte
    # identity was how the first version achieved pixel identity, and it handed the repeat
    # pairs to anyone with sha256sum: 45 files, 36 distinct digests, 9 groups of two, no salt
    # and no key needed. Intra-rater agreement is the number that breaks under that, upward,
    # and it is the ceiling this gate puts on its own decisive rate. So the files have to
    # differ, and what they depict has to not.
    files = sorted((bundle["dir"] / "images").glob("*.png"))
    assert len(files) == len(bundle["key"]["items"])
    byte_digests = {hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    assert len(byte_digests) == len(files), (
        "two images in the bundle are byte-identical, so hashing the directory recovers the "
        "repeat pairs without the key"
    )
    assert len({row["pixel_sha256"] for row in bundle["key"]["items"]}) == len(positions), (
        "the number of distinct pixel digests has to be the number of distinct observations"
    )


def test_the_committed_worksheet_is_balanced_and_says_what_was_available():
    """The balance assertions have to run against the real manifest, not only the fixture.

    The fixture builds from the console source, which has no unknown class, so every balance
    assertion below it was scoped to a two-class sample and none of them ever looked at the
    worksheet this repository commits to. A gate whose wording asks for a balanced sample
    should be checked on the sample it is committed to.
    """
    manifest = json.loads(
        (REPO / "artifacts" / "GATE4_WORKSHEET.json").read_text(encoding="utf-8")
    )
    available = manifest["observations_available_per_class"]
    requested = manifest["per_class_requested"]
    classes_with_stock = [name for name, count in available.items() if count > 0]
    assert classes_with_stock, "the committed manifest reports no observations at all"

    # What the sample can be, given what each class held. Asserting a perfectly balanced
    # sample would be asserting a property of the source: a clean clone with no snapshot has
    # 11 without-signal observations and no unknown class at all, so a --source console
    # rebuild is legitimately unbalanced. What has to hold either way is that the manifest's
    # own numbers account for it, so a reader can tell a short class from a quiet one.
    expected = sum(min(requested, available[name]) for name in classes_with_stock)
    assert manifest["unique_observations"] == expected, (
        f"{manifest['unique_observations']} unique observations against {expected} the "
        f"published availability allows, so the manifest does not account for its own sample"
    )
    assert manifest["items"] == expected + manifest["repeated_observations"]
    short = {name: available[name] for name in classes_with_stock if available[name] < requested}
    if not short:
        assert manifest["unique_observations"] == requested * len(classes_with_stock), (
            "every class had stock for the full request, so the committed sample has to be "
            "the balanced one the gate's wording asks for"
        )


def test_the_sample_is_balanced_and_records_what_it_could_not_balance(bundle):
    """The console source has no unknown class at all, and the manifest has to say so."""
    manifest = bundle["manifest"]
    assert manifest["source"] == "console"
    available = manifest["observations_available_per_class"]
    assert available["unknown"] == 0, (
        "the console ships imagery only for decisively labelled observations, so a manifest "
        "claiming a balanced three-class sample from it would be false"
    )
    labels = [row["label"] for row in bundle["key"]["items"]]
    for name in ("with-signal", "without-signal"):
        # As many as were asked for, or every one the source had. The console holds 11
        # without-signal observations against a request for 12, and the manifest publishes
        # the availability so a smaller class reads as a property of the source.
        assert labels.count(name) >= min(_PER_CLASS, available[name]), (
            f"{name}: {labels.count(name)} sampled, {available[name]} available"
        )


def test_the_build_is_reproducible_from_the_seed_and_the_salt(bundle, tmp_path):
    manifest = tmp_path / "again.json"
    assert (
        build_main(
            [
                "--out",
                str(tmp_path / "bundle"),
                "--source",
                "console",
                "--per-class",
                str(_PER_CLASS),
                "--repeats",
                str(_REPEATS),
                "--salt",
                _SALT,
                "--manifest",
                str(manifest),
            ]
        )
        == 0
    )
    assert json.loads(manifest.read_text(encoding="utf-8")) == bundle["manifest"]


# ---------------------------------------------------------------------------
# The rule, and the three outcomes plus one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("artifact", "signal", "target", "expected"),
    [
        ("yes", "yes", "yes", True),
        ("yes", "no", "na", True),
        ("yes", "unsure", "no", True),
        ("no", "unsure", "unsure", True),  # a decisive artifact judgment is the gate's own
        ("yes", "unsure", "unsure", False),
        ("yes", "unsure", "na", False),  # na is not a judgment about the signal
        ("unsure", "yes", "yes", False),  # an unreadable image cannot support a judgment
    ],
)
def test_the_decisive_rule_is_the_one_the_manifest_publishes(
    artifact, signal, target, expected
):
    assert (
        is_decisive(
            {
                "artifact_usable": artifact,
                "visible_signal": signal,
                "target_consistent": target,
            }
        )
        is expected
    )


def test_an_unfilled_worksheet_is_not_run_and_carries_no_rate(bundle, tmp_path):
    """The third outcome. Absence must not read as a failure or as silence."""
    receipt = _score(bundle, {}, tmp_path)
    assert receipt["verdict"] == "NOT_RUN"
    assert "rate" not in receipt
    assert receipt["threshold"] == THRESHOLD
    assert "not a failure" in receipt["reading"]


def test_all_three_measured_verdicts_are_reachable(bundle, tmp_path):
    """Every branch fired by construction, so none of them is dead code.

    The mixture is found by scanning rather than typed, because the number of decisive items
    that leaves the interval straddling the threshold depends on the sample size.
    """
    items = [row["item"] for row in bundle["key"]["items"]]
    by_observation: dict[int, list[str]] = {}
    for row in bundle["key"]["items"]:
        by_observation.setdefault(row["obs_id"], []).append(row["item"])
    trials = len(by_observation)

    straddling = next(
        (
            k
            for k in range(trials + 1)
            if (rate_lower_bound(k, trials) or 0) < THRESHOLD <= (rate_upper_bound(k, trials) or 0)
        ),
        None,
    )
    assert straddling is not None, "no count leaves the interval containing the threshold"

    def answers(decisive_observations: int) -> dict[str, tuple[str, str, str]]:
        chosen = list(by_observation)[:decisive_observations]
        out: dict[str, tuple[str, str, str]] = {}
        for obs, obs_items in by_observation.items():
            row = ("yes", "yes", "yes") if obs in chosen else ("yes", "unsure", "unsure")
            for item in obs_items:
                out[item] = row
        return out

    assert _score(bundle, answers(trials), tmp_path)["verdict"] == "PASSED"
    assert _score(bundle, answers(0), tmp_path)["verdict"] == "FAILED"
    middle = _score(bundle, answers(straddling), tmp_path)
    assert middle["verdict"] == "NOT_ESTABLISHED"
    assert middle["decisive"] == straddling
    assert middle["observations_scored"] == trials
    assert len(items) > trials, "the sample has to contain repeats for the next test"


def test_only_the_first_occurrence_of_an_observation_counts(bundle, tmp_path):
    """A reviewer who answers the repeat differently is not scored twice on one image.

    Counting both would let one observation move the gate's numerator by two, and the repeat
    exists to measure the reviewer against themselves rather than to add evidence.
    """
    by_observation: dict[int, list[str]] = {}
    for row in bundle["key"]["items"]:
        by_observation.setdefault(row["obs_id"], []).append(row["item"])
    repeated = {obs: items for obs, items in by_observation.items() if len(items) > 1}

    answers: dict[str, tuple[str, str, str]] = {}
    for obs, items in by_observation.items():
        for index, item in enumerate(sorted(items)):
            if obs in repeated and index == 1:
                answers[item] = ("yes", "unsure", "unsure")  # not decisive, second time
            else:
                answers[item] = ("yes", "yes", "yes")

    receipt = _score(bundle, answers, tmp_path)
    assert receipt["observations_scored"] == len(by_observation)
    assert receipt["decisive"] == len(by_observation), (
        "the second occurrence changed the decisive count, so an observation was scored twice"
    )
    intra = receipt["intra_rater"]
    assert intra["repeated_pairs_scored"] == len(repeated)
    assert intra["identical_on_all_three_axes"] == 0
    assert intra["per_axis"]["artifact_usable"]["identical"] == len(repeated)


def test_an_uninterpretable_answer_refuses_and_writes_nothing(bundle, tmp_path):
    responses = tmp_path / "responses.csv"
    _write_responses(
        responses,
        {bundle["key"]["items"][0]["item"]: ("probably", "yes", "yes")},
    )
    receipt = tmp_path / "receipt.json"
    with pytest.raises(SystemExit) as caught:
        score_main(
            [
                "--bundle",
                str(bundle["dir"]),
                "--responses",
                str(responses),
                "--manifest",
                str(bundle["manifest_path"]),
                "--out",
                str(receipt),
            "--reviewer",
            str(_write_reviewer(tmp_path / "REVIEWER.json", _HUMAN)),
            ]
        )
    assert "probably" in str(caught.value)
    assert not receipt.exists()


def test_the_receipt_reveals_what_a_reader_needs_to_verify_the_commitments(bundle, tmp_path):
    answers = {row["item"]: ("yes", "yes", "yes") for row in bundle["key"]["items"]}
    receipt = _score(bundle, answers, tmp_path)
    reveal = receipt["reveal"]
    assert reveal["salt"] == bundle["key"]["salt"]
    committed = {row["item"]: row["commitment"] for row in bundle["manifest"]["commitments"]}
    for row in reveal["items"]:
        recomputed = hashlib.sha256(
            f"{reveal['salt']}|{row['item']}|{row['obs_id']}|{row['image_sha256']}".encode()
        ).hexdigest()
        assert recomputed == committed[row["item"]]


def test_the_label_agreement_is_reported_and_is_not_the_gate(bundle, tmp_path):
    """The interesting number, kept out of the verdict on purpose."""
    answers = {row["item"]: ("yes", "yes", "na") for row in bundle["key"]["items"]}
    receipt = _score(bundle, answers, tmp_path)
    agreement = receipt["network_label_agreement"]
    labels = [row["label"] for row in bundle["key"]["items"]]
    # Everyone answered "signal present", so agreement is exactly the with-signal share of
    # the first occurrences, and the gate still passed on decisiveness alone.
    assert receipt["verdict"] == "PASSED"
    assert agreement["items_scored"] == receipt["observations_scored"]
    assert agreement["agreed_with_the_network_label"] < agreement["items_scored"], (
        f"every item was answered yes and the sample holds without-signal cases: {labels}"
    )
    assert "not gate 4" in agreement["reading"]


# ---------------------------------------------------------------------------
# The bounds
# ---------------------------------------------------------------------------


def test_the_exact_bounds_agree_with_their_closed_forms():
    """Gate 4 needed an upper bound, and a wrong one would invent a FAILED verdict."""
    for trials in (3, 10, 23, 45):
        assert rate_lower_bound(trials, trials) == pytest.approx(0.05 ** (1 / trials))
        assert rate_upper_bound(0, trials) == pytest.approx(1 - 0.05 ** (1 / trials))
        assert rate_lower_bound(0, trials) == 0.0
        assert rate_upper_bound(trials, trials) == 1.0
        for successes in range(trials + 1):
            lower = rate_lower_bound(successes, trials)
            upper = rate_upper_bound(successes, trials)
            rate = successes / trials
            assert lower <= rate + 1e-12
            assert rate - 1e-12 <= upper
            assert lower < upper


def test_the_verdict_rule_cannot_report_passed_and_failed_for_one_count():
    """The three branches partition the line, which is what makes the third one honest."""
    trials = 45
    seen = set()
    for successes in range(trials + 1):
        lower = rate_lower_bound(successes, trials)
        upper = rate_upper_bound(successes, trials)
        passed = lower >= THRESHOLD
        failed = upper < THRESHOLD
        assert not (passed and failed)
        seen.add("PASSED" if passed else "FAILED" if failed else "NOT_ESTABLISHED")
    assert seen == {"PASSED", "FAILED", "NOT_ESTABLISHED"}


def test_the_committed_receipt_and_worksheet_agree_with_each_other():
    """The real pair in this repository, rather than the fixtures above."""
    worksheet = REPO / "artifacts" / "GATE4_WORKSHEET.json"
    receipt = REPO / "artifacts" / "GATE4_RECEIPT.json"
    if not (worksheet.exists() and receipt.exists()):
        pytest.skip("the gate 4 instrument has not been built in this checkout")
    w = json.loads(worksheet.read_text(encoding="utf-8"))
    r = json.loads(receipt.read_text(encoding="utf-8"))
    assert r["threshold"] == w["threshold"]
    assert r["decisive_rule"] == w["decisive_rule"]
    assert r["verdict_rule"] == w["verdict_rule"]
    assert r["worksheet"]["items"] == w["items"]
    assert r["worksheet"]["seed"] == w["seed"]
    assert r["verdict"] in {"PASSED", "FAILED", "NOT_ESTABLISHED", "NOT_RUN"}
    if r["verdict"] == "NOT_RUN":
        assert "rate" not in r, "a receipt with no review must not carry a rate"


def test_the_worksheet_the_repository_commits_to_is_not_the_test_fixture():
    """A committed manifest built with the fixed test salt would not be a commitment at all."""
    worksheet = REPO / "artifacts" / "GATE4_WORKSHEET.json"
    if not worksheet.exists():
        pytest.skip("the gate 4 instrument has not been built in this checkout")
    text = worksheet.read_text(encoding="utf-8")
    assert _SALT not in text
    built_with_the_test_salt = hashlib.sha256(
        f"{_SALT}|G4-001|0|0".encode()
    ).hexdigest()
    assert built_with_the_test_salt not in text


def test_the_instrument_is_wired_into_the_gate_document():
    """A gate whose instrument exists and whose document still says OPEN with no path to it."""
    document = (REPO / "docs" / "KILL_GATE.md").read_text(encoding="utf-8")
    assert "scripts/build_gate4_worksheet.py" in document, (
        "docs/KILL_GATE.md does not tell a reader how to run gate 4, so the instrument is "
        "invisible from the document that declares the gate"
    )
    assert "scripts/score_gate4.py" in document


def test_the_bundle_is_never_committed():
    """The images and the key live outside the repository, and that is load-bearing."""
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for path in tracked:
        assert "KEY_do_not_open" not in path, f"the answer key is tracked at {path}"
        assert not path.startswith("artifacts/gate4"), f"the blind bundle is tracked at {path}"


def test_the_stimulus_is_rehashed_from_disk(bundle, tmp_path):
    """The commitment has to bind what the reviewer saw, not only who saw what.

    The first version hashed the digest the key carried, so every image in the bundle could be
    replaced and all 45 commitments still verified, while the error message blamed exactly that
    case. A preregistration that does not bind the stimulus is half a preregistration, so swap
    one file and the scorer must refuse.
    """
    images = tmp_path / "images"
    images.mkdir()
    for source in sorted((bundle["dir"] / "images").glob("*.png")):
        (images / source.name).write_bytes(source.read_bytes())
    victim = sorted(images.glob("*.png"))[0]
    victim.write_bytes(victim.read_bytes() + b"\x00")

    with pytest.raises(ScoringError) as caught:
        verify_commitments(bundle["manifest"], bundle["key"], images)
    assert "stimulus changed" in str(caught.value)

    # And the honest case still verifies, so the check is not simply always failing.
    assert verify_commitments(
        bundle["manifest"], bundle["key"], bundle["dir"] / "images"
    ) == len(bundle["key"]["items"])


def test_a_deleted_bundle_cannot_be_scored_as_verified(bundle, tmp_path):
    with pytest.raises(ScoringError) as caught:
        verify_commitments(bundle["manifest"], bundle["key"], tmp_path / "gone")
    assert "no images" in str(caught.value)


def test_one_item_answered_twice_is_refused_rather_than_deduplicated(bundle, tmp_path):
    """Building a dict from the rows keeps the last answer and says nothing."""
    responses = tmp_path / "responses.csv"
    item = bundle["key"]["items"][0]["item"]
    with responses.open("w", encoding="utf-8", newline="") as handle:
        handle.write("item,artifact_usable,visible_signal,target_consistent,notes\n")
        handle.write(f"{item},yes,yes,yes,\n")
        handle.write(f"{item},no,no,no,\n")
    with pytest.raises(ScoringError) as caught:
        read_responses(responses)
    assert "answered twice" in str(caught.value)


def test_a_key_that_is_not_json_refuses_instead_of_crashing(bundle, tmp_path):
    """By the script's own taxonomy an unreadable key is an instrument failure."""
    broken = tmp_path / "KEY_broken.json"
    broken.write_text("{not json", encoding="utf-8")
    responses = tmp_path / "responses.csv"
    _write_responses(
        responses, {row["item"]: ("yes", "yes", "yes") for row in bundle["key"]["items"]}
    )
    receipt = tmp_path / "receipt.json"
    with pytest.raises(SystemExit) as caught:
        score_main(
            [
                "--bundle",
                str(bundle["dir"]),
                "--responses",
                str(responses),
                "--key",
                str(broken),
                "--manifest",
                str(bundle["manifest_path"]),
                "--out",
                str(receipt),
            "--reviewer",
            str(_write_reviewer(tmp_path / "REVIEWER.json", _HUMAN)),
            ]
        )
    assert "not readable JSON" in str(caught.value)
    assert not receipt.exists()


def test_the_sample_size_can_establish_the_threshold_it_publishes():
    """The arithmetic that decides whether running the study can answer the question.

    A verdict read off an exact 95 percent lower bound needs a rate strictly above the
    threshold before PASSED is reachable at all. At 36 observations that rate is 0.944, so a
    corpus whose true decisive rate is 0.90 returns NOT_ESTABLISHED however the review goes.
    The committed sample has to be sized so the band a real corpus plausibly sits in can
    clear it, and the number that says so has to be computed rather than believed.
    """
    manifest = json.loads(
        (REPO / "artifacts" / "GATE4_WORKSHEET.json").read_text(encoding="utf-8")
    )
    sizing = manifest["what_this_sample_size_can_establish"]
    n = manifest["unique_observations"]
    assert sizing["unique_observations"] == n
    k = sizing["minimum_decisive_for_pass"]
    assert k is not None, "no number of decisive answers could reach PASSED at this size"
    assert rate_lower_bound(k, n) >= manifest["threshold"]
    assert rate_lower_bound(k - 1, n) < manifest["threshold"], (
        "minimum_decisive_for_pass is not minimal, so the published sizing overstates what "
        "this sample can conclude"
    )
    assert rate_upper_bound(sizing["maximum_decisive_for_fail"], n) < manifest["threshold"]
    assert sizing["lower_bound_if_the_true_rate_is_0.90"] >= manifest["threshold"], (
        f"at {n} observations a true decisive rate of 0.90 gives a lower bound of "
        f"{sizing['lower_bound_if_the_true_rate_is_0.90']}, which cannot establish "
        f"{manifest['threshold']}. The study would return NOT_ESTABLISHED by construction, "
        f"which is a sample size defect rather than a finding."
    )


def test_the_receipt_publishes_the_balance_and_the_sizing(bundle, tmp_path):
    receipt = _score(
        bundle,
        {row["item"]: ("yes", "yes", "yes") for row in bundle["key"]["items"]},
        tmp_path,
    )
    balance = receipt["sample_balance"]
    assert sum(balance["observations_per_class"].values()) == receipt["observations_scored"]
    assert balance["balanced"] is (balance["smallest_class"] == balance["largest_class"])
    assert receipt["worksheet"]["what_this_sample_size_can_establish"]["unique_observations"] == (
        bundle["manifest"]["unique_observations"]
    )
    assert "--salt" in receipt["worksheet"]["salt_source"] or "random" in (
        receipt["worksheet"]["salt_source"]
    )
    assert receipt["stimulus"]["images_rehashed_from_disk"] == len(bundle["key"]["items"])


def test_the_label_agreement_says_how_many_items_it_excluded(bundle, tmp_path):
    """It conditions on the reviewer's own confidence, which is the flattering direction."""
    items = [row["item"] for row in bundle["key"]["items"]]
    answers = {item: ("yes", "yes", "yes") for item in items}
    answers[items[0]] = ("yes", "unsure", "unsure")
    receipt = _score(bundle, answers, tmp_path)
    agreement = receipt["network_label_agreement"]
    assert agreement["items_excluded_reviewer_unsure"] >= 1
    assert "unsure" in agreement["reading"]
    assert (
        agreement["items_scored"]
        + agreement["items_excluded_reviewer_unsure"]
        + agreement["items_excluded_unknown_label"]
        == receipt["observations_scored"]
    ), "the exclusions and the scored items have to account for every observation"


def test_the_published_decisive_rule_names_what_the_code_reads():
    """Prose and behaviour drift apart silently, so the prose has to name the fields."""
    manifest = json.loads(
        (REPO / "artifacts" / "GATE4_WORKSHEET.json").read_text(encoding="utf-8")
    )
    rule = manifest["decisive_rule"]
    for field in ("artifact_usable", "visible_signal", "target_consistent"):
        assert field in rule, f"the published rule does not name {field}"
    assert "no" in rule and "yes" in rule
    # The two hard cases the code implements, stated in the prose a reader gets.
    assert is_decisive(
        {"artifact_usable": "no", "visible_signal": "unsure", "target_consistent": "unsure"}
    ), "an unusable artifact is itself the decisive judgment, and the rule says so"
    assert not is_decisive(
        {"artifact_usable": "yes", "visible_signal": "unsure", "target_consistent": "unsure"}
    ), "usable and then unsure on every axis supported no judgment, and the rule says so"


def test_the_manifest_states_what_the_blinding_does_not_cover():
    """A threat model that lists only the threats it defeats is an advertisement."""
    manifest = json.loads(
        (REPO / "artifacts" / "GATE4_WORKSHEET.json").read_text(encoding="utf-8")
    )
    limits = " ".join(manifest["what_the_blinding_does_not_cover"]).lower()
    assert "pixel" in limits, "the pixel-hash route to the repeat pairs is not disclosed"
    assert "console" in limits, (
        "a console-source bundle is invertible against the tracked waterfalls, and the "
        "manifest has to say so"
    )


def test_the_committed_manifest_is_not_silently_replaced(tmp_path):
    """A commitment that a later build can overwrite without saying so is not a commitment.

    The builder writes artifacts/GATE4_WORKSHEET.json by default, so a judge who runs it out
    of curiosity would replace the preregistration this repository is committed to and nothing
    would record that the sample had changed.
    """
    manifest = tmp_path / "GATE4_WORKSHEET.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        build_main(
            [
                "--out",
                str(tmp_path / "bundle"),
                "--source",
                "console",
                "--per-class",
                "8",
                "--repeats",
                "2",
                "--salt",
                _SALT,
                "--manifest",
                str(manifest),
            ]
        )
    assert "already committed" in str(caught.value)
    assert manifest.read_text(encoding="utf-8") == "{}", "the refusal still wrote over it"

    # And --force is a real path rather than a token in a help string.
    assert (
        build_main(
            [
                "--out",
                str(tmp_path / "bundle"),
                "--source",
                "console",
                "--per-class",
                "8",
                "--repeats",
                "2",
                "--salt",
                _SALT,
                "--manifest",
                str(manifest),
                "--force",
            ]
        )
        == 0
    )
    assert json.loads(manifest.read_text(encoding="utf-8"))["schema"] == "GATE4_WORKSHEET"


# ---------------------------------------------------------------------------
# Who reviewed
# ---------------------------------------------------------------------------


def test_a_rate_cannot_be_published_without_saying_who_produced_it(bundle, tmp_path):
    """The one number in this project that must never be anonymous.

    Everything else here guards the sample. Nothing guarded the reviewer, so a receipt
    carrying a decisive rate, an interval and an intra-rater figure read as a study
    whoever produced it. This makes the absence a refusal rather than a default.
    """
    answers = {row["item"]: ("yes", "yes", "yes") for row in bundle["key"]["items"]}
    responses = tmp_path / "responses.csv"
    receipt = tmp_path / "GATE4_RECEIPT.json"
    _write_responses(responses, answers)
    with pytest.raises(SystemExit) as caught:
        score_main(
            [
                "--bundle",
                str(bundle["dir"]),
                "--responses",
                str(responses),
                "--manifest",
                str(bundle["manifest_path"]),
                "--out",
                str(receipt),
                "--reviewer",
                str(tmp_path / "nothing-here.json"),
            ]
        )
    assert "no reviewer declaration" in str(caught.value)
    assert not receipt.exists(), "a refusal must not leave a receipt behind"


@pytest.mark.parametrize("dropped", sorted(_HUMAN))
def test_every_field_of_the_declaration_is_required(tmp_path, dropped):
    partial = {k: v for k, v in _HUMAN.items() if k != dropped}
    path = tmp_path / "REVIEWER.json"
    path.write_text(json.dumps(partial), encoding="utf-8")
    with pytest.raises(Exception) as caught:
        read_reviewer(path)
    assert dropped in str(caught.value)


def test_a_kind_the_scorer_has_no_handling_for_refuses(tmp_path):
    """Not a fallthrough. A third kind must stop the run rather than pick a branch."""
    path = tmp_path / "REVIEWER.json"
    path.write_text(json.dumps({**_HUMAN, "kind": "panel"}), encoding="utf-8")
    with pytest.raises(Exception) as caught:
        read_reviewer(path)
    assert "panel" in str(caught.value)


def test_a_model_review_keeps_the_gate_open_and_publishes_its_numbers_separately(
    bundle, tmp_path
):
    """The whole point of the split.

    A review by anything other than a person measures something real about the sample and
    does not measure the gate as titled. So the numbers are published, in `arm`, and the
    field every consumer reads does not move. No consumer has to know this distinction
    exists in order to avoid getting it wrong.
    """
    answers = {row["item"]: ("yes", "yes", "yes") for row in bundle["key"]["items"]}
    model = {**_HUMAN, "kind": "model", "identity": "a language model, named"}
    receipt = _score(bundle, answers, tmp_path, reviewer=model)

    assert receipt["verdict"] == "NOT_RUN"
    assert "not by a person" in receipt["why"]
    assert receipt["arm"]["verdict"] == "PASSED", "the measured arm keeps its own verdict"
    assert receipt["arm"]["reviewer"]["kind"] == "model"
    assert "rate" not in receipt, "no rate may sit where a human rate would"
    assert receipt["arm"]["rate"] == 1.0

    human = _score(bundle, answers, tmp_path)
    assert human["verdict"] == "PASSED"
    assert human["rate"] == 1.0
    assert "arm" not in human, "a human review is the gate, not an arm of it"
    assert human["reviewer"]["kind"] == "human"


def test_the_committed_receipt_says_who_reviewed_it_if_anyone_did():
    """The tracked receipt, not a fixture. Either nobody has reviewed, or it says who."""
    receipt = json.loads(
        (REPO / "artifacts/GATE4_RECEIPT.json").read_text(encoding="utf-8")
    )
    if receipt["verdict"] == "NOT_RUN" and "arm" not in receipt:
        assert "reviewer" not in receipt, "nothing was reviewed, so nobody may be named"
        return
    named = receipt.get("reviewer") or receipt["arm"]["reviewer"]
    for field in ("kind", "identity", "procedure", "independence"):
        assert str(named.get(field) or "").strip(), f"the receipt names no {field}"
    if named["kind"] != "human":
        assert receipt["verdict"] == "NOT_RUN", (
            "gate 4 is titled blinded human decidability and this reviewer is not a "
            "person, so the gate's own verdict must stay open"
        )


def test_the_label_agreement_reports_both_axes_and_claims_neither_is_the_question(
    bundle, tmp_path
):
    """Two comparisons, and the receipt refuses to nominate one as the right one.

    The first version published one rate, on `visible_signal`, and it read as "the silver
    labels are this often wrong". It is not that: `visible_signal` counts a fixed local
    carrier and the network label does not. Adding `target_consistent` did not fix that, it
    swapped it, because that axis wants a drifting curve and a packet burst near zero offset
    is a real pass that answers no. Both directions are measurable and this asserts both are
    reported.
    """
    answers = {}
    for row in bundle["key"]["items"]:
        # Every plate: a trace is visible, and none of them is pass-shaped. Against a
        # balanced sample that has to disagree with the network in both directions at once,
        # which is exactly the shape the two axes cannot both describe.
        answers[row["item"]] = ("yes", "yes", "no")
    agreement = _score(bundle, answers, tmp_path)["network_label_agreement"]

    assert "neither_axis_asks_the_network_question" in agreement
    assert "closest" not in json.dumps(agreement), (
        "no field may nominate one axis as the network's question, because the measurement "
        "says both miss it"
    )
    by_axis = agreement["by_axis"]
    assert set(by_axis) == {"visible_signal", "target_consistent"}
    for axis, block in by_axis.items():
        assert block["axis"] == axis
        assert block["items_scored"] >= 1
        assert block["confusion_network_label_to_human"]

    # visible_signal calls everything with-signal, so it agrees on exactly the plates the
    # network calls with-signal. target_consistent calls everything without-signal, so it
    # agrees on exactly the complement. The two rates must therefore sum to 1.
    assert by_axis["visible_signal"]["rate"] + by_axis["target_consistent"]["rate"] == 1.0

    # And the top level stays the visible_signal pair, because the console and the sync
    # scripts read those names.
    assert agreement["rate"] == by_axis["visible_signal"]["rate"]
    assert agreement["items_scored"] == by_axis["visible_signal"]["items_scored"]


def test_na_on_the_target_axis_is_a_committed_answer_not_an_exclusion():
    """`na` means there was nothing in the frame to judge, which is a without-signal verdict.

    Counting it as unsure would drop every empty plate out of the comparison, and empty
    plates are half of what a balanced sample is for.
    """
    key = {"G4-001": {"label": "without-signal"}, "G4-002": {"label": "with-signal"}}
    answers = {
        "G4-001": {"artifact_usable": "yes", "visible_signal": "no", "target_consistent": "na"},
        "G4-002": {"artifact_usable": "yes", "visible_signal": "yes", "target_consistent": "yes"},
    }
    block = _one_axis_against_the_label(answers, key, "target_consistent", "yes")
    assert block["items_scored"] == 2
    assert block["items_excluded_reviewer_unsure"] == 0
    assert block["agreed_with_the_network_label"] == 2


def test_the_committed_receipt_still_says_what_its_generator_says() -> None:
    """The one field in this receipt that no checkout can re-derive by running the scorer.

    Scoring gate 4 needs the bundle: the plates, the response file and the reviewer
    declaration, none of which are in the repository, because the plates are the sample
    itself and the declaration names a reviewer rather than a setting. So the receipt is a
    committed artifact whose builder cannot be run here, and the sentence explaining why a
    measured review still leaves the gate open was typed into the receipt by a run nobody
    can repeat.

    `why_not_run` is a pure function of the reviewer declaration the receipt already
    carries, so that one field can be re-derived without the bundle. It is checked because
    it drifted once: the template appended a full stop to an identity that ended in one and
    the receipt carried a double stop for four days.
    """
    receipt = json.loads(
        (REPO / "artifacts" / "GATE4_RECEIPT.json").read_text(encoding="utf-8")
    )
    if receipt["verdict"] != "NOT_RUN":
        pytest.skip(
            f"the committed verdict is {receipt['verdict']}, so this receipt was not "
            "written by the NOT_RUN branch this checks"
        )
    assert receipt["why"] == why_not_run(receipt["arm"]["reviewer"]), (
        "the receipt's `why` is not what scripts/score_gate4.py would write from the "
        "reviewer declaration the same receipt carries"
    )
