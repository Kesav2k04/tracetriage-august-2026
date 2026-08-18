"""Rebuild the split artifacts into a scratch directory and diff them.

Why this exists: `scripts/gate.py` checked pytest, ruff, contract status, a clean tree, a
gate-6 verdict, secrets, the build log and the commit identity, and never rebuilt an
artifact. In D0 that let a committed `LEAKAGE_AUDIT.json` disagree with the code that
produced it while every gate stayed green, and it let a test pass against a file the
builder could no longer emit. Green on a stale artifact is the failure this closes.

`rebuilt_at` is excluded from the comparison because it is a write time: it moves on
every rebuild by design, and comparing it would report drift on every run.

    .venv/Scripts/python.exe scripts/check_artifact_freshness.py [--verbose] [--deep]

Exit 0 means the committed artifacts are what the current code produces from the current
snapshot. Exit 1 names the first field that differs.

Covered by default: SPLIT_MANIFEST.json, LEAKAGE_AUDIT.json and HERO_NULLS.json. The
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
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "Scripts" / "python.exe"
ARTIFACTS = REPO / "artifacts"

# Fields that are write times rather than measurements. A rebuild moves them and that is
# not drift.
IGNORED_TOP_LEVEL = ("rebuilt_at", "generated_at")


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

    with tempfile.TemporaryDirectory(prefix="tracetriage-freshness-") as tmp:
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
            tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
            print("[FAIL] the builder itself does not run:")
            for line in tail[-6:]:
                print(f"        {line}")
            return 1
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
                tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()
                print("[FAIL] the hero nulls exporter does not run:")
                for line in tail[-6:]:
                    print(f"        {line}")
                return 1
            diff = _first_difference(_strip(_load(hero_path)), _strip(_load(rebuilt_hero)))
            if diff:
                print("[FAIL] HERO_NULLS.json is stale. First difference:")
                print(f"        {diff}")
                print("        Rebuild it, then regenerate provenance:")
                print("          python scripts/export_hero_nulls.py")
                print("          python scripts/build_console_data.py --skip-images")
                return 1
            print("[PASS] HERO_NULLS.json matches what the exporter produces")

        if args.deep:
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
                print("[FAIL] the gate 3 runner does not run")
                return 1
            diff = _first_difference(
                _strip(_load(ARTIFACTS / "GATE3_RECEIPT.json")),
                _strip(_load(rebuilt_g3)),
            )
            if diff:
                print("[FAIL] GATE3_RECEIPT.json is stale. First difference:")
                print(f"        {diff}")
                return 1
            print("[PASS] GATE3_RECEIPT.json matches what the runner produces")

    return 0


if __name__ == "__main__":
    sys.exit(main())
