"""Was a figure actually spoken in the audio that was rendered?

A spoken number cannot be read off the frame it is said over, so every figure the console
explainers speak is transcribed back by a second model and looked for here. Matching is on
whole tokens after both sides are reduced to a canonical form, not on substrings: the
figure 2 must not match the 2 inside 2727 and report a number as spoken that never was.

Both sides are reduced first. Number words become digits, separators between digits
collapse, and punctuation goes. That still catches the failure that matters, which is the
model saying a different number: "2,727" read aloud as "two, seven twenty seven" only
canonicalises to 2727 on both sides if the digits really were spoken in order.

This lived inside another renderer and was loaded out of it by file path, which is not a
dependency a reader can see. It is a module now. One matcher, because two drift and the one
that drifts is the one that stops catching things.
"""

from __future__ import annotations

import re

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


def figure_in(transcript: str, spoken: str, display: str | None = None) -> tuple[bool, str]:
    """Is the figure the narration says actually in what the audio was heard to say?

    Matched on whole tokens rather than as a substring, so the figure 2 does not match
    the 2 inside 2727 and report a number as spoken that never was.

    `display` is the string the card draws, and it is a second reading rather than a
    looser one. A spelled decimal folds badly: "plus thirty two point zero five" reduces
    to "plus 32 point 5", because the fold reads "zero five" as a quantity and leaves the
    word "point" standing, while the transcript's own "plus 32.05" reduces to "plus
    3205". Both are the same figure and neither is wrong; they just do not meet. The
    display reaches the transcript's form directly. It admits nothing a mis-reading could
    reach: audio heard as "32.5" reduces to "325" and matches neither needle, which is
    the failure this check exists for.
    """
    readings = [(canonical(transcript), canonical(spoken))]
    if display is not None and display != spoken:
        readings.append((canonical(transcript), canonical(display)))
    if "." in spoken:
        readings.append((canonical_digitwise(transcript), canonical_digitwise(spoken)))
    for haystack, needle in readings:
        if not needle:
            continue
        if re.search(rf"(?:^|\s){re.escape(needle)}(?:\s|$)", haystack):
            return True, needle
    return False, ""
