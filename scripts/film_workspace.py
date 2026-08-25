"""Build the working directory the presentation film is rendered in, outside the repo.

Three things the film needs are deliberately not in the working tree: the narration audio,
which is a voice recording; the render itself, which is a 4K mp4 tens of megabytes long; and
the poster and thumbnail cut from it. A clone does not need any of them. The film is published
as a link, and everything in the repository that describes it does so from a receipt.

They live in a sibling of the repository rather than in an ignored directory inside it. An
ignore rule is a line that says a path exists and is being hidden; a sibling directory is
not part of the tree at all, so there is nothing to hide and no way for a `git add -f` or a
stray tool to put a voice recording into a commit.

    <repo>/..
      film-local/
        public/audio/      the narration, rendered here by scripts/render_narration*.py
        public/film/       copied from the console's assets by this script
        public/waterfalls/ copied from the console's assets by this script
        out/               the render, its poster and the thumbnail

Set TRACETRIAGE_FILM_LOCAL to put it somewhere else. Everything that reads or writes any
of it resolves the same way, so one variable moves all of it.

    .venv/Scripts/python.exe scripts/film_workspace.py
    .venv/Scripts/python.exe scripts/film_workspace.py --check
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: The console's own assets, which the film reuses rather than keeping a second copy of in
#: the repository. They are copied into the workspace at render time instead, so the two
#: pictures still cannot drift: the copy is made from the tracked file every run.
SHARED = ("film", "waterfalls")
CONSOLE_PUBLIC = REPO / "apps" / "web" / "public"


def root() -> Path:
    """Where the film's local-only files live. A sibling of the repository by default."""
    override = os.environ.get("TRACETRIAGE_FILM_LOCAL")
    return Path(override).resolve() if override else REPO.parent / "film-local"


def public() -> Path:
    return root() / "public"


def audio() -> Path:
    return public() / "audio"


def out() -> Path:
    return root() / "out"


def prepare() -> list[str]:
    """Create the workspace and refresh the copied assets. Returns what it touched."""
    touched = []
    for directory in (public(), audio(), audio() / "explainer", out()):
        directory.mkdir(parents=True, exist_ok=True)
    for name in SHARED:
        source = CONSOLE_PUBLIC / name
        if not source.is_dir():
            raise SystemExit(f"{source.relative_to(REPO)} is missing")
        target = public() / name
        # Replaced rather than merged. A file deleted from the console's assets should
        # disappear from the film's copy too, or the film can go on rendering something
        # the site no longer ships.
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        touched.append(f"{name}/ ({sum(1 for _ in target.rglob('*') if _.is_file())} files)")
    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the workspace exists and what is in it, change nothing",
    )
    args = parser.parse_args(argv)

    if args.check:
        if not root().is_dir():
            print(f"no film workspace at {root()}", file=sys.stderr)
            return 1
        wavs = len(list(audio().glob("*.wav"))) if audio().is_dir() else 0
        renders = len(list(out().glob("*"))) if out().is_dir() else 0
        print(f"{root()}: {wavs} narration file(s), {renders} render artifact(s)")
        return 0

    touched = prepare()
    print(f"film workspace at {root()}")
    for line in touched:
        print(f"  copied {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
