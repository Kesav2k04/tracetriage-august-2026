"""Every video this repository publishes can start before it has finished downloading.

An MP4 keeps its sample table in the `moov` atom, and a player cannot render a frame until
it has read it. Write `moov` after `mdat` and the index a player needs first sits at the end
of the file, so the browser must fetch far enough through the payload to reach it before
anything happens. `ffmpeg -movflags +faststart` moves it to the front.

This is here because it shipped. `apps/web/public/media/corridor-explainer.mp4` is 1.6 MB on
the landing page and was written by Manim, which does not pass the flag, so `moov` sat last.
The element also carried `preload="none"`, so nothing was fetched until a click and the
click then bought a wait rather than a video. The other two tracked videos already had
faststart, which is why exactly one of the three misbehaved and the cause read as a broken
file rather than as a container layout.

The check is on the committed bytes rather than on the renderer, because the renderer is
`manim` for one file and Remotion for another and neither is a dependency of the offline
suite. What matters is the property, whoever produced it.
"""

from __future__ import annotations

import struct
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

#: Container extensions whose atom order this check understands. WebM is a different
#: container with a different seeking story and is excluded rather than mis-checked.
MP4_SUFFIXES = {".mp4", ".m4v", ".mov"}


def _tracked_videos() -> list[Path]:
    """Committed video files, read from git rather than by walking the tree.

    A walk would pick up renderer scratch output under `presentation/out` and `media/` that
    is gitignored and never published, and failing on a file no reader can fetch would be a
    regression nobody caused.
    """
    done = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        REPO / line
        for line in done.stdout.split()
        if Path(line).suffix.lower() in MP4_SUFFIXES
    ]


def _atom_order(path: Path) -> list[str]:
    """The top-level atom types, in the order they appear in the file."""
    order: list[str] = []
    with path.open("rb") as handle:
        while True:
            header = handle.read(8)
            if len(header) < 8:
                break
            size = struct.unpack(">I", header[:4])[0]
            order.append(header[4:8].decode("latin1", errors="replace"))
            if size == 0:
                # Runs to end of file, so there is nothing after it to record.
                break
            if size == 1:
                size = struct.unpack(">Q", handle.read(8))[0]
                handle.seek(size - 16, 1)
            else:
                handle.seek(size - 8, 1)
    return order


def test_there_is_a_video_to_check() -> None:
    """A green run over zero files would report the property without measuring it."""
    assert _tracked_videos(), (
        "no tracked .mp4/.m4v/.mov was found, so every assertion below would pass over "
        "an empty list"
    )


@pytest.mark.parametrize("video", _tracked_videos(), ids=lambda p: p.name)
def test_the_index_comes_before_the_payload(video: Path) -> None:
    """`moov` before `mdat`, so a player can start on the first bytes it receives."""
    order = _atom_order(video)
    # Reported relative to the repository when it sits inside it, and absolute otherwise.
    # A failure message that raises while formatting hides the failure it was written to
    # explain, which is what happened the first time this assertion fired.
    try:
        where: Path | str = video.relative_to(REPO)
    except ValueError:
        where = video
    assert "moov" in order, f"{video.name} has no moov atom and is not a playable MP4"
    assert "mdat" in order, f"{video.name} has no mdat atom and carries no samples"
    assert order.index("moov") < order.index("mdat"), (
        f"{where} writes moov after mdat, so a browser cannot begin "
        f"playback until it has fetched far enough to reach the end of the file. Atom "
        f"order is {order}. Fix without re-encoding: "
        f"ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4"
    )
