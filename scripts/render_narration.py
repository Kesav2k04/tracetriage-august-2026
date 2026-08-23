"""Speak the film's narration, then check that the audio says what the receipts hold.

The film was silent because it was built to be presented live. A judge watches it
alone, so it needs a track, and a spoken figure is a published figure. That is the
whole problem this script exists to solve: audio is the one artifact in this
repository that no reader can diff, so it gets an instrument instead of trust.

Three things happen here, in this order.

1. Render. `presentation/narration/narration.json` is generated from the same claim
   objects the film draws, so this script reads no receipt and holds no number of its
   own. Each beat becomes one wav, spoken by Kokoro 82M locally at a fixed speed. No
   API, no key, no credit, and nothing leaves the machine.

2. Fit. A line that overruns its card is heard over the next card. Each rendered wav
   is measured against the beat's own frame budget and an overrun is a failure, not a
   warning.

3. Transcribe, and check the figures. The audio is fed to Whisper and every figure
   the narration claims is looked for in the transcript. A speech model that reads
   "436.400" as two numbers, or drops a sign, or elides a thousands group, fails here
   rather than shipping. This is the step that makes the track checkable: the same
   discipline `presentation/test/claims.test.ts` applies to a drawn number, applied to
   a spoken one by measuring the sound rather than the script.

The receipt records the voice, the speed, the model digests, every duration and every
figure check, so a reader can say which weights produced the audio in the mp4. It also
records the versions of the four packages that decide how long a line takes to speak,
because the weights are not the whole toolchain and assuming they were cost a day: the
Physics line went from 17.5 seconds of speech to 25.2 across a dependency bump inside a
compatible version range, same text, same voice, same speed. Every digest still matched,
because both sides of that comparison were the committed files. So `--check` now speaks
the longest line again and compares the bytes, which is the only question that catches a
pipeline that no longer reproduces its own output.

Both dependencies are optional and neither is needed to run the gate or build the
console:

    pip install -e ".[narration]"

The Kokoro weights are 354 MB and are not committed. Fetch them once:

    curl -L -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
    curl -L -o voices-v1.0.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

Then point this script at the directory holding them with --model-dir or
TRACETRIAGE_KOKORO_DIR.

Kokoro 82M is Apache-2.0, which is why it is the one used here: the audio in a film
that carries CC BY-SA 4.0 imagery should not also carry a voice licence nobody can
read. `--check` re-runs every measurement against the committed receipt and writes
nothing, which is the mode the gate calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
NARRATION_JSON = REPO / "presentation" / "narration" / "narration.json"
# apps/web/public, not presentation/public. remotion.config.ts points the film's
# public directory at the console's, so staticFile() serves the exact asset the site
# ships and there is no second copy to go stale. The narration follows that rule, so
# the console can offer the narrated film with its captions from the same origin.
AUDIO_DIR = REPO / "apps" / "web" / "public" / "audio"
RECEIPT = REPO / "artifacts" / "NARRATION_RECEIPT.json"

#: The voice, fixed. Kokoro is deterministic at a given voice and speed, so naming it
#: here rather than passing it per run is what makes the audio reproducible.
#:
#: Chosen by `scripts/cast_narration_voice.py`, not by ear. All thirteen male voices in
#: these weights read the whole script and were ranked on figures heard, then lines
#: overrunning their card, then word error rate, by a rule fixed before the run. Nine
#: carried all 26 figures and four lost four each. Three of the nine overran no card, and
#: this one had the lowest error rate of those three. `artifacts/VOICE_CASTING.json` holds
#: the table with the losers in it. What that measurement does not cover is timbre, and
#: nothing here pretends otherwise.
VOICE = "am_eric"

#: Slightly under one so the numbers land. At 1.0 the model runs the digits of a
#: grouped figure together often enough that the transcription check catches it.
SPEED = 0.96

#: Kokoro's own sample rate. Written down so a resample never happens silently.
SAMPLE_RATE = 24_000

MODEL_FILES = ("kokoro-v1.0.onnx", "voices-v1.0.bin")


@dataclass
class BeatResult:
    """One beat's rendered line, measured rather than assumed."""

    beat: str
    index: int
    text: str
    path: str
    seconds: float
    budget_seconds: float
    sha256: str
    transcript: str = ""
    figures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return self.seconds <= self.budget_seconds

    @property
    def figures_found(self) -> bool:
        return all(f["found"] for f in self.figures)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


