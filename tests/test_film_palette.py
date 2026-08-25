"""Every rendered video carries the console's ground, measured in pixels.

The presentation film was rendered at a navy palette, the palette then moved to black, and
nothing noticed for eight hours. Every check in the chain agreed: `presentation/src/theme.ts`
said `#0c0e12`, the claim test compared those pins against `globals.css` and passed, the film
receipt's digest matched the committed bytes exactly, and the committed bytes were still
`#050d21`. Each of those compares two things that were both updated, or a file against a
digest taken of that same file. None of them looks at a pixel.

The two Manim explainers were worse, and for the same reason. They read their palette out of
`globals.css` at render time, so the source of truth was never in question; they had simply
not been rendered since. One carried the navy and the other carried a ground from a palette
older than that, `#140d1b`, which no stylesheet in this repository has defined for months.

So this reads pixels. Each video is sampled in the outer margin of one frame and compared
against the hex the stylesheet defines for the ground, with a tolerance rather than an exact
match, because neither H.264 at yuv420p nor JPEG gives back the value it was handed. Each
poster is sampled the same way at the frame it was taken from, and compared against its own
video as well as against the pin, because a poster is rendered by a separate command and a
fresh poster over a stale film would otherwise read as clean.

What this does not measure: whether the sampled frame is representative. It takes five points
in the outer margin and requires them to agree with each other before it compares any of them
to the pin, so a frame whose margin is not the ground fails loudly instead of passing on one
lucky pixel.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CSS = REPO / "apps" / "web" / "app" / "globals.css"
THEME = REPO / "presentation" / "src" / "theme.ts"

#: Lossy encoding moves a flat colour by a little. The measured JPEG shift on these stills is
#: 1 to 3 in one channel; H.264 with 4:2:0 chroma has more room to drift, and 8 is still far
#: below the 19-step gap between the navy this check exists to catch and the black it wants.
TOLERANCE = 8

#: How closely the margin samples have to agree before any of them is trusted.
FLATNESS = 3


@dataclass(frozen=True)
class Clip:
    """A rendered video, the still taken from it, and the frame they share."""

    name: str
    video: Path
    poster: Path
    frame: int
    rebuild: str


def _explainer_clips() -> list[tuple[str, str, dict]]:
    """The two Manim clips, read from the receipt the build script writes.

    Their poster frames move whenever the narration is re-cut, so holding them here as
    constants meant the test compared the poster against a frame it was not taken from.
    """
    receipt = REPO / "artifacts" / "EXPLAINER_CLIPS.json"
    if not receipt.is_file():
        return []
    scenes = {"corridor": "CorridorExplainer", "gate4": "Gate4Explainer"}
    return [
        (entry["clip"].replace("gate4", "gate 4"), scenes[entry["clip"]], entry)
        for entry in json.loads(receipt.read_text(encoding="utf-8"))["clips"]
    ]


CLIPS = (
    Clip(
        name="presentation film",
        video=REPO / "presentation" / "out" / "tracetriage-film.mp4",
        poster=REPO / "presentation" / "out" / "tracetriage-film-poster.jpg",
        # The frame presentation/package.json renders the poster from.
        frame=1730,
        rebuild="npm run render, npm run poster and npm run report in presentation/",
    ),
    *(
        Clip(
            name=f"{label} explainer",
            video=REPO / entry["video"],
            poster=REPO / entry["poster"],
            # Written by the script that cuts the still, so the frame this compares
            # against is the frame the still was taken from. It used to be a constant
            # here, recovered by matching the committed image against every frame, and
            # a re-cut clip moved the still without moving the constant.
            frame=entry["poster_frame"],
            rebuild=(
                f"manim -qh scripts/explainer_{entry['clip']}.py {scene}, then "
                f"scripts/build_explainers.py"
            ),
        )
        for label, scene, entry in _explainer_clips()
    ),
)

IDS = [clip.name for clip in CLIPS]


def _ground_pin() -> tuple[int, int, int]:
    """The ground the stylesheet defines. Every clip here is rendered against it."""
    match = re.search(
        r"--ui-background:\s*#([0-9a-fA-F]{6})", CSS.read_text(encoding="utf-8")
    )
    assert match, "globals.css no longer defines --ui-background as a six-digit hex"
    value = match.group(1)
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _margin_points(width: int, height: int) -> list[tuple[int, int]]:
    """Four corners inset by eight pixels, plus the top centre."""
    return [
        (8, 8),
        (width - 9, 8),
        (8, height - 9),
        (width - 9, height - 9),
        (width // 2, 8),
    ]


def _agreed(samples: list[tuple[int, int, int]], where: str) -> tuple[int, int, int]:
    """One colour from several samples, refusing if they disagree."""
    for channel in range(3):
        values = [sample[channel] for sample in samples]
        spread = max(values) - min(values)
        assert spread <= FLATNESS, (
            f"the margin of {where} is not one flat colour: channel {channel} spans "
            f"{spread} across {samples}. This check samples the margin, so a layout that "
            "puts content there makes it measure the wrong thing."
        )
    means = [round(sum(s[c] for s in samples) / len(samples)) for c in range(3)]
    return (means[0], means[1], means[2])


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _apart(measured: tuple[int, int, int], pin: tuple[int, int, int]) -> int:
    return max(abs(measured[channel] - pin[channel]) for channel in range(3))


def _video_ground(clip: Clip) -> tuple[int, int, int]:
    cv2 = pytest.importorskip(
        "cv2", reason="opencv is in the full extra; install .[full] to decode the videos"
    )
    assert clip.video.exists(), f"{clip.video.name} is missing. Rebuild: {clip.rebuild}"
    capture = cv2.VideoCapture(str(clip.video))
    try:
        assert capture.isOpened(), f"{clip.video.name} did not open as a video"
        capture.set(cv2.CAP_PROP_POS_FRAMES, clip.frame)
        ok, frame = capture.read()
        assert ok and frame is not None, f"frame {clip.frame} of {clip.video.name} did not decode"
        height, width = frame.shape[:2]
        # OpenCV hands back BGR.
        samples = [
            (int(frame[y, x][2]), int(frame[y, x][1]), int(frame[y, x][0]))
            for x, y in _margin_points(width, height)
        ]
    finally:
        capture.release()
    return _agreed(samples, clip.video.name)


def _poster_ground(clip: Clip) -> tuple[int, int, int]:
    image_module = pytest.importorskip("PIL.Image", reason="pillow is a core dependency")
    assert clip.poster.exists(), f"{clip.poster.name} is missing. Rebuild: {clip.rebuild}"
    image = image_module.open(clip.poster).convert("RGB")
    samples = [image.getpixel(point) for point in _margin_points(*image.size)]
    return _agreed(samples, clip.poster.name)


@pytest.fixture(scope="module")
def pin() -> tuple[int, int, int]:
    return _ground_pin()


@pytest.mark.parametrize("clip", CLIPS, ids=IDS)
def test_the_rendered_video_carries_the_ground_the_stylesheet_defines(clip, pin) -> None:
    """The check a digest cannot make: the pixels, against the declared hex."""
    measured = _video_ground(clip)
    apart = _apart(measured, pin)
    assert apart <= TOLERANCE, (
        f"the committed {clip.name} has a ground of {_hex(measured)} and globals.css defines "
        f"{_hex(pin)}, off by {apart} per channel. It was rendered before the palette moved. "
        f"Rebuild it: {clip.rebuild}"
    )


@pytest.mark.parametrize("clip", CLIPS, ids=IDS)
def test_the_poster_carries_the_same_ground(clip, pin) -> None:
    """A still is rendered by its own command, so it can go stale on its own."""
    measured = _poster_ground(clip)
    apart = _apart(measured, pin)
    assert apart <= TOLERANCE, (
        f"the committed {clip.name} poster has a ground of {_hex(measured)} and globals.css "
        f"defines {_hex(pin)}, off by {apart} per channel. Rebuild it: {clip.rebuild}"
    )


@pytest.mark.parametrize("clip", CLIPS, ids=IDS)
def test_the_video_and_its_poster_agree_at_the_frame_they_share(clip) -> None:
    """Two commands, one composition. Either one alone can be the stale artifact."""
    video = _video_ground(clip)
    poster = _poster_ground(clip)
    apart = _apart(video, poster)
    assert apart <= TOLERANCE, (
        f"the {clip.name} reads {_hex(video)} at frame {clip.frame} and its poster, which is "
        f"that frame, reads {_hex(poster)}. One of the two was not re-rendered."
    )


def test_the_films_own_theme_file_pins_the_stylesheets_ground(pin) -> None:
    """The film renders from theme.ts, so that file is a second place the ground can drift.

    The presentation suite already compares the whole pin block against `globals.css`. This
    repeats one line of it here so that a failure in the video checks above can be read
    without opening another test runner: if this passes and those fail, the sources are right
    and the render is stale.
    """
    match = re.search(
        r'uiBackground:\s*"#([0-9a-fA-F]{6})"', THEME.read_text(encoding="utf-8")
    )
    assert match, "presentation/src/theme.ts no longer pins uiBackground as a six-digit hex"
    value = match.group(1)
    pinned = (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    assert pinned == pin, (
        f"theme.ts pins {_hex(pinned)} and globals.css defines {_hex(pin)}, so the film is "
        "rendered against a ground the console does not use"
    )
