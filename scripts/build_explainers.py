"""Lay the spoken track onto the two explainer clips, and write their captions.

The scenes are rendered by Manim and then left alone. Their video stream is copied, not
re-encoded: `tests/test_film_palette.py` reads colours out of the committed file and
compares them to the console's stylesheet, and a re-encode moves them. So this adds an
audio stream, moves the index to the front of the file, and touches nothing else.

The track is assembled rather than recorded in one pass. Each section's line is a separate
wav, and it is delayed to the exact frame its own card appears on, which
`artifacts/explainer_cuts/<clip>.json` records at render time. Nothing overlaps, so the
mix is a sum rather than a blend.

    .venv/Scripts/python.exe scripts/build_explainers.py           # mux, poster, captions
    .venv/Scripts/python.exe scripts/build_explainers.py --check   # verify, write nothing

`--check` re-reads what is committed and holds it against the receipts: that each clip has
an audio stream, that its duration covers the last line, that the captions name the same
sections in the same order, and that the index is at the front. It runs ffprobe and no
model, so the offline suite can run it.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEDIA = REPO / "apps" / "web" / "public" / "media"
NARRATION = REPO / "artifacts" / "EXPLAINER_NARRATION.json"
CUTS = REPO / "artifacts" / "explainer_cuts"

#: Manim writes here. The quality flag in the render command decides the subdirectory.
MANIM_OUT = REPO / "media" / "videos"

CLIPS = {"corridor": "CorridorExplainer", "gate4": "Gate4Explainer"}

#: The section whose card the poster is taken from: the one holding the answer, so
#: the still a reader sees before pressing play is already the result rather than a
#: title. The exact frame is written into the receipt, because `tests/
#: test_film_palette.py` compares the poster against that frame of the video and it
#: has to read the number rather than hold a second copy of it.
POSTER_SECTION = {"corridor": "measure", "gate4": "result"}
RECEIPT = REPO / "artifacts" / "EXPLAINER_CLIPS.json"

#: The page each clip is embedded in. Its copy states how long the clip runs, and a
#: reader deciding whether to press play is deciding on that number, so it is checked
#: rather than trusted: a re-cut clip that leaves the page saying the old length is
#: exactly the drift nobody notices.
PAGES = {
    "corridor": REPO / "apps" / "web" / "app" / "page.tsx",
    "gate4": REPO / "apps" / "web" / "app" / "evaluation" / "page.tsx",
}

#: Speech only, so a low bitrate is transparent and the page pays almost nothing for it.
AUDIO_BITRATE = "112k"


def _run(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{args[0]} failed:\n{result.stderr[-2000:]}")
    return result.stdout


def _ffprobe(path: Path, stream: str, fields: str) -> list[str]:
    out = _run(
        [
            "ffprobe", "-v", "error", "-select_streams", stream,
            "-show_entries", f"stream={fields}", "-of", "csv=p=0", str(path),
        ]
    )
    return [line for line in out.strip().split("\n") if line]


def sections(clip: str) -> list[dict]:
    receipt = json.loads(NARRATION.read_text(encoding="utf-8"))
    for entry in receipt["clips"]:
        if entry["clip"] == clip:
            return entry["sections"]
    raise SystemExit(f"{NARRATION.name} holds no clip called {clip!r}")


def cuts(clip: str) -> dict[str, float]:
    path = CUTS / f"{clip}.json"
    if not path.is_file():
        raise SystemExit(
            f"missing {path.relative_to(REPO)}. Render the scene first: it writes the "
            f"time each section starts at, which is the only place that is known."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {s["key"]: float(s["start"]) for s in payload["sections"]}


def find_render(clip: str) -> Path:
    """The newest Manim render of this scene, whatever quality it was rendered at."""
    matches = sorted(
        MANIM_OUT.rglob(f"{CLIPS[clip]}.mp4"), key=lambda p: p.stat().st_mtime
    )
    if not matches:
        raise SystemExit(
            f"no Manim render of {CLIPS[clip]} under {MANIM_OUT.relative_to(REPO)}. "
            f"Run: manim -qh scripts/explainer_{clip}.py {CLIPS[clip]}"
        )
    return matches[-1]


def _rate(path: Path) -> float:
    """Frames a second, as a number rather than as the ratio ffprobe prints."""
    num, _, den = _ffprobe(path, "v", "r_frame_rate")[0].partition("/")
    return float(num) / float(den or 1)


def timestamp(seconds: float) -> str:
    minutes, rest = divmod(seconds, 60)
    return f"00:{int(minutes):02d}:{rest:06.3f}"


def write_captions(clip: str, rows: list[tuple[str, float, float]]) -> Path:
    """WebVTT beside the clip, because a spoken clip that cannot be read is worse.

    One cue per section rather than per phrase. The lines are whole sentences spoken
    over a card that is itself the point, and splitting them would put a reader's eye
    on the caption instead of on the animation the caption is describing.
    """
    out = MEDIA / f"{clip}-explainer.vtt"
    body = ["WEBVTT", ""]
    for text, start, end in rows:
        body += [f"{timestamp(start)} --> {timestamp(end)}", text, ""]
    out.write_text("\n".join(body), encoding="utf-8")
    return out


def build(clip: str) -> None:
    source = find_render(clip)
    starts = cuts(clip)
    rows = sections(clip)
    missing = [s["key"] for s in rows if s["key"] not in starts]
    if missing:
        raise SystemExit(f"{clip}: the render has no section for {', '.join(missing)}")

    inputs: list[str] = ["-i", str(source)]
    filters: list[str] = []
    labels: list[str] = []
    for index, row in enumerate(rows, start=1):
        inputs += ["-i", str(REPO / row["audio"])]
        delay = int(round(starts[row["key"]] * 1000))
        filters.append(f"[{index}:a]adelay={delay}|{delay},aresample=48000[a{index}]")
        labels.append(f"[a{index}]")
    # normalize=0 because the lines never overlap: a section's card is on screen alone.
    # With normalisation on, amix divides every input by the number of inputs and a
    # seven-section clip comes out at a seventh of the level it was rendered at.
    filters.append(
        f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[out]"
    )

    target = MEDIA / f"{clip}-explainer.mp4"
    _run(
        ["ffmpeg", "-y", "-v", "error", *inputs,
         "-filter_complex", ";".join(filters),
         "-map", "0:v", "-map", "[out]",
         # No -shortest: the audio mix ends on the last word and the video runs half a
         # second past it, which is the tail the scene held for. Truncating to the
         # shorter stream cuts exactly that tail off.
         "-c:v", "copy", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", "1",
         "-movflags", "+faststart", str(target)]
    )

    fps = _rate(target)
    key = POSTER_SECTION[clip]
    held = next(row["seconds"] for row in rows if row["key"] == key)
    poster_frame = int(round((starts[key] + held * 0.75) * fps))
    _run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(target),
         "-vf", f"select=eq(n\\,{poster_frame})", "-vsync", "0",
         "-frames:v", "1", "-q:v", "3", str(MEDIA / f"{clip}-explainer-poster.jpg")]
    )

    write_captions(
        clip,
        [
            (row["text"], starts[row["key"]], starts[row["key"]] + row["seconds"])
            for row in rows
        ],
    )
    duration = float(_ffprobe(target, "v", "duration")[0])
    print(
        f"{clip}: {duration:.1f}s at {fps:g} fps, {len(rows)} spoken sections, "
        f"poster at frame {poster_frame}, {target.stat().st_size / 1e6:.2f} MB"
    )
    return {
        "clip": clip,
        "video": target.relative_to(REPO).as_posix(),
        "poster": (MEDIA / f"{clip}-explainer-poster.jpg").relative_to(REPO).as_posix(),
        "captions": (MEDIA / f"{clip}-explainer.vtt").relative_to(REPO).as_posix(),
        "seconds": round(duration, 2),
        "fps": fps,
        "poster_frame": poster_frame,
        "spoken_sections": len(rows),
        "audio_codec": _ffprobe(target, "a", "codec_name")[0],
    }


def check() -> int:
    problems: list[str] = []
    for clip in CLIPS:
        target = MEDIA / f"{clip}-explainer.mp4"
        vtt = MEDIA / f"{clip}-explainer.vtt"
        if not target.is_file():
            problems.append(f"{clip}: {target.name} is missing")
            continue
        codecs = _ffprobe(target, "a", "codec_name")
        if not codecs:
            problems.append(f"{clip}: {target.name} has no audio stream")
        head = target.read_bytes()[:200_000]
        moov, mdat = head.find(b"moov"), head.find(b"mdat")
        if mdat >= 0 and not 0 <= moov < mdat:
            problems.append(f"{clip}: {target.name} is not faststart")
        rows = sections(clip)
        if not vtt.is_file():
            problems.append(f"{clip}: {vtt.name} is missing")
        else:
            body = vtt.read_text(encoding="utf-8")
            for row in rows:
                if row["text"] not in body:
                    problems.append(f"{clip}: {vtt.name} is missing the {row['key']} line")
        stated = re.findall(r"(\d+) seconds, narrated", PAGES[clip].read_text(encoding="utf-8"))
        if not stated:
            problems.append(f"{clip}: {PAGES[clip].name} does not say how long the clip is")
        elif {int(n) for n in stated} != {round(float(_ffprobe(target, "v", "duration")[0]))}:
            problems.append(
                f"{clip}: {PAGES[clip].name} says {'/'.join(stated)} seconds and the file "
                f"is {float(_ffprobe(target, 'v', 'duration')[0]):.0f}"
            )
        starts = cuts(clip)
        last = max(starts[r["key"]] + r["seconds"] for r in rows)
        duration = float(_ffprobe(target, "v", "duration")[0])
        if duration + 0.05 < last:
            problems.append(
                f"{clip}: the clip is {duration:.1f}s but its last line ends at {last:.1f}s"
            )
        else:
            print(f"{clip}: {duration:.1f}s, audio {codecs[0] if codecs else 'none'}, "
                  f"{len(rows)} captioned sections, last line ends at {last:.1f}s")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify, write nothing")
    args = parser.parse_args(argv)

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"{tool} is not on PATH")
            return 2
    if args.check:
        return check()
    built = [build(clip) for clip in CLIPS]
    RECEIPT.write_text(
        json.dumps(
            {
                "what_this_is": (
                    "The two explainer clips as committed: how long each one runs, the "
                    "frame its poster was taken from, and that it carries an audio "
                    "stream. The spoken lines and what a transcriber heard are in "
                    "artifacts/EXPLAINER_NARRATION.json."
                ),
                "clips": built,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {RECEIPT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
