"""Give the two page explainers a voice, and check what that voice actually said.

The clips on the console explain a measurement and a review protocol, and until now they
did it silently, with the explanation sitting in captions a reader has to keep up with
while the animation moves under them. A reader who looks away loses the thread. So the
same words are spoken, in the same voice the film uses, and each section of each scene
holds for exactly as long as its own line takes rather than for a duration somebody
guessed while watching a mute render.

Every figure spoken here is read out of the scene file that draws it, by parsing the
module for its constants rather than importing it, which is how `tests/
test_explainer_gate4_values.py` already reads the same numbers and means this runs
without Manim installed. Nothing is typed twice: if the scene's number moves and the
narration's does not, there is no second copy to move.

    .venv-tts/Scripts/python.exe scripts/render_explainer_narration.py --reference PATH
    .venv-tts/Scripts/python.exe scripts/render_explainer_narration.py --check

Then a second model transcribes what was rendered, without seeing the script, and every
figure is looked for in that transcript with the whole-token matcher `render_narration.py`
uses for the film. A clip that sounds fine and says a different number fails here.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
AUDIO_DIR = REPO / "apps" / "web" / "public" / "audio" / "explainer"
RECEIPT = REPO / "artifacts" / "EXPLAINER_NARRATION.json"

#: The same seed, exaggeration and reference clip as the film, so the console and the
#: film are one speaker rather than two. Pinned for the same reason: without it every run
#: is a new take and the receipt's digests say nothing.
SEED = 20260825
EXAGGERATION = 0.5
CFG_WEIGHT = 0.4
SAMPLE_RATE = 24000

ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _spell_below_thousand(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        rest = n % 10
        return TENS[n // 10] if rest == 0 else f"{TENS[n // 10]} {ONES[rest]}"
    rest = n % 100
    head = f"{ONES[n // 100]} hundred"
    return head if rest == 0 else f"{head} and {_spell_below_thousand(rest)}"


def spell_integer(n: int) -> str:
    """Spell a non-negative integer below one million."""
    if n < 0 or n >= 1_000_000:
        raise ValueError(f"cannot spell {n}")
    if n < 1000:
        return _spell_below_thousand(n)
    thousands, rest = divmod(n, 1000)
    head = f"{_spell_below_thousand(thousands)} thousand"
    if rest == 0:
        return head
    joiner = " and " if rest < 100 else " "
    return f"{head}{joiner}{_spell_below_thousand(rest)}"


def say(display: str) -> str:
    """The spoken form of a figure, derived from the way the scene displays it.

    The three rules the film's narration arrived at, for the same three reasons, and
    they are here rather than imported because the film's copy is TypeScript.

    Integers of three digits or more are spelled: a grouped display comes back as a
    different number ("two, seven twenty seven" for 2,727), and a bare three-digit one
    forks between "one hundred and thirteen" and "one thirteen", which was transcribed
    as 1130. A decimal whose fraction starts with a zero is spelled after the point,
    because the unstressed zero gets dropped and 32.05 becomes 32.5. Everything else
    keeps its digits: "one point five eight" reads worse than it sounds.
    """
    text = display.strip()
    if "." in text:
        text = re.sub(r"\.$", "", re.sub(r"(\.\d*?)0+$", r"\1", text))
    sign = "plus " if text.startswith("+") else "minus " if text.startswith("-") else ""
    bare = text.lstrip("+-")
    if re.fullmatch(r"\d{3,}", bare.replace(",", "")):
        return sign + spell_integer(int(bare.replace(",", "")))
    zero_led = re.fullmatch(r"(\d+)\.(0\d*)", bare)
    if zero_led:
        digits = " ".join(ONES[int(d)] for d in zero_led.group(2))
        return f"{sign}{spell_integer(int(zero_led.group(1)))} point {digits}"
    return sign + bare


def constants(scene: str) -> dict[str, Any]:
    """Read a scene file's module-level literals without importing Manim.

    The same reading `tests/test_explainer_gate4_values.py` does. Importing the module
    would pull in Manim and its font registration, and this has to run inside the TTS
    environment, which has neither.
    """
    tree = ast.parse((SCRIPTS / scene).read_text(encoding="utf-8"))
    out: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not target.id.isupper():
            continue
        try:
            out[target.id] = ast.literal_eval(node.value)
        except ValueError:
            continue
    return out


class Cue:
    """One section's spoken line, and the figures it is allowed to be checked against.

    `parts` interleaves prose with (name, display) pairs. The display is the string the
    scene draws, so the spoken form and the frame cannot disagree: both are that string,
    one read by a person and one rendered by Manim.
    """

    def __init__(self, key: str, *parts: str | tuple[str, str]) -> None:
        self.key = key
        self.figures = [p for p in parts if isinstance(p, tuple)]
        self.text = "".join(p if isinstance(p, str) else say(p[1]) for p in parts)


def corridor_cues() -> list[Cue]:
    c = constants("explainer_corridor.py")
    px = f"{abs(c['OFFSET_PX']):.0f}"
    hz = f"{abs(c['OFFSET_HZ']):,.0f}"
    ppm = f"{abs(c['OFFSET_PPM']):.1f}"
    elev = f"{c['MAX_EL_DEG']:.1f}"
    return [
        Cue(
            "intro",
            "This is one real pass, recorded by a volunteer station. It reached ",
            ("MAX_EL_DEG", elev),
            " degrees at its highest.",
        ),
        Cue(
            "assumption",
            "A detector that assumes the trace is vertical looks for energy in one "
            "column. On a moving satellite there is nothing in that column to find.",
        ),
        Cue(
            "geometry",
            "The satellite is moving, so the received frequency sweeps. The corridor "
            "is curved, and its shape is fixed by the geometry of the pass, not by "
            "anything a model chose.",
        ),
        Cue(
            "slide",
            "Slide that same curve across the image until it best matches the energy, "
            "and it gives up one number: how far off the capture was.",
        ),
        Cue(
            "measure",
            "That shift is ",
            ("OFFSET_PX", px),
            " pixels, which on this image is ",
            ("OFFSET_HZ", hz),
            " hertz, or ",
            ("OFFSET_PPM", ppm),
            " parts per million of the receive frequency.",
        ),
        Cue(
            "closing",
            "The gap between the two curves is the measurement. Not a score a model "
            "produced: a frequency error, in hertz, that a reviewer can check against "
            "the image itself.",
        ),
    ]


def gate4_cues() -> list[Cue]:
    c = constants("explainer_gate4.py")
    return [
        Cue(
            "intro",
            "Kill gate 4 asks the question the whole project rests on. Can a person "
            "decide anything from the image at all?",
        ),
        Cue(
            "protocol",
            "Three axes, and unsure is an answer rather than a failure to give one. "
            "Run the review, and report the rate.",
        ),
        Cue(
            "commit",
            "The sample was committed to first. One salted digest for every item, all ",
            ("COMMITMENTS_CHECKED", str(c["COMMITMENTS_CHECKED"])),
            " of them published before the review began, so nothing could be chosen "
            "after the answers were known.",
        ),
        Cue(
            "sample",
            ("N_OBSERVATIONS", str(c["N_OBSERVATIONS"])),
            " observations, with ",
            ("N_REPEATS", str(c["N_REPEATS"])),
            " of them shown twice: ",
            ("N_ITEMS", str(c["N_ITEMS"])),
            " items in all. No label, no model output, and no way to tell which ones "
            "are the repeats.",
        ),
        Cue(
            "scoring",
            "Before the scorer reads a single answer it re-hashes every image from disk "
            "and recomputes all ",
            ("COMMITMENTS_CHECKED", str(c["COMMITMENTS_CHECKED"])),
            " commitments. Any mismatch and it refuses outright.",
        ),
        Cue(
            "result",
            "It came back decisive on ",
            ("DECISIVE", str(c["DECISIVE"])),
            " of them. The bar written down beforehand was ",
            ("THRESHOLD", f"{c['THRESHOLD']:.2f}"),
            ". The interval's lower bound is ",
            ("LOWER", f"{c['LOWER']:.4f}"),
            ".",
        ),
        Cue(
            "verdict",
            "The gate is ",
            ("VERDICT", str(c["VERDICT"]).lower()),
            ", and the reviewer was a person, answering plates they had never seen "
            "against a sample nobody could still change.",
        ),
    ]


CLIPS = {"corridor": corridor_cues, "gate4": gate4_cues}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seconds(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return round(handle.getnframes() / handle.getframerate(), 2)


def _film_matcher():
    """Borrow the film's transcript matcher rather than writing a second one.

    Two matchers drift, and the one that drifts is the one that stops catching things.
    """
    spec = importlib.util.spec_from_file_location(
        "_film_narration", SCRIPTS / "render_narration.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before it is executed. `render_narration.py` defines a dataclass, and
    # dataclasses resolves its own annotations through `sys.modules[cls.__module__]`,
    # which is None for a module loaded from a spec and never registered.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.figure_in


def render(reference: Path) -> dict[str, Any]:
    import soundfile  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415
    from faster_whisper import WhisperModel  # noqa: PLC0415

    figure_in = _film_matcher()
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    tts = ChatterboxTTS.from_pretrained(device="cuda")
    whisper = WhisperModel("small.en", device="cpu", compute_type="int8")

    clips: list[dict[str, Any]] = []
    missed = 0
    for clip, build in CLIPS.items():
        cues = build()
        sections: list[dict[str, Any]] = []
        for index, cue in enumerate(cues):
            out = AUDIO_DIR / f"{clip}-{index}-{cue.key}.wav"
            torch.manual_seed(SEED)
            wav = tts.generate(
                cue.text,
                audio_prompt_path=str(reference),
                exaggeration=EXAGGERATION,
                cfg_weight=CFG_WEIGHT,
            )
            soundfile.write(
                str(out), wav.squeeze(0).cpu().numpy(), tts.sr, subtype="PCM_16"
            )
            segments, _ = whisper.transcribe(str(out), beam_size=5)
            heard = " ".join(s.text for s in segments).strip()
            figures = []
            for name, display in cue.figures:
                found, _ = figure_in(heard, say(display), display)
                figures.append(
                    {
                        "constant": name,
                        "display": display,
                        "spoken": say(display),
                        "found": found,
                    }
                )
                if not found:
                    missed += 1
                    print(f"NOT HEARD  {clip}/{cue.key}: {display}")
            sections.append(
                {
                    "key": cue.key,
                    "text": cue.text,
                    "audio": out.relative_to(REPO).as_posix(),
                    "seconds": _seconds(out),
                    "sha256": _sha256(out),
                    "heard": heard,
                    "figures": figures,
                }
            )
            print(f"  {clip}/{cue.key:11s} {_seconds(out):6.2f}s")
        clips.append(
            {
                "clip": clip,
                "scene": f"scripts/explainer_{clip}.py",
                "seconds": round(sum(s["seconds"] for s in sections), 2),
                "sections": sections,
            }
        )
        print(f"{clip}: {clips[-1]['seconds']:.2f}s of speech")

    checked = sum(len(s["figures"]) for c in clips for s in c["sections"])
    return {
        "what_this_is": (
            "The spoken track for the two explainer clips on the console, and what a "
            "second model heard when it transcribed that track without seeing the "
            "script. Every figure is read from the scene file that draws it."
        ),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "renderer": {
            "model": "Chatterbox TTS (Resemble AI)",
            "licence": "MIT",
            "voice": "the builder's own, cloned from a private reference recording",
            "seed": SEED,
            "exaggeration": EXAGGERATION,
            "cfg_weight": CFG_WEIGHT,
            "sample_rate_hz": SAMPLE_RATE,
            "runs_offline": True,
            "reference_sha256": _sha256(reference),
            "reference_seconds": _seconds(reference),
            "reference_committed": False,
        },
        "verifier": {
            "ran": True,
            "model": "faster-whisper small.en, int8, CPU",
            "saw_the_script": False,
        },
        "totals": {
            "clips": len(clips),
            "sections": sum(len(c["sections"]) for c in clips),
            "spoken_seconds": round(sum(c["seconds"] for c in clips), 2),
            "figures_checked": checked,
            "figures_not_heard": missed,
        },
        "verdict": "PASSED" if missed == 0 else "FAILED",
        "clips": clips,
    }


def check() -> int:
    """Re-read the receipt and hold it against the wavs on disk. No model, no network."""
    if not RECEIPT.exists():
        print(f"missing {RECEIPT.relative_to(REPO)}")
        return 1
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    problems: list[str] = []
    for clip in receipt["clips"]:
        cues = CLIPS[clip["clip"]]()
        if [c.key for c in cues] != [s["key"] for s in clip["sections"]]:
            problems.append(f"{clip['clip']}: sections no longer match the script")
            continue
        for cue, section in zip(cues, clip["sections"], strict=True):
            if cue.text != section["text"]:
                problems.append(f"{clip['clip']}/{cue.key}: line changed since render")
            path = REPO / section["audio"]
            if not path.exists():
                problems.append(f"{clip['clip']}/{cue.key}: {section['audio']} missing")
            elif _sha256(path) != section["sha256"]:
                problems.append(f"{clip['clip']}/{cue.key}: audio digest differs")
            for figure in section["figures"]:
                if not figure["found"]:
                    problems.append(
                        f"{clip['clip']}/{cue.key}: {figure['display']} was not heard"
                    )
    for problem in problems:
        print(problem)
    total = receipt["totals"]
    print(
        f"{total['sections']} sections, {total['spoken_seconds']:.1f}s of speech, "
        f"{total['figures_checked']} figures checked, "
        f"{total['figures_not_heard']} not heard"
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, help="the voice to clone")
    parser.add_argument("--check", action="store_true", help="verify, render nothing")
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.reference or not args.reference.is_file():
        print("--reference PATH is required, and has to be a wav that exists")
        return 2

    receipt = render(args.reference)
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    total = receipt["totals"]
    print(
        f"\n{total['sections']} sections, {total['spoken_seconds']:.1f}s of speech, "
        f"{total['figures_checked']} figures checked, "
        f"{total['figures_not_heard']} not heard"
    )
    print(f"wrote {RECEIPT.relative_to(REPO)}")
    return 0 if receipt["verdict"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