#: The packages whose versions change how long a line takes to speak. kokoro-onnx does the
#: chunking, espeakng-loader the phonemisation, onnxruntime the inference. soundfile only
#: writes the container and is here because it decides the header the digest covers.
_TIMING_PACKAGES = ("kokoro-onnx", "espeakng-loader", "onnxruntime", "soundfile")


def _toolchain() -> dict[str, str]:
    """What is installed, by name, for the packages that decide the audio's timing."""
    import importlib.metadata as metadata  # noqa: PLC0415

    found = {}
    for name in _TIMING_PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            # Absent is a fact about this environment, and recording it as absent is more
            # use than omitting the key: a receipt with no espeakng-loader row was made
            # somewhere that phonemised differently.
            found[name] = "absent"
    return found


def resolve_model_dir(explicit: str | None) -> Path:
    """Find the Kokoro weights, and say exactly what is missing when they are not there."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    from_env = os.environ.get("TRACETRIAGE_KOKORO_DIR")
    if from_env:
        candidates.append(Path(from_env))
    for candidate in candidates:
        if all((candidate / name).is_file() for name in MODEL_FILES):
            return candidate
    searched = ", ".join(str(c) for c in candidates) or "nothing (no path given)"
    raise SystemExit(
        f"Kokoro weights not found. Searched: {searched}.\n"
        f"Expected both of {', '.join(MODEL_FILES)} in one directory.\n"
        "The module docstring holds the two curl commands that fetch them."
    )


# ---------------------------------------------------------------------------
# Checking a spoken figure against a transcript.
#
# The hard part is not the speech, it is that Whisper writes a heard number in
# whichever form it likes, and none of them is the form the receipt holds. One run
# produced all four of these from correct readings:
#
#   seventeen thousand two hundred ninety   ->  "17 290"     (grouped, space for comma)
#   plus thirty two point zero five         ->  "plus 32, zero five"
#   three                                   ->  "three"      (word, not digit)
#   two point two five                      ->  "2, 25"      (comma for the point)
#
# So both sides are reduced to a canonical string first: number words become digits,
# separators between digits collapse, and punctuation goes. A figure counts as spoken
# when its canonical form appears in the transcript's. That still catches the failure
# that matters, which is the model saying a different number: "2,727" read as "two,
# seven twenty seven" canonicalises to 2727 on one side and 2727 on the other only if
# the digits really were spoken in order, and it did not, so it failed.
# ---------------------------------------------------------------------------

_WORD_DIGITS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}
_SCALES = {"hundred": 100, "thousand": 1000}
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_DIGIT_RUNS = re.compile(r"(?<=\d)[ .,](?=\d)")


def _words_to_number(tokens: list[str]) -> str:
    """Fold a run of number words into one integer string, or return '' if it is not one."""
    total = 0
    current = 0
    seen = False
    for token in tokens:
        if token in _WORD_DIGITS:
            current += int(_WORD_DIGITS[token])
            seen = True
        elif token in _SCALES:
            scale = _SCALES[token]
            if scale == 100:
                current = max(current, 1) * 100
            else:
                total += max(current, 1) * scale
                current = 0
            seen = True
        elif token == "and":
            continue
        else:
            return ""
    return str(total + current) if seen else ""


def _fold_number_words(text: str) -> str:
    """Replace every maximal run of number words with the integer it names.

    A run ends at the first token that is not a number word. A trailing "and" is put
    back as itself, because "twenty two and the checker refused" should fold the
    number and leave the conjunction where it was.
    """
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        trailing_and = 0
        while run and run[-1] == "and":
            run.pop()
            trailing_and += 1
        if run:
            out.append(_words_to_number(run) or " ".join(run))
        out.extend(["and"] * trailing_and)
        run.clear()

    for token in text.split():
        if token in _WORD_DIGITS or token in _SCALES or (token == "and" and run):
            run.append(token)
            continue
        flush()
        out.append(token)
    flush()
    return " ".join(out)


def canonical(text: str) -> str:
    """Reduce a phrase to the form a receipt and a transcript can be compared in."""
    lowered = _NON_ALNUM.sub(" ", text.lower()).strip()
    return _DIGIT_RUNS.sub("", _fold_number_words(_DIGIT_RUNS.sub("", lowered)))


def canonical_digitwise(text: str) -> str:
    """Canonicalise reading each number word as a digit rather than as a quantity.

    Only used for figures that carry a decimal point, and only as a second chance.
    Whisper writes "plus thirty two point zero five" as "plus 32, zero five", dropping
    the word "point", and the quantity reading then folds "zero five" to 5 and the
    figure looks absent. Reading those two words as the digits they are recovers 3205,
    which is what the receipt holds once the point is taken out.

    Kept narrow on purpose. Applied to integers it would accept a wrong reading: the
    mangled "two 727" concatenates to 2727 and would pass as a correct 2,727, which is
    the exact defect this whole check exists to catch.
    """
    lowered = _NON_ALNUM.sub(" ", text.lower()).strip()
    out = [_WORD_DIGITS.get(token, token) for token in lowered.split()]
    return _DIGIT_RUNS.sub("", " ".join(out))


def figure_in(transcript: str, spoken: str) -> tuple[bool, str]:
    """Is the figure the narration says actually in what the audio was heard to say?

    Matched on whole tokens rather than as a substring, so the figure 2 does not match
    the 2 inside 2727 and report a number as spoken that never was.
    """
    readings = [(canonical(transcript), canonical(spoken))]
    if "." in spoken:
        readings.append((canonical_digitwise(transcript), canonical_digitwise(spoken)))
    for haystack, needle in readings:
        if not needle:
            continue
        if re.search(rf"(?:^|\s){re.escape(needle)}(?:\s|$)", haystack):
            return True, needle
    return False, ""


def render(cues: list[dict[str, Any]], model_dir: Path) -> list[BeatResult]:
    try:
        import soundfile  # noqa: PLC0415
        from kokoro_onnx import Kokoro  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            'kokoro-onnx is not installed. Run: pip install -e ".[narration]"'
        ) from exc

    kokoro = Kokoro(
        str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin")
    )
    if VOICE not in kokoro.get_voices():
        raise SystemExit(f"voice {VOICE!r} is not in these weights")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    results: list[BeatResult] = []
    for cue in cues:
        name = f"narration-{cue['index']}-{cue['beat'].lower()}.wav"
        out = AUDIO_DIR / name
        samples, rate = kokoro.create(
            cue["text"], voice=VOICE, speed=SPEED, lang="en-us"
        )
        if rate != SAMPLE_RATE:
            raise SystemExit(f"expected {SAMPLE_RATE} Hz from Kokoro, got {rate}")
        soundfile.write(str(out), samples, rate)
        results.append(
            BeatResult(
                beat=cue["beat"],
                index=cue["index"],
                text=cue["text"],
                path=str(out.relative_to(REPO)).replace("\\", "/"),
                seconds=round(wav_seconds(out), 3),
                budget_seconds=cue["budgetSeconds"],
                sha256=sha256_of(out),
            )
        )
    return results


def transcribe(results: list[BeatResult], cues: list[dict[str, Any]]) -> None:
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(
            'faster-whisper is not installed. Run: pip install -e ".[narration]"'
        ) from exc

    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    by_index = {cue["index"]: cue for cue in cues}
    for result in results:
        segments, _ = model.transcribe(str(REPO / result.path), beam_size=5)
        result.transcript = " ".join(s.text.strip() for s in segments)
        for claim in by_index[result.index]["claims"]:
            found, form = figure_in(result.transcript, claim["spoken"])
            result.figures.append(
                {
                    "file": claim["file"],
                    "path": claim["path"],
                    "display": claim["display"],
                    "spoken": claim["spoken"],
                    "heard_as": form,
                    "found": found,
                }
            )


def report(results: list[BeatResult]) -> int:
    failures = 0
    for r in results:
        fit = "ok " if r.fits else "OVER"
        figs = f"{sum(1 for f in r.figures if f['found'])}/{len(r.figures)}"
        line = (
            f"{r.beat:<12} {r.seconds:>6.2f}s / {r.budget_seconds:>5.2f}s  {fit}  "
            f"figures {figs}"
        )
        print(line)
        if not r.fits:
            failures += 1
            print(f"    overruns its card by {r.seconds - r.budget_seconds:.2f}s")
        for f in r.figures:
            if not f["found"]:
                failures += 1
                print(
                    f"    {f['spoken']!r} (display {f['display']}) from "
                    f"{f['path']} is not in the transcript"
                )
                print(f"    heard: {r.transcript}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed receipt against the committed audio, write nothing",
    )
    parser.add_argument(
        "--skip-transcript",
        action="store_true",
        help="render and measure only, for iterating on the script",
    )
    args = parser.parse_args()

    if not NARRATION_JSON.is_file():
        raise SystemExit(
            f"{NARRATION_JSON.relative_to(REPO)} is missing. "
            "Run: cd presentation && npm run narration"
        )
    manifest = json.loads(NARRATION_JSON.read_text(encoding="utf-8"))
    cues: list[dict[str, Any]] = manifest["cues"]

    if args.check:
        return check(cues)

    model_dir = resolve_model_dir(args.model_dir)
    results = render(cues, model_dir)
    if not args.skip_transcript:
        transcribe(results, cues)
    failures = report(results)

    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "The narration track of presentation/out/tracetriage-film.mp4. "
                    "Text generated from the film's own claims by "
                    "presentation/scripts/build-narration.ts, spoken locally, then "
                    "transcribed and checked figure by figure against what the "
                    "receipts hold."
                ),
                "what_this_does_not_establish": (
                    "That the narration is worth listening to. It establishes that "
                    "every figure in it is a figure a receipt holds, and that no line "
                    "overruns the card it is spoken over."
                ),
                "renderer": {
                    "model": "kokoro-82M v1.0 (ONNX)",
                    "licence": "Apache-2.0",
                    "voice": VOICE,
                    "voice_chosen_by": (
                        "measurement, not preference. Every male voice in these weights "
                        "read the whole script and was ranked by figures heard, then by "
                        "lines overrunning their card, then by word error rate. "
                        "artifacts/VOICE_CASTING.json holds the table, losers included."
                    ),
                    "speed": SPEED,
                    "sample_rate_hz": SAMPLE_RATE,
                    "runs_offline": True,
                    "model_sha256": {
                        name: sha256_of(model_dir / name) for name in MODEL_FILES
                    },
                    # The two weight files are not the whole toolchain, and assuming they
                    # were cost a day. How long a line takes to speak depends on how
                    # kokoro-onnx chunks it and how espeakng-loader phonemises it, so the
                    # same text, voice and speed re-timed by eight seconds across a version
                    # bump inside a compatible range. Recorded so the next disagreement
                    # between this receipt and a fresh render is diagnosable rather than
                    # mysterious.
                    "toolchain": _toolchain(),
                },
                "verifier": {
                    "model": "faster-whisper small.en, int8, CPU",
                    "ran": not args.skip_transcript,
                    "method": (
                        "Every figure the narration names is looked for in the "
                        "transcript of the rendered audio, on digits with grouping "
                        "and punctuation normalised away."
                    ),
                },
                "totals": {
                    "beats": len(results),
                    "spoken_seconds": round(sum(r.seconds for r in results), 3),
                    "film_seconds": round(manifest["totalFrames"] / manifest["fps"], 3),
                    "beats_overrunning_their_card": sum(
                        1 for r in results if not r.fits
                    ),
                    "figures_checked": sum(len(r.figures) for r in results),
                    "figures_not_heard": sum(
                        1 for r in results for f in r.figures if not f["found"]
                    ),
                },
                "verdict": "PASSED" if failures == 0 else "FAILED",
                "beats": [
                    {
                        "beat": r.beat,
                        "index": r.index,
                        "text": r.text,
                        "audio": r.path,
                        "sha256": r.sha256,
                        "seconds": r.seconds,
                        "budget_seconds": r.budget_seconds,
                        "fits": r.fits,
                        "transcript": r.transcript,
                        "figures": r.figures,
                    }
                    for r in results
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        # newline="" so Python does not translate to CRLF on Windows. Git normalises it
        # on the way in either way, which would leave the file on disk different from the
        # file in the tree, and any digest taken of it here a value no committed file
        # reproduces.
        newline="",
    )
    print(f"\n{RECEIPT.relative_to(REPO)} written.")
    if failures:
        print(f"{failures} failure(s). The receipt records them rather than hiding them.")
    return 1 if failures else 0


def check(cues: list[dict[str, Any]]) -> int:
    """Re-measure the committed audio against the committed receipt."""
    if not RECEIPT.is_file():
        print(f"{RECEIPT.relative_to(REPO)} is missing")
        return 1
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    rows = {row["beat"]: row for row in receipt["beats"]}
    failures = 0
    if receipt["renderer"]["voice"] != VOICE:
        print(f"receipt voice {receipt['renderer']['voice']} is not {VOICE}")
        failures += 1
    for cue in cues:
        row = rows.get(cue["beat"])
        if row is None:
            print(f"{cue['beat']}: no row in the receipt")
            failures += 1
            continue
        if row["text"] != cue["text"]:
            print(f"{cue['beat']}: the receipt's text is not the generated text")
            failures += 1
        if abs(row["budget_seconds"] - cue["budgetSeconds"]) > 1e-6:
            print(f"{cue['beat']}: the beat's budget moved since the audio was made")
            failures += 1
        audio = REPO / row["audio"]
        if not audio.is_file():
            print(f"{cue['beat']}: {row['audio']} is missing")
            failures += 1
            continue
        if sha256_of(audio) != row["sha256"]:
            print(f"{cue['beat']}: {row['audio']} is not the file the receipt digested")
            failures += 1
        measured = round(wav_seconds(audio), 3)
        if measured > cue["budgetSeconds"]:
            print(f"{cue['beat']}: {measured}s overruns its {cue['budgetSeconds']}s card")
            failures += 1
    reproduced, why = _reproduces_longest(cues, receipt)
    if reproduced is False:
        failures += 1
    if failures:
        print(f"{len(cues)} beats, {failures} failure(s). {why}")
    else:
        print(f"{len(cues)} beats fit, digests match. {why}")
    return 1 if failures else 0


def _reproduces_longest(
    cues: list[dict[str, Any]], receipt: dict[str, Any]
) -> tuple[bool | None, str]:
    """Speak the longest line again and compare the bytes. Three outcomes, not two.

    Everything above compares the committed audio to the committed receipt, which cannot
    tell the difference between an intact pipeline and one that no longer produces its own
    output. It could not: the same text, voice and speed re-timed the Physics line from
    17.5 seconds of speech to 25.2 across a dependency bump, and every digest here still
    matched because both sides of the comparison were the old files.

    The longest line is the subject rather than a random one, and the reason is not that it
    is the one that drifted. Kokoro chunks a line that exceeds its context, so the longest
    line is the one nearest that edge, and an edge is where a re-timing shows up first.

    Returns True when the bytes match, False when they differ, and None when there was
    nothing to ask: no weights on this machine, or no kokoro-onnx installed. None is not a
    pass, and the caller prints which of the three it was.
    """
    try:
        model_dir = resolve_model_dir(None)
    except SystemExit:
        return None, "No weights here, so no re-render."
    try:
        import soundfile  # noqa: PLC0415
        from kokoro_onnx import Kokoro  # noqa: PLC0415
    except ImportError:
        return None, "No kokoro-onnx here, so no re-render."

    longest = max(cues, key=lambda cue: len(cue["text"]))
    row = next(r for r in receipt["beats"] if r["beat"] == longest["beat"])
    kokoro = Kokoro(
        str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin")
    )
    samples, rate = kokoro.create(
        longest["text"], voice=VOICE, speed=SPEED, lang="en-us"
    )
    with tempfile.TemporaryDirectory() as scratch:
        fresh = Path(scratch) / "fresh.wav"
        soundfile.write(str(fresh), samples, rate)
        digest = sha256_of(fresh)
        seconds = round(wav_seconds(fresh), 3)
    if digest == row["sha256"]:
        return True, f"{longest['beat']} re-renders to the same bytes."
    print(
        f"{longest['beat']}: re-rendering it here does not reproduce the committed audio. "
        f"committed {row['seconds']}s / {row['sha256'][:16]}, "
        f"fresh {seconds}s / {digest[:16]}.\n"
        f"  The receipt was made with {receipt['renderer'].get('toolchain')} and this "
        f"environment has {_toolchain()}.\n"
        "  If those differ, pin them back or re-render and re-verify the whole track: the "
        "durations are published and a card can start overrunning without a word changing."
    )
    return False, f"{longest['beat']} no longer re-renders to its bytes."


if __name__ == "__main__":
    if shutil.which("ffmpeg") is None and "--check" not in sys.argv:
        print("note: ffmpeg is not on PATH. It is not needed here, only by Remotion.")
    sys.exit(main())
