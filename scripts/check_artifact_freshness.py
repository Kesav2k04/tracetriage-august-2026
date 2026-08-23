"""Rebuild the split artifacts into a scratch directory and diff them.

Why this exists: `scripts/gate.py` checked pytest, ruff, contract status, a clean tree, a
gate-6 verdict, secrets, the build log and the commit identity, and never rebuilt an
artifact. In D0 that let a committed `LEAKAGE_AUDIT.json` disagree with the code that
produced it while every gate stayed green, and it let a test pass against a file the
builder could no longer emit. Green on a stale artifact is the failure this closes.

`rebuilt_at` is excluded from the comparison because it is a write time: it moves on
every rebuild by design, and comparing it would report drift on every run.

    .venv/Scripts/python.exe scripts/check_artifact_freshness.py [--verbose] [--deep]

Three outcomes, not two. Exit 0 with `[PASS]` lines means the committed artifacts are what
the current code produces from the current snapshot. Exit 1 with `[FAIL]` names the first
field that differs, or the builder that crashed. Exit 0 with `[SKIP]` means the snapshot is
not configured in this environment, so nothing was compared and nothing here is stale.

That third outcome is the correction. Every builder below rebuilds from the 20 GB snapshot,
which lives outside the repository and is named by TRACETRIAGE_PAGES_DIR. With the variable
unset, `scripts/build_splits.py` refuses by design and this script printed
`[FAIL] the builder itself does not run`, which reads as a stale artifact in a checkout
where nothing is stale. "Not measurable here" and "wrong" are different answers, and
folding the first into the second manufactures a regression on every machine that does not
hold the snapshot. A builder that crashes for any other reason still fails.

Covered by default: SPLIT_MANIFEST.json, LEAKAGE_AUDIT.json, HERO_NULLS.json,
SATELLITE_NAMES.json, TRIAGE_RECEIPT.json and every file a JSON-only console rebuild
emits under apps/web/public/data. cards.json is the one published file this cannot check, because
it needs the waterfall PNGs, and the check says so rather than passing over it. The
hero artifact earned its place the hard way. Its generator defaulted to 32 drawn paths
and one decimal while the shipped file carried 6 and zero, so a bare rebuild tripled the
ink on the home page and rewrote every coordinate, and nothing in the repository recorded
which command had produced the file. The defaults are now the shipped decision and this
check is what keeps them that way.

``--deep`` also rescores gate 3, which takes a few minutes and needs the waterfall PNGs.
Neither this script nor its deep mode can run in CI, because CI has no snapshot. Run the
deep form before a submission.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline.tracetriage.splits import (  # noqa: E402
    _PAGES_DIR_ENV,
    SplitsPathNotConfigured,
)

PY = REPO / ".venv" / "Scripts" / "python.exe"
ARTIFACTS = REPO / "artifacts"

# Fields that are write times rather than measurements. A rebuild moves them and that is
# not drift.
IGNORED_TOP_LEVEL = ("rebuilt_at", "generated_at")

#: The three verdicts a builder subprocess can earn. Named rather than spelled as two
#: booleans, because the whole defect here was a third state with nowhere to go.
RAN = "RAN"
NOT_CONFIGURED = "NOT_CONFIGURED"
CRASHED = "CRASHED"

#: The line `scripts/gate.py` looks for to tell "not measurable here" from "stale". It
#: greps for this prefix rather than reading an exit code, because the not-configured case
#: is not a failure and must not exit non-zero. `tests/test_freshness_outcomes.py` asserts
#: that the gate is still looking for this exact string.
SKIP_PREFIX = "[SKIP]"

#: Published files this script does not rebuild because something else owns them. Kept
#: separate from the files that need the waterfall imagery, so the note this script prints
#: says which of the two reasons applies rather than asserting the wrong one.
_CHECKED_BY_ANOTHER_BUILDER = {
    "bob.json": "scripts/export_bob_units.py --check, in tests/test_bob_units_export.py",
    "grounding_golden.json": (
        "scripts/export_grounding_golden.py --check, in tests/test_grounding_parity.py"
    ),
}

#: The exception class name, taken from the class rather than typed, so renaming it in
#: `pipeline/tracetriage/splits.py` cannot leave this scanner matching nothing and
#: silently reporting every unconfigured checkout as a stale artifact again.
_NOT_CONFIGURED_MARKER = SplitsPathNotConfigured.__name__

#: The degraded state `pipeline/tracetriage/waterfall.py` raises when there is no OCR
#: backend to read a waterfall's axis labels with. A code rather than a message, which is
#: what makes it safe to key a decision off: it is raised in exactly one situation and it
#: exists to be read.
_OCR_REFUSAL = "NO_OCR_BACKEND"


def _builder_outcome(returncode: int, output: str) -> str:
    """Which of the three things happened to a builder this script spawned.

    A refusal for want of the snapshot is a refusal by design: `_default_pages_dir` raises
    it, names the variable and says what to set. The exception's own class name is the guard
    that this really was that designed refusal and not a coincidence.

    The class name is not sufficient on its own, and reading the traceback alone was the
    first version of this function. `_default_pages_dir` raises the same
    `SplitsPathNotConfigured` for two different situations: the variable being absent, "no
    pages directory was given", and the variable being set to something that is not a
    directory, "TRACETRIAGE_PAGES_DIR is set to X, which is not a directory". Both messages
    carry the class name and the variable name, so text matching cannot separate them, and it
    reported a bad path as "not measurable here" and exited 0. That is worse than the defect
    this whole outcome was added to fix: a typo in the variable disabled the freshness check
    silently and left the gate green.

    So the environment decides, not the traceback. The variable being genuinely absent is the
    only thing that earns a skip. If it is set, the operator has asked for a measurement and
    supplied an address, and a bad address is a failure. The subprocess inherits this
    process's environment, so what is read here is what the builder saw.
    """
    if returncode == 0:
        return RAN
    configured = os.environ.get(_PAGES_DIR_ENV, "").strip()
    if _NOT_CONFIGURED_MARKER in output and not configured:
        return NOT_CONFIGURED
    return CRASHED


def _report_crash(subject: str, proc: subprocess.CompletedProcess) -> int:
    """Print why a builder produced nothing, and the exit code that reading deserves.

    Returns 0 for a missing snapshot and 1 for a crash. The caller no longer returns
    either one directly. It used to, on the reasoning that with no snapshot there was
    nothing further to compare, and that reasoning was wrong: two of the builders below
    need no snapshot at all, and the first one that did need it ran first, so its refusal
    returned out of the function before they were reached. That is why this whole check
    had never run in CI. A caller now records the skip, keeps going, and lets the builders
    that can run decide the exit code.
    """
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    tail = output.splitlines()
    if _builder_outcome(proc.returncode, output) == NOT_CONFIGURED:
        print(
            f"{SKIP_PREFIX} {subject} needs the snapshot, and {_PAGES_DIR_ENV} is not "
            f"set to it here."
        )
        print(
            "        Nothing it owns was compared and nothing it owns is known to be "
            "stale. The snapshot is 20 GB and lives outside the repository."
        )
        print(
            f"        Set {_PAGES_DIR_ENV} to its pages folder and run again to check "
            f"those artifacts for real."
        )
        if tail:
            print(f"        {tail[-1]}")
        return 0
    if _OCR_REFUSAL in output:
        # The third absent input, and the one the offline replay creates on purpose.
        # `scripts/clean_clone_check.py` installs `.[full,dev,onnx]` and not `.[ocr]`,
        # because easyocr pulls torch, torchvision, opencv and scikit-image, and pyproject
        # marks the tests that need it as excluded from the offline gate. So a clean clone
        # has no OCR backend by design, `pipeline/tracetriage/waterfall.py` raises the named
        # degraded state rather than guessing at an axis, and the hero-nulls exporter cannot
        # start. That is the environment, not a stale artifact, and this row printed [FAIL]
        # for it on every clean clone.
        #
        # Matched on the code rather than on a traceback. NO_OCR_BACKEND is a defined
        # degraded state that exists to be read by something, and
        # `tests/test_console_export.py` already keys the same third outcome off the same
        # string for the same reason.
        print(
            f"{SKIP_PREFIX} {subject} needs an OCR backend, and this environment has none: "
            f"{_OCR_REFUSAL}."
        )
        print(
            "        Nothing it owns was compared and nothing it owns is known to be "
            "stale. The offline replay installs .[full,dev,onnx] and leaves .[ocr] out on "
            "purpose, because easyocr pulls torch."
        )
        print("          pip install -e .[ocr]   (then the weights it reads)")
        return 0
    print(f"[FAIL] {subject} does not run:")
    for line in tail[-6:]:
        print(f"        {line}")
    return 1


def _load(path: pathlib.Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _strip(doc: object) -> object:
    if isinstance(doc, dict):
        return {k: _strip(v) for k, v in doc.items() if k not in IGNORED_TOP_LEVEL}
    if isinstance(doc, list):
        return [_strip(v) for v in doc]
    return doc


def _first_difference(a: object, b: object, path: str = "") -> str | None:
    if type(a) is not type(b):
        return f"{path or '<root>'}: committed {type(a).__name__}, rebuilt {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                return f"{path}.{k}: missing from the committed artifact"
            if k not in b:
                return f"{path}.{k}: no longer produced by the builder"
            d = _first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: committed {len(a)} entries, rebuilt {len(b)}"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = _first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    if a != b:
        return f"{path or '<root>'}: committed {a!r}, rebuilt {b!r}"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--deep",
        action="store_true",
        help="also rescore gate 3 (slow; needs the waterfall PNGs)",
    )
    args = ap.parse_args(argv)

    # The builders are re-invoked with the pinned interpreter rather than whichever
    # python launched this, because a rebuild under a different interpreter is a
    # different measurement. Named here so a missing venv reads as one line in the
    # gate output instead of a FileNotFoundError traceback from the first rebuild.
    if not PY.exists():
        print(f"[FAIL] no interpreter at {PY}; create the venv before checking freshness")
        return 1

    manifest_path = ARTIFACTS / "SPLIT_MANIFEST.json"
    audit_path = ARTIFACTS / "LEAKAGE_AUDIT.json"
    for p in (manifest_path, audit_path):
        if not p.exists():
            print(f"[FAIL] {p.name} is not committed, so there is nothing to check")
            return 1

    committed_manifest = _load(manifest_path)
    frozen_at = committed_manifest.get("frozen_at")
    if not frozen_at:
        print("[FAIL] the committed manifest carries no frozen_at to pin the rebuild to")
        return 1

    # Three outcomes, not two, and that is the whole point of this check's shape.
    #
    # It used to return the moment a builder could not run, and the builder that needs
    # the 20 GB snapshot ran first, so on any machine without the snapshot the function
    # returned before reaching the builders that need nothing. That is why a check
    # described as the strongest anti-staleness gate in the repository had never once
    # run in CI: it reported success from a line that had compared nothing.
    #
    # So a builder that cannot run is recorded in `skipped`, a comparison that ran is
    # recorded in `compared`, and only a real difference sets `failed`. The summary at
    # the end prints both lists, and it refuses to report a pass when `compared` is
    # empty, because "nothing was stale" and "nothing was checked" are different
    # sentences and only one of them is evidence.
    failed = False
    compared: list[str] = []
    skipped: list[str] = []
    snapshot = True

    with tempfile.TemporaryDirectory(prefix="tracetriage-freshness-") as tmp:
        # HERO_NULLS.json is deterministic and carries no timestamp, so it compares
        # exactly. It is also the artifact whose generator defaults had drifted away
        # from what shipped.
        hero_path = ARTIFACTS / "HERO_NULLS.json"
        if hero_path.exists():
            rebuilt_hero = pathlib.Path(tmp) / "HERO_NULLS.json"
            proc = subprocess.run(
                [
                    str(PY),
                    str(REPO / "scripts" / "export_hero_nulls.py"),
                    "--out",
                    str(rebuilt_hero),
                ],
                cwd=REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                if _report_crash("the hero nulls exporter", proc):
                    failed = True
                else:
                    skipped.append("HERO_NULLS.json")
            else:
                diff = _first_difference(
                    _strip(_load(hero_path)), _strip(_load(rebuilt_hero))
                )
                if diff:
                    print("[FAIL] HERO_NULLS.json is stale. First difference:")
                    print(f"        {diff}")
                    print("        Rebuild it, then regenerate provenance:")
                    print("          python scripts/export_hero_nulls.py")
                    print(
                        "          python scripts/build_console_data.py --skip-images"
                    )
                    failed = True
                else:
                    print("[PASS] HERO_NULLS.json matches what the exporter produces")
                    compared.append("HERO_NULLS.json")

        # SATELLITE_NAMES.json is the one receipt the console builder reads that comes
        # straight out of the snapshot, so it is the one that can drift without any
        # code changing: a snapshot rebuilt over a different window renames rows. It is
        # checked here rather than left to the console diff, because the console diff
        # reads it as an input and a stale input compares clean against itself.
        names_path = ARTIFACTS / "SATELLITE_NAMES.json"
        if names_path.exists():
            rebuilt_names_receipt = pathlib.Path(tmp) / "SATELLITE_NAMES.json"
            proc = subprocess.run(
                [
                    str(PY),
                    str(REPO / "scripts" / "export_satellite_names.py"),
                    "--out",
                    str(rebuilt_names_receipt),
                ],
                cwd=REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                if _report_crash("the satellite name exporter", proc):
                    failed = True
                else:
                    skipped.append("SATELLITE_NAMES.json")
            else:
                diff = _first_difference(
                    _strip(_load(names_path)), _strip(_load(rebuilt_names_receipt))
                )
                if diff:
                    print("[FAIL] SATELLITE_NAMES.json is stale. First difference:")
                    print(f"        {diff}")
                    print("        Rebuild it, then rebuild the console payloads:")
                    print("          python scripts/export_satellite_names.py")
                    print(
                        "          python scripts/build_console_data.py --skip-images"
                    )
                    failed = True
                else:
                    print(
                        "[PASS] SATELLITE_NAMES.json matches what the exporter produces"
                    )
                    compared.append("SATELLITE_NAMES.json")

        # The published copies under apps/web/public/data are derived artifacts too,
        # and nothing compared them against their sources until now. That gap shipped:
        # artifacts/HERO_NULLS.json was corrected in D2 and the published copy stayed
        # three times too heavy for a whole commit, because the artifact and the copy
        # are written by different scripts and only one of them was re-run.
        published = REPO / "apps" / "web" / "public" / "data"
        if published.is_dir():
            rebuilt_data = pathlib.Path(tmp) / "data"
            proc = subprocess.run(
                [
                    str(PY),
                    str(REPO / "scripts" / "build_console_data.py"),
                    "--skip-images",
                    "--data-dir",
                    str(rebuilt_data),
                ],
                cwd=REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                if _report_crash("the console data builder", proc):
                    failed = True
                else:
                    skipped.append("apps/web/public/data")
                rebuilt_names = set()
            else:
                rebuilt_names = {p.name for p in rebuilt_data.iterdir() if p.is_file()}
                for name in sorted(rebuilt_names):
                    a, b = published / name, rebuilt_data / name
                    if not a.exists():
                        print(f"[FAIL] {name} is built but not published")
                        return 1
                    if name.endswith(".json"):
                        diff = _first_difference(_strip(_load(a)), _strip(_load(b)))
                    else:
                        diff = None if a.read_bytes() == b.read_bytes() else "file contents differ"
                    if diff:
                        print(f"[FAIL] apps/web/public/data/{name} is stale. First difference:")
                        print(f"        {diff}")
                        print("        Rebuild it:")
                        print("          python scripts/build_console_data.py --skip-images")
                        return 1
                print(
                    f"[PASS] {len(rebuilt_names)} published files match what the console "
                    "builder produces"
                )
                compared.append(f"apps/web/public/data ({len(rebuilt_names)} files)")
                # Named rather than skipped. cards.json needs the waterfall PNGs, so a
                # JSON-only rebuild cannot produce it, and a check that quietly ignored it
                # would read as covering the directory.
                #
                # Two reasons a file can be uncovered here, and they are not the same reason.
                # Folding them together made this line say bob.json needs the waterfall images,
                # which it does not: it has its own builder and its own check, and a reader of
                # that note would have concluded nothing was watching it.
                uncovered = sorted(
                    p.name
                    for p in published.iterdir()
                    if p.is_file() and p.name not in rebuilt_names
                )
                elsewhere = sorted(n for n in uncovered if n in _CHECKED_BY_ANOTHER_BUILDER)
                needs_images = [n for n in uncovered if n not in _CHECKED_BY_ANOTHER_BUILDER]
                if needs_images:
                    print(
                        "[NOTE] not checked here (needs the waterfall images): "
                        + ", ".join(needs_images)
                    )
                for name in elsewhere:
                    print(f"[NOTE] {name} is checked by {_CHECKED_BY_ANOTHER_BUILDER[name]}")

        cmd = [
            str(PY),
            str(REPO / "scripts" / "build_splits.py"),
            "--out-dir",
            tmp,
            "--frozen-at",
            str(frozen_at),
        ]
        proc = subprocess.run(
            cmd, cwd=REPO, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            if _report_crash("the split builder", proc):
                return 1
            # The snapshot is absent, so the two artifacts this builder owns cannot be
            # compared here and the triage slice below cannot run either. Recorded and
            # stepped over rather than returned from: the checks above needed no snapshot
            # and have already run.
            skipped.extend(["SPLIT_MANIFEST.json", "LEAKAGE_AUDIT.json"])
            snapshot = False
        if snapshot:
            if args.verbose:
                print(proc.stdout.strip().splitlines()[-1] if proc.stdout else "")

            rebuilt_dir = pathlib.Path(tmp)
            for name, committed in (
                ("SPLIT_MANIFEST.json", committed_manifest),
                ("LEAKAGE_AUDIT.json", _load(audit_path)),
            ):
                rebuilt_path = rebuilt_dir / name
                if not rebuilt_path.exists():
                    print(f"[FAIL] the builder no longer emits {name}")
                    return 1
                diff = _first_difference(_strip(committed), _strip(_load(rebuilt_path)))
                if diff:
                    print(f"[FAIL] {name} is stale. First difference:")
                    print(f"        {diff}")
                    print(
                        "        Rebuild it, then regenerate provenance:\n"
                        f'        .venv\\Scripts\\python.exe scripts\\build_splits.py '
                        f'--frozen-at "{frozen_at}"\n'
                        "        .venv\\Scripts\\python.exe scripts\\build_console_data.py "
                        "--skip-images"
                    )
                    return 1
                print(f"[PASS] {name} matches what the builder produces")
                compared.append(name)

        # TRIAGE_RECEIPT.json earned its place the same way HERO_NULLS did. It was
        # written on 2026-08-17 and D1 added five fields to the corridor summary it
        # embeds, so the committed receipt was two units behind the code that writes
        # it while every gate passed. The observation id comes from the receipt rather
        # than from this script's idea of which one it should be, so the rebuild
        # compares like with like.
        triage_path = ARTIFACTS / "TRIAGE_RECEIPT.json"
        # The slice re-applies a trained model rather than training one, and the pickle it
        # reads is caught by `artifacts/**/*` in .gitignore and never re-included, so a
        # clone does not have it. Without it the slice still runs and writes a receipt whose
        # `model_checksum` is null, which its own schema rejects, so the builder exits
        # non-zero and this row printed [FAIL] on every fresh clone. A 1 MB input the
        # repository deliberately does not publish being absent is not a stale receipt.
        #
        # Checked as a precondition rather than read out of the traceback. The words a
        # schema rejection produces are the same whether the cause is an absent model or a
        # real regression in the receipt's shape, and `_builder_outcome` cannot separate
        # them: it earns NOT_CONFIGURED only for the designed pages-directory refusal with
        # the variable unset, and in the clone's snapshot-present pass the variable is set.
        model_path = ARTIFACTS / "hoglr_model.pkl"
        if triage_path.exists() and not model_path.exists():
            print(
                f"{SKIP_PREFIX} the triage slice needs artifacts/hoglr_model.pkl, which "
                f"this repository does not publish."
            )
            print(
                "        Nothing it owns was compared and nothing it owns is known to be "
                "stale. Rebuild the model first:"
            )
            print(
                "          python scripts/run_baseline.py --save-model "
                "artifacts/hoglr_model.pkl"
            )
            skipped.append("TRIAGE_RECEIPT.json")
        elif triage_path.exists():
            committed_triage = _load(triage_path)
            rebuilt_triage = pathlib.Path(tmp) / "TRIAGE_RECEIPT.json"
            proc = subprocess.run(
                [
                    str(PY),
                    str(REPO / "scripts" / "run_triage_slice.py"),
                    "--obs-id",
                    str(committed_triage.get("observation_id")),
                    "--out",
                    str(rebuilt_triage),
                ],
                cwd=REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                # Recorded and carried past, the way every builder above this one is. It
                # used to return here, which is the shape the comment on `_report_crash`
                # describes: the first builder that could not run decided the exit code and
                # the two rows below it never ran at all.
                if _report_crash("the triage slice", proc):
                    return 1
                skipped.append("TRIAGE_RECEIPT.json")
            else:
                diff = _first_difference(
                    _strip(committed_triage), _strip(_load(rebuilt_triage))
                )
                if diff:
                    print("[FAIL] TRIAGE_RECEIPT.json is stale. First difference:")
                    print(f"        {diff}")
                    print("        Rebuild it, then regenerate the card:")
                    print("          python scripts/run_triage_slice.py")
                    print("          python scripts/render_evidence_card.py")
                    return 1
                print("[PASS] TRIAGE_RECEIPT.json matches what the slice produces")
                compared.append("TRIAGE_RECEIPT.json")

        if args.deep:
            # PHYSICS_VALIDATION.json is here rather than in the default set because
            # rebuilding it propagates 200 passes three times over (the corridor, the
            # azimuth check and its two counterfactuals) and takes minutes, and because
            # it reads the A4 page cache rather than the snapshot. It is still a
            # generated artifact and it did drift once: the README quoted a median from
            # the run before the geodetic-normal fix for two waves.
            physics_path = ARTIFACTS / "PHYSICS_VALIDATION.json"
            if physics_path.exists():
                rebuilt_physics = pathlib.Path(tmp) / "PHYSICS_VALIDATION.json"
                proc = subprocess.run(
                    [str(PY), str(REPO / "scripts" / "validate_physics.py")],
                    cwd=REPO, capture_output=True, text=True,
                    encoding="utf-8", errors="replace",
                    env={**os.environ, "A4_OUT_PATH": str(rebuilt_physics)},
                )
                if proc.returncode != 0:
                    return _report_crash("the physics validation", proc)
                if rebuilt_physics.exists():
                    diff = _first_difference(
                        _strip(_load(physics_path)), _strip(_load(rebuilt_physics))
                    )
                    if diff:
                        print("[FAIL] PHYSICS_VALIDATION.json is stale. First difference:")
                        print(f"        {diff}")
                        return 1
                    print("[PASS] PHYSICS_VALIDATION.json matches what the validator produces")
                    compared.append("PHYSICS_VALIDATION.json")
                else:
                    print(
                        "[NOTE] the validator ignored A4_OUT_PATH, so this comparison "
                        "was skipped rather than run against the committed file"
                    )

            rebuilt_g3 = pathlib.Path(tmp) / "GATE3_RECEIPT.json"
            proc = subprocess.run(
                [
                    str(PY),
                    str(REPO / "scripts" / "run_gate3.py"),
                    "--out",
                    str(rebuilt_g3),
                ],
                cwd=REPO, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                return _report_crash("the gate 3 runner", proc)
            diff = _first_difference(
                _strip(_load(ARTIFACTS / "GATE3_RECEIPT.json")),
                _strip(_load(rebuilt_g3)),
            )
            if diff:
                print("[FAIL] GATE3_RECEIPT.json is stale. First difference:")
                print(f"        {diff}")
                return 1
            print("[PASS] GATE3_RECEIPT.json matches what the runner produces")
            compared.append("GATE3_RECEIPT.json")

    # The summary is the part a reader should be able to act on. A count of what was
    # compared is the only thing that distinguishes a clean run from a run that did
    # nothing, so it is printed either way and it decides the exit code.
    print()
    if compared:
        print(f"compared {len(compared)}: {', '.join(compared)}")
    if skipped:
        print(f"not compared here {len(skipped)}: {', '.join(skipped)}")
        # The remedy is per skip and no longer stated here. This line used to say to set
        # TRACETRIAGE_PAGES_DIR, which is right for the snapshot skips and wrong for the
        # triage slice's, whose remedy is rebuilding a model the repository does not
        # publish. One instruction printed under a mixed list is wrong for part of it.
        print("        Each [SKIP] line above names what it needs.")
    if failed:
        print("at least one artifact is stale, and the lines above say which")
        return 1
    if not compared:
        print(
            "nothing was compared, so this is not a pass. Every builder was skipped, "
            "which means this run is no evidence that any artifact is current."
        )
        return 1
    print(f"{len(compared)} artifact(s) match their builders")
    return 0


if __name__ == "__main__":
    sys.exit(main())
