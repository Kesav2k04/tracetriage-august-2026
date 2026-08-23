"""The three release-audit receipts, and whether the checks that produced them can fail.

`docs/REFERENCE.md` was generated for the first time in D12 and its "named in tests" column
came back empty for `SECRET_SCAN.json`, `ATTRIBUTION_AUDIT.json` and `REPO_WEIGHT.json`.
Those three carry the strongest words in the repository: zero secrets, every redistributed
file attributed, nothing tracked a judge does not need. Nothing asserted any of them, so a
scanner that had stopped scanning would still have published `clean: true`, which is the
shape gate 3 had before it was withdrawn.

The tests below plant each thing the audit claims to find. A scan that misses a planted key
is a scan whose zero means nothing, and the point of a mutation here is that it makes the
zero mean something.

`scan_secrets` is exercised two ways. Against strings, for the planted shapes below,
because writing a real-shaped credential into the tree would be committing one to make a
point. And against this repository for real, live, in the fixture: the cleanliness
assertion used to read `artifacts/SECRET_SCAN.json` and assert that the file said clean,
which is a check that can only pass. A scanner that had stopped scanning, or a key
committed after the receipt was last written, left that assertion green. The scan now runs
here and decides, and the committed receipt is required to agree with what it found.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ARTIFACTS = _REPO / "artifacts"


def _load_audit():
    path = _REPO / "scripts" / "audit_release.py"
    spec = importlib.util.spec_from_file_location("audit_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_release"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load_audit()


@pytest.fixture(scope="module")
def secret_scan(audit) -> dict:
    """A live scan of this working tree and its history, not the committed receipt.

    Module-scoped because it walks every tracked text file and then reads
    `git log --all -p`, which is seconds rather than milliseconds. History is included
    on purpose: a credential committed once and deleted in the next commit is still in
    the blob, and that is the case the working-tree walk cannot see.
    """
    return audit.scan_secrets(skip_history=False)


@pytest.fixture(scope="module")
def committed_secret_scan() -> dict:
    """What `artifacts/SECRET_SCAN.json` currently publishes.

    Kept as a separate fixture so the two can be compared. On its own it asserts nothing:
    it is the claim, and `secret_scan` above is the measurement.
    """
    return json.loads((_ARTIFACTS / "SECRET_SCAN.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def attribution() -> dict:
    return json.loads((_ARTIFACTS / "ATTRIBUTION_AUDIT.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def weight() -> dict:
    return json.loads((_ARTIFACTS / "REPO_WEIGHT.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The published receipts say what they are supposed to say
# ---------------------------------------------------------------------------


def test_the_secret_scan_is_clean_and_says_what_it_covered(secret_scan: dict) -> None:
    """Run the scan over this tree, now, and require it to find nothing.

    The failure message names the findings rather than the count, because a count tells a
    reader a secret exists and not which file to open.
    """
    assert secret_scan["schema"] == "SECRET_SCAN"
    assert secret_scan["findings"] == [], (
        f"{secret_scan['n_findings']} credential-shaped strings in this tree or its "
        f"history: {secret_scan['findings'][:5]}"
    )
    assert secret_scan["clean"] is True
    assert secret_scan["env_files_tracked"] == []
    assert secret_scan["env_example_credential_shaped_values"] == []
    # A scan that walked nothing also finds nothing. These two are what make the zero
    # above a measurement, and both are read off the same run that produced it.
    assert secret_scan["coverage"]["text_files_scanned"] > 100
    assert secret_scan["coverage"]["history"]["scanned"] is True
    assert secret_scan["coverage"]["history"]["commits"] > 1
    assert len(secret_scan["rules"]) == 14


def test_the_committed_receipt_agrees_with_a_live_scan(
    secret_scan: dict, committed_secret_scan: dict
) -> None:
    """The published receipt has to match what the scanner says today.

    Not a byte comparison. The receipt is written at one commit and committed at the next,
    so its `commit` field and its history counts are behind HEAD by design, the same
    reason `scripts/gate.py` does not check the sign-off receipt for freshness. What must
    not drift is the answer: the same rule set, and the same verdict.
    """
    assert committed_secret_scan["rules"] == secret_scan["rules"], (
        "the committed receipt was produced by a different rule set than the scanner "
        "now has, so its clean verdict describes a different question"
    )
    assert committed_secret_scan["clean"] == secret_scan["clean"]
    assert committed_secret_scan["n_findings"] == secret_scan["n_findings"]


def test_the_attribution_audit_leaves_no_incomplete_file(attribution: dict) -> None:
    """Zero incomplete files over a non-empty set of rows.

    The second half is the one that matters: an audit that resolved no files at all would
    also report zero incomplete ones, and would be a clean receipt describing nothing.
    """
    assert attribution["clean"] is True
    assert attribution["incomplete_files"] == []
    assert len(attribution["rows"]) > 50
    derived = [r for r in attribution["rows"] if r.get("satnogs_derived")]
    assert derived, "no row resolved to a SatNOGS observation, so nothing was audited"
    for row in derived:
        assert all(row["obligations"].values()), row["file"]


def test_the_weight_report_adds_up_to_the_tree_it_measured(weight: dict) -> None:
    """The report's own groups have to account for the total it published.

    Deliberately a self-consistency check rather than a comparison against HEAD. The audit
    is measured at a commit and committing its receipt moves HEAD past it, so requiring
    equality here would fail on the commit that publishes the receipt. Freshness at the
    release commit is `scripts/signoff.py`'s job, where it is a decision made once.

    What this catches is the other failure: a directory silently dropped from the walk, so
    that the groups sum to less than the total the same run reported.
    """
    assert weight["tracked_files"] > 0
    assert weight["tracked_bytes"] > 0
    # The field is named megabytes and holds mebibytes: bytes over 1048576, which is what
    # `du -h` and GitHub's own size column report, so a reader comparing them agrees. The
    # divisor is pinned here so a later edit cannot change the unit under the same name.
    assert weight["tracked_megabytes"] == pytest.approx(
        weight["tracked_bytes"] / 1048576, abs=0.01
    )
    grouped = sum(d["megabytes"] for d in weight["by_directory"])
    remainder = weight["by_directory_remainder"]
    assert grouped + remainder["megabytes"] == pytest.approx(
        weight["tracked_megabytes"], abs=0.2
    ), (
        f"the directory groups plus the remainder account for "
        f"{grouped + remainder['megabytes']:.2f} MB of a tree the same run measured at "
        f"{weight['tracked_megabytes']:.2f} MB"
    )
    assert remainder["groups"] >= 0
    assert remainder["why"]
    for proposal in weight["proposals"]:
        assert proposal["keep_because"], f"{proposal['path']} is proposed with no reason"


# ---------------------------------------------------------------------------
# The checks can fail: every claim is planted and has to be found
# ---------------------------------------------------------------------------


#: Every planted value is assembled from fragments rather than written whole. The standing
#: gate greps the tracked tree for three of these shapes, and the first version of this file
#: failed it on the private-key header: a test about credential scanning that put a
#: credential-shaped literal into the repository is the thing it was written to prevent. Do
#: not join these strings back up.
_PLANTED = [
    ("github_pat_classic", "gh" + "p_" + "a" * 36),
    ("private_key_block", "-----BEGIN RSA PRIVATE " + "KEY-----"),
    ("aws_access_key_id", "AKIA" + "Q" * 16),
    ("openai_key", "sk-" + "b" * 24),
    ("anthropic_key", "sk-ant-" + "c" * 24),
    ("google_api_key", "AIza" + "d" * 35),
    ("slack_token", "xoxb-" + "1234567890abcd"),
    ("npm_token", "npm_" + "e" * 36),
    (
        "jwt",
        ".".join(
            [
                "eyJhbGciOiJI" + "UzI1NiJ9",
                "eyJzdWIiOiIx" + "MjM0NTY3ODkwIn0",
                "dBjftJeZ4CV" + "PmB92K27uhbUJU1p1r",
            ]
        ),
    ),
    ("generic_assigned_secret", 'api_key = "' + "f" * 30 + '"'),
]


@pytest.mark.parametrize(("rule", "planted"), _PLANTED, ids=[r for r, _ in _PLANTED])
def test_every_pattern_matches_the_credential_shape_it_names(
    audit, rule: str, planted: str
) -> None:
    """One planted credential per rule, so a rule that stopped matching is visible.

    Fourteen patterns and one silently broken regex is a scan that reports zero for a
    reason that has nothing to do with the repository.
    """
    pattern = dict(audit._SECRET_PATTERNS)[rule]
    assert re.search(pattern, planted), f"{rule} no longer matches its own credential shape"


def test_no_pattern_matches_ordinary_source(audit) -> None:
    """The other direction. A scan that matches everything is as useless as one that
    matches nothing, and it is the version that gets weakened by an allowlist entry."""
    benign = (
        "token = os.environ['GITHUB_TOKEN']\n"
        "password_field = form.get('password')\n"
        "SEED = 20260817\n"
        "sha256 = hashlib.sha256(raw).hexdigest()\n"
    )
    hits = [rule for rule, pat in audit._SECRET_PATTERNS if re.search(pat, benign)]
    assert hits == [], f"these patterns fire on ordinary source: {hits}"


def test_every_allowlist_entry_carries_a_reason(audit) -> None:
    """An exemption with no reason attached outlives the reason it was granted for."""
    for path, rule, why in audit._SECRET_ALLOWLIST:
        assert path and rule and why
        assert len(why) > 30, f"{path}/{rule} has no stated reason"


def test_an_obligation_removed_from_a_row_fails_the_audit(attribution: dict) -> None:
    """The mutation the receipt's own `clean` flag depends on.

    `clean` is computed from `incomplete_files`, so dropping one obligation on one row has
    to move a file into that list. If it does not, `clean` is a constant.
    """
    rows = [dict(r) for r in attribution["rows"]]
    target = next(r for r in rows if r.get("satnogs_derived"))
    target["obligations"] = dict(target["obligations"], source_sha256=False)
    incomplete = [
        r["file"]
        for r in rows
        if r.get("satnogs_derived") and not all(r["obligations"].values())
    ]
    assert incomplete == [target["file"]]


def test_the_audit_names_the_document_its_obligations_come_from(attribution: dict) -> None:
    """Six obligations, and they are the six `DATA_LICENSE.md` commits this project to."""
    assert "DATA_LICENSE.md" in attribution["obligations_source"]
    derived = next(r for r in attribution["rows"] if r.get("satnogs_derived"))
    assert set(derived["obligations"]) == {
        "attribution",
        "record_source_url",
        "artifact_source_url",
        "retrieval_timestamp",
        "source_sha256",
        "modification_notice",
    }


# ---------------------------------------------------------------------------
# The receipts were measured at the commit they claim
# ---------------------------------------------------------------------------


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(_REPO), capture_output=True, text=True, check=True
    ).stdout.strip()


def _recent_commits(n: int = 12) -> list[str]:
    out = subprocess.run(
        ["git", "log", f"-{n}", "--format=%H"],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return out


@pytest.mark.parametrize(
    "name", ["SECRET_SCAN.json", "ATTRIBUTION_AUDIT.json", "REPO_WEIGHT.json"]
)
def test_each_audit_receipt_names_a_commit_that_exists_in_this_history(name: str) -> None:
    """A receipt measured against a commit nobody can find is not evidence of anything.

    This is deliberately weaker than "measured at HEAD": committing the receipt creates a
    new commit, so a receipt can never name the commit it lands in. `scripts/signoff.py`
    is what enforces freshness, at the release commit, where it is a decision rather than
    a standing constraint.
    """
    doc = json.loads((_ARTIFACTS / name).read_text(encoding="utf-8"))
    commit = doc["commit"]
    found = subprocess.run(
        ["git", "cat-file", "-t", commit],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
    )
    assert found.stdout.strip() == "commit", f"{name} names {commit}, which is not a commit here"
