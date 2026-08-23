"""Casting the narration voice by measurement, because the ear that would judge it is not here.

The film is watched once, alone, by somebody who will not rewind. So the property that
decides which voice reads it is not which one sounds warmest to whoever happened to be
listening: it is whether the figures in the script survive being spoken. That is measurable,
and measuring it costs one background run.

Every male voice in the Kokoro weights speaks the whole narration. A separate model
(faster-whisper, which never sees the script) transcribes each beat back, and each figure is
looked for in the transcript with the same whole-token matcher `scripts/render_narration.py`
uses to verify the shipped audio. Word error rate over the full script comes along as the
tie-break, and so does the room each voice leaves against its card, because a voice that is
perfectly clear and two seconds too long on every beat is unusable.

The ranking rule is written out below before any result exists, and it is total, so this run
is reproducible and cannot be re-read afterwards to favour a voice somebody already liked:

  1. figures heard, more is better
  2. beats that overrun their card, fewer is better
  3. word error rate over the whole script, lower is better
  4. voice id, alphabetically, so ties still resolve

Note what this does not measure. Nothing here scores timbre, warmth, or how a voice carries
a sentence, and no automatic metric stands in for that. It narrows the candidates to the ones
that are intelligible and fit, which is the part a listener cannot fix.

    .venv/Scripts/python.exe scripts/cast_narration_voice.py [--limit N] [--voices a,b]

Writes `artifacts/VOICE_CASTING.json`. The weights are the two files
`artifacts/NARRATION_RECEIPT.json` records under `renderer.model_sha256`; they are not
digested again here, because a second copy of a digest is one digest and one lie waiting.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
NARRATION_JSON = REPO / "presentation" / "narration" / "narration.json"
OUT = REPO / "artifacts" / "VOICE_CASTING.json"

RULE = [
    "figures heard, more is better",
    "beats that overrun their card, fewer is better",
    "word error rate over the whole script, lower is better",
    "voice id alphabetically, so ties still resolve",
]

#: American and British male voices. The prefix is Kokoro's own naming: the second letter is
#: the speaker's sex, so the candidate set is read off the weights rather than listed from
#: memory, and a voice added by a later release gets measured without editing this file.
MALE = re.compile(r"^[ab]m_")


def _renderer():
    """`scripts/render_narration.py`, imported for its verifier rather than re-implemented.

    The point of this run is to predict how the shipped check will behave, so it has to ask
    the same question with the same code. A second matcher written here could rank a voice
    first and then fail `render_narration.py --check` on the same audio.
    """
    spec = importlib.util.spec_from_file_location(
        "render_narration", REPO / "scripts" / "render_narration.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because that module declares a dataclass, and
    # `dataclasses` resolves a field's type by looking the defining module up in
    # `sys.modules`. Without this line it finds None and dies inside the decorator, which
    # reads as a bug in the renderer rather than in how this file imports it.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wer(reference: str, hypothesis: str, canonical) -> float:
    """Levenshtein distance over canonicalised words, divided by the reference length.

    Both sides go through the renderer's `canonical`, which folds spoken number words back
    into digits and collapses digit separators. Without that, a voice that said "seventeen
    thousand two hundred and ninety" for 17,290 would score four errors for being right.
    """
    ref = canonical(reference).split()
    hyp = canonical(hypothesis).split()
    if not ref:
        return 0.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i]
        for j, h in enumerate(hyp, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h))
            )
        previous = current
    return previous[-1] / len(ref)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model-dir", default=None)
    ap.add_argument(
        "--voices",
        default=None,
        help="comma-separated voice ids, for re-measuring a shortlist",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="measure only the first N cues, for a smoke run",
    )
    args = ap.parse_args()

    narration = json.loads(NARRATION_JSON.read_text(encoding="utf-8"))
    cues = narration["cues"]
    if args.limit:
        cues = cues[: args.limit]

    renderer = _renderer()
    model_dir = renderer.resolve_model_dir(args.model_dir)

    import soundfile
    from faster_whisper import WhisperModel
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(
        str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin")
    )
    available = sorted(kokoro.get_voices())
    if args.voices:
        wanted = [v.strip() for v in args.voices.split(",") if v.strip()]
        missing = [v for v in wanted if v not in available]
        if missing:
            raise SystemExit(f"these voices are not in the weights: {missing}")
        candidates = wanted
    else:
        candidates = [v for v in available if MALE.match(v)]
    if not candidates:
        raise SystemExit(
            f"no male voice matched {MALE.pattern} in {len(available)} voices, so these "
            "weights are laid out differently than this expects"
        )

    asr = WhisperModel("small.en", device="cpu", compute_type="int8")
    scratch = pathlib.Path(tempfile.mkdtemp(prefix="voice-casting-"))
    n_figures = sum(len(cue["claims"]) for cue in cues)

    rows = []
    for voice in candidates:
        heard = 0
        over = 0
        seconds = 0.0
        errors = 0.0
        beats = []
        for cue in cues:
            wav = scratch / f"{voice}-{cue['index']}.wav"
            samples, rate = kokoro.create(
                cue["text"], voice=voice, speed=renderer.SPEED, lang="en-us"
            )
            soundfile.write(str(wav), samples, rate)
            length = renderer.wav_seconds(wav)
            seconds += length
            fits = length <= cue["budgetSeconds"]
            if not fits:
                over += 1
            segments, _ = asr.transcribe(str(wav), beam_size=5)
            transcript = " ".join(s.text.strip() for s in segments)
            missed = []
            for claim in cue["claims"]:
                found, _form = renderer.figure_in(transcript, claim["spoken"])
                if found:
                    heard += 1
                else:
                    missed.append(claim["display"])
            spoken_words = len(renderer.canonical(cue["text"]).split())
            errors += _wer(cue["text"], transcript, renderer.canonical) * spoken_words
            beats.append(
                {
                    "beat": cue["beat"],
                    "seconds": round(length, 3),
                    "budget_seconds": cue["budgetSeconds"],
                    "fits": fits,
                    "figures_missed": missed,
                    "transcript": transcript,
                }
            )
            wav.unlink(missing_ok=True)
        words = sum(len(renderer.canonical(cue["text"]).split()) for cue in cues)
        row = {
            "voice": voice,
            "figures_heard": heard,
            "figures_total": n_figures,
            "beats_over_card": over,
            "word_error_rate": round(errors / words, 4) if words else 0.0,
            "total_seconds": round(seconds, 2),
            "beats": beats,
        }
        rows.append(row)
        print(
            f"{voice:<12} figures {heard}/{n_figures}  over {over}  "
            f"wer {row['word_error_rate']:.3f}  {seconds:6.1f}s",
            flush=True,
        )

    ranked = sorted(
        rows,
        key=lambda r: (
            -r["figures_heard"],
            r["beats_over_card"],
            r["word_error_rate"],
            r["voice"],
        ),
    )
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    decided_by = RULE[-1]
    if runner_up:
        for index, key in enumerate(
            ("figures_heard", "beats_over_card", "word_error_rate")
        ):
            if winner[key] != runner_up[key]:
                decided_by = RULE[index]
                break

    payload = {
        "note": (
            "Which male voice reads the film, decided by measurement. Every candidate "
            "speaks the whole script; faster-whisper transcribes it back without seeing "
            "the script; each figure is looked for with the same matcher that verifies "
            "the shipped audio. The ranking rule was fixed before the run and is total."
        ),
        "measured_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "weights": (
            "the two files artifacts/NARRATION_RECEIPT.json records under "
            "renderer.model_sha256"
        ),
        "asr_model": "faster-whisper small.en, int8 on CPU",
        "speed": renderer.SPEED,
        "sample_rate": renderer.SAMPLE_RATE,
        "script": {
            "cues": len(cues),
            "figures": n_figures,
            "source": "presentation/narration/narration.json",
        },
        "rule": RULE,
        "n_candidates": len(rows),
        "chosen": winner["voice"],
        "decided_by": decided_by,
        "runner_up": runner_up["voice"] if runner_up else None,
        "ranking": [r["voice"] for r in ranked],
        "candidates": ranked,
    }
    OUT.write_text(
        json.dumps(payload, indent=1) + "\n", encoding="utf-8", newline=""
    )
    print(f"\nchosen {winner['voice']} on {decided_by}")
    print(f"{OUT.relative_to(REPO)} written, {len(rows)} candidates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
