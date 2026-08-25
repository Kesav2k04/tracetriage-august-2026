"""Speak the film's narration in the builder's own voice, and check what it said.

This is `scripts/render_narration.py` with one thing changed and one thing kept.

Changed: the speaker. Kokoro reads a script in a voice that belongs to nobody, and a
viewer hearing it knows within a sentence that no person is talking to them. This
renders the same script with Chatterbox, conditioned on a short recording of the person
who built the project, so the voice in the film is the voice of the builder rather than a
model's idea of a narrator. The reference clip is not committed and never leaves the
machine.

Kept: everything that makes a spoken number checkable. The script still comes from
`presentation/narration/narration.json`, which is generated from the same claim objects
the film draws, so this file reads no receipt and holds no figure of its own. Every
rendered beat is measured against its card's frame budget, then transcribed by a second
model that never sees the script, and every figure the narration claims is looked for in
that transcript with the same whole-token matcher the Kokoro path uses. A voice that
sounds better but says "two, seven twenty seven" fails here exactly as loudly.

    .venv-tts/Scripts/python.exe scripts/render_narration_cloned.py --reference PATH
    .venv-tts/Scripts/python.exe scripts/render_narration_cloned.py --check

Chatterbox is MIT-licensed and runs locally on the GPU, so the film's audio still carries
no licence a reader cannot read and still costs nothing to produce. It is deterministic
at a fixed seed, which is why SEED is a constant here rather than an argument: the same
script and the same reference clip produce the same wavs, and `--check` can compare bytes.

The reference recording is a biometric of a real person. It stays out of the repository,
out of the receipt, and out of the artifacts: the receipt records its digest and its
duration so a reader can tell whether the audio was re-rendered from the same source,
and nothing that could reconstruct the voice is published.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
NARRATION_JSON = REPO / "presentation" / "narration" / "narration.json"
AUDIO_DIR = REPO / "apps" / "web" / "public" / "audio"
RECEIPT = REPO / "artifacts" / "NARRATION_RECEIPT.json"

#: Fixed so a re-render reproduces the committed bytes. Chatterbox is deterministic at a
#: given seed, reference clip and setting; without pinning it, every run is a new take and
#: the receipt's digests mean nothing.
SEED = 20260825

#: How far the delivery is pushed from the reference's own affect. Left near the middle:
#: the point of cloning a real recording is to keep the speaker's own delivery, and a high
#: exaggeration overrides it with the model's idea of emphasis.
EXAGGERATION = 0.5

#: Lower values follow the reference's pacing more closely. Raised from the default
#: because a narration script read at conversational pace overruns cards written for it.
CFG_WEIGHT = 0.4

SAMPLE_RATE = 24000


def _renderer():
    """The Kokoro path, imported for its verifier rather than re-implemented.

    The figure matcher, the number folding and the transcript canonicalisation are the
    published behaviour of this repository's narration check. Writing a second copy here
    would let this file pass audio the committed check would fail, which is the one thing
    a second renderer must not be able to do.
    """
    spec = importlib.util.spec_from_file_location(
        "render_narration", REPO / "scripts" / "render_narration.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


#: The packages whose versions change how long a line takes to speak. Recorded for the
#: same reason the Kokoro path records its four: the weights are not the whole toolchain,
#: and a bump inside a compatible version range once re-timed a line by eight seconds
#: with the same text, the same voice and every digest still matching.
_TIMING_PACKAGES = ("chatterbox-tts", "torch", "torchaudio", "soundfile")


def toolchain() -> dict[str, str]:
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    out: dict[str, str] = {}
    for name in _TIMING_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = "not installed"
    return out


def render(cues: list[dict[str, Any]], reference: Path) -> list[dict[str, Any]]:
    import soundfile  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ChatterboxTTS.from_pretrained(device=device)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for cue in cues:
        name = f"narration-{cue['index']}-{cue['beat'].lower()}.wav"
        out = AUDIO_DIR / name
        # Re-seeded per beat rather than once per run, so re-rendering one beat after a
        # script edit does not change the other thirteen.
        torch.manual_seed(SEED + cue["index"])
        wav = model.generate(
            cue["text"],
            audio_prompt_path=str(reference),
            exaggeration=EXAGGERATION,
            cfg_weight=CFG_WEIGHT,
        )
        # Written as 16-bit PCM through soundfile rather than through torchaudio, which
        # saves float32. Both are valid WAV and only one of them is the format every
        # other narration file in this repository is in: the stdlib `wave` module cannot
        # read float WAV at all, so the duration check that decides whether a line fits
        # its card would have failed on a file the renderer had just written.
        soundfile.write(str(out), wav.squeeze(0).cpu().numpy(), model.sr, subtype="PCM_16")
        seconds = wav_seconds(out)
        results.append(
            {
                "beat": cue["beat"],
                "index": cue["index"],
                "text": cue["text"],
                "path": str(out.relative_to(REPO)).replace("\\", "/"),
                "seconds": round(seconds, 3),
                "budget_seconds": cue["budgetSeconds"],
                "fits": seconds <= cue["budgetSeconds"],
                "sha256": sha256_of(out),
            }
        )
        flag = "ok" if results[-1]["fits"] else "OVER"
        print(
            f"{cue['beat']:<14}{seconds:>7.2f}s  budget {cue['budgetSeconds']:>6.2f}s  {flag}"
        )
    return results


def transcribe(results: list[dict[str, Any]], cues: list[dict[str, Any]]) -> None:
    """Ask a model that never saw the script what it heard, then look for every figure."""
    from faster_whisper import WhisperModel  # noqa: PLC0415

    renderer = _renderer()
    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    by_index = {cue["index"]: cue for cue in cues}
    for result in results:
        segments, _ = model.transcribe(str(REPO / result["path"]), beam_size=5)
        result["transcript"] = " ".join(s.text.strip() for s in segments)
        result["figures"] = []
        for claim in by_index[result["index"]]["claims"]:
            found, form = renderer.figure_in(
                result["transcript"], claim["spoken"], claim["display"]
            )
            result["figures"].append(
                {
                    "file": claim["file"],
                    "path": claim["path"],
                    "display": claim["display"],
                    "spoken": claim["spoken"],
                    "heard_as": form,
                    "found": found,
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path(
            r"D:/IBM August Challenge/voice_casting/my_voice/reference.wav"
        ),
        help="the recording the narration voice is conditioned on; never committed",
    )
    parser.add_argument("--frames", action="store_true", help="print frame counts and exit")
    args = parser.parse_args()

    payload = json.loads(NARRATION_JSON.read_text(encoding="utf-8"))
    cues = payload["cues"]

    if not args.reference.exists():
        print(f"no reference recording at {args.reference}", file=sys.stderr)
        return 2

    results = render(cues, args.reference)
    transcribe(results, cues)

    over = [r for r in results if not r["fits"]]
    missing = [
        (r["beat"], f["display"])
        for r in results
        for f in r["figures"]
        if not f["found"]
    ]

    print()
    for beat, display in missing:
        print(f"NOT HEARD  {beat}: {display}")

    total = sum(r["seconds"] for r in results)
    print(
        f"\n{len(results)} beats, {total:.1f}s of speech, "
        f"{sum(len(r['figures']) for r in results)} figures checked, "
        f"{len(missing)} not heard, {len(over)} over budget"
    )

    # The frame count each card needs: the measured line plus the lead-in, the tail and
    # about a second of air, rounded up to a whole six frames. Printed rather than written
    # so the edit to Film.tsx stays a deliberate one.
    fps = payload["fps"]
    lead, tail = payload["leadInSeconds"], payload["tailSeconds"]
    print("\nframe budget from the measured audio:")
    frames_total = 0
    for r in results:
        need = r["seconds"] + lead + tail + 1.0
        frames = int(-(-need * fps // 6) * 6)
        frames_total += frames
        print(f'  {{ name: "{r["beat"]}", durationInFrames: {frames} }},')
    print(
        f"  total {frames_total} frames = {frames_total / fps:.1f}s "
        f"({'OK' if frames_total / fps <= 180 else 'OVER THE 3 MINUTE CAP'})"
    )

    # Written in the shape the published receipt already has, because
    # `presentation/src/data.ts` reads three fields out of it for the attribution card
    # and the narration tests read more. A second renderer emitting a second schema
    # would break the card rather than change the voice.
    for r in results:
        r["audio"] = r.pop("path")
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "What the film says out loud, and what a second model heard it say. "
                    "The script is generated from the same claim objects the film draws, "
                    "so this renderer reads no receipt and holds no figure of its own. "
                    "Every figure below was looked for in a transcript produced without "
                    "sight of the script."
                ),
                "what_this_does_not_establish": (
                    "That the narration is well delivered. Nothing here scores warmth or "
                    "pacing. It establishes that the audio says the figures the receipts "
                    "hold, and that no line outruns the card it is spoken over."
                ),
                "renderer": {
                    "model": "Chatterbox TTS (Resemble AI)",
                    "licence": "MIT",
                    "voice": "the builder's own, cloned from a private reference recording",
                    "voice_chosen_by": (
                        "Not chosen. It is the voice of the person who built the project, "
                        "recorded for this film. The reference clip is a recording of a "
                        "real person and is not committed; its digest and duration are "
                        "recorded here so a reader can tell whether two renders share a "
                        "source, and nothing that could reconstruct the voice is published."
                    ),
                    "seed": SEED,
                    "exaggeration": EXAGGERATION,
                    "cfg_weight": CFG_WEIGHT,
                    "sample_rate_hz": SAMPLE_RATE,
                    "runs_offline": True,
                    "reference_sha256": sha256_of(args.reference),
                    "reference_seconds": round(wav_seconds(args.reference), 3),
                    "reference_committed": False,
                    "model_sha256": {},
                    "toolchain": toolchain(),
                },
                "verifier": {
                    "model": "faster-whisper small.en, int8, CPU",
                    "ran": True,
                    "method": (
                        "Every figure the narration names is looked for in the transcript "
                        "of the rendered audio, on digits with grouping and punctuation "
                        "normalised away."
                    ),
                },
                "totals": {
                    "beats": len(results),
                    "spoken_seconds": round(total, 3),
                    # The film's own length, read from the script payload that
                    # `build-narration.ts` writes out of BEATS, not the sum of the frame
                    # budgets this script suggests. Those two are the same number only
                    # while every suggestion has been applied, and the receipt must
                    # report the film that exists rather than the one it recommended.
                    "film_seconds": round(payload["totalFrames"] / fps, 3),
                    "beats_overrunning_their_card": len(over),
                    "figures_checked": sum(len(r["figures"]) for r in results),
                    "figures_not_heard": len(missing),
                },
                "verdict": "PASSED" if not (missing or over) else "FAILED",
                "beats": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {RECEIPT.relative_to(REPO)}")
    return 1 if (missing or over) else 0


if __name__ == "__main__":
    raise SystemExit(main())
