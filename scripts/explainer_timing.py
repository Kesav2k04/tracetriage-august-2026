"""Hold each section of an explainer for as long as its own narration takes.

Both clips were cut mute, with a `self.wait()` after every section chosen by watching the
render and guessing how long a reader needs. Once the sections are spoken those guesses
are wrong in both directions: a section holds after the line has finished, or the line is
still running when the next animation starts over it.

So the wait is computed instead. Each section declares itself, the scene tracks how much
time its own entrance animations have already used, and the hold is whatever is left of
the spoken line plus a short tail. A section whose line grows holds longer without anyone
editing a number, and a scene rendered before the narration exists still runs, on the
floors it was authored with, so a checkout with no receipts can still draw both clips.

The one number that is not derived is the floor, which is the shortest a section may hold
whatever the audio says. It exists because two of these sections are one short sentence
over an animation that has to finish being read.
"""

from __future__ import annotations

import json
from pathlib import Path

from manim import Scene

REPO = Path(__file__).resolve().parents[1]
RECEIPT = REPO / "artifacts" / "EXPLAINER_NARRATION.json"
CUTS_DIR = REPO / "artifacts" / "explainer_cuts"

#: Silence after the last word of a section, before the scene moves on. Long enough that
#: a cut never lands on the speaker's final consonant.
TAIL_SECONDS = 0.55


def spoken(clip: str) -> dict[str, float]:
    """Section key to the measured length of its rendered line, in seconds.

    Empty when the receipt is absent, which is the case in a fresh clone before the
    narration has been rendered. The scenes fall back to their authored floors then, so
    a missing receipt costs the timing and not the clip.
    """
    if not RECEIPT.is_file():
        return {}
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for entry in receipt["clips"]:
        if entry["clip"] == clip:
            return {s["key"]: float(s["seconds"]) for s in entry["sections"]}
    return {}


class NarratedScene(Scene):
    """A scene whose sections hold for their narration rather than for a constant."""

    #: Set by the subclass to the clip's key in the receipt.
    clip: str = ""

    def setup(self) -> None:
        super().setup()
        self._spoken = spoken(self.clip)
        self._section_key = ""
        self._section_start = 0.0
        self._cuts: list[dict[str, object]] = []

    def section(self, key: str) -> None:
        """Start a section. Everything played from here counts against its line."""
        self._section_key = key
        self._section_start = self.renderer.time
        self._cuts.append({"key": key, "start": round(self.renderer.time, 3)})

    def tear_down(self) -> None:
        """Write down where each section landed, so the audio can be laid against it.

        The scene is the only thing that knows this. A section starts when its entrance
        animation starts, and that time is the sum of every run_time before it, which is
        not a number anyone should be transcribing into a second file by hand. Writing it
        here means the mux places each line exactly where its own card appears.
        """
        super().tear_down()
        out = CUTS_DIR / f"{self.clip}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "clip": self.clip,
            "seconds": round(self.renderer.time, 3),
            "sections": self._cuts,
        }
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def hold(self, floor: float) -> None:
        """Wait out the rest of this section's line, or the floor, whichever is longer."""
        want = self._spoken.get(self._section_key, 0.0) + TAIL_SECONDS
        spent = self.renderer.time - self._section_start
        self.wait(max(floor, want - spent))
