"""Cutting narration at natural boundaries so each piece fits one video clip.

Narration arrives as text plus its real duration, with no word timings, so the time of a cut is
estimated by spreading the real duration over the text in proportion to its length (plus a small
allowance for the pause after sentence and clause punctuation). Those estimates are only used to
decide *where* to cut and to time subtitle cues; the total is always exactly the real duration.

Cuts are tried from most to least natural, and a finer level is used only where a coarser one cannot
make the pieces fit (``limit`` seconds each):

1. **sentence** boundaries (``. ! ? ።`` ...);
2. **clause** boundaries (``, ; : ፣ ፤`` ...), only inside a sentence too long for one clip;
3. **pause**: the gap between two words, only inside a clause too long for one clip.

Among the cuts that are allowed, the pieces are chosen to need the fewest clips, then the most
natural cuts, then to avoid pieces shorter than ``soft_min`` seconds. Words are never split.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

#: Sentence terminators (Latin, CJK and Ethiopic full stop / question mark / paragraph mark).
SENTENCE_ENDS = ".!?…。！？።፧፨"
#: Clause separators (Latin, CJK and Ethiopic comma / semicolon / colon).
CLAUSE_ENDS = ",;:，；：、—–፣፤፥፦"
_CLOSERS = "\"'”’»)]}"
#: Words whose final period does not end a sentence.
_ABBREVIATIONS = frozenset({"mr.", "mrs.", "ms.", "dr.", "st.", "vs.", "e.g.", "i.e."})
#: Words are separated by whitespace or the Ethiopic word space.
_WORD = re.compile(r"[^\s፡]+")
_EPS = 1e-6


class Boundary(IntEnum):
    """How natural a cut after a word is (lower is more natural)."""

    SENTENCE = 0
    CLAUSE = 1
    PAUSE = 2


#: Extra time, in characters' worth of speech, a pause after this kind of boundary takes.
_PAUSE_WEIGHT = {Boundary.SENTENCE: 4.0, Boundary.CLAUSE: 2.0, Boundary.PAUSE: 0.0}
#: What using a cut costs when choosing between pieces of equal count.
_CUT_PENALTY = {Boundary.SENTENCE: 0.0, Boundary.CLAUSE: 1.0, Boundary.PAUSE: 5.0}


@dataclass(frozen=True)
class Segment:
    text: str
    start: float
    end: float

    @property
    def seconds(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class _Word:
    start: int  # offsets in the original text
    end: int
    weight: float
    after: Boundary


@dataclass(frozen=True)
class _Cost:
    """What a way of cutting costs, compared in this order: clips, cut penalty, time in pieces
    shorter than ``soft_min`` (squared), then lopsidedness (sum of squared lengths)."""

    clips: int = 0
    penalty: float = 0.0
    shortfall: float = 0.0
    lopsided: float = 0.0

    def plus(self, length: float, penalty: float, soft_min: float) -> _Cost:
        return _Cost(
            self.clips + 1,
            self.penalty + penalty,
            self.shortfall + max(0.0, soft_min - length) ** 2,
            self.lopsided + length**2,
        )

    @property
    def key(self) -> tuple[int, float, float, float]:
        return (
            self.clips,
            round(self.penalty, 6),
            round(self.shortfall, 6),
            round(self.lopsided, 6),
        )


def _boundary_after(token: str) -> Boundary:
    core = token.rstrip(_CLOSERS)
    if not core or core.lower() in _ABBREVIATIONS:
        return Boundary.PAUSE
    if core[-1] in SENTENCE_ENDS:
        return Boundary.SENTENCE
    if core[-1] in CLAUSE_ENDS:
        return Boundary.CLAUSE
    return Boundary.PAUSE


def _words(text: str) -> list[_Word]:
    matches = list(_WORD.finditer(text))
    words: list[_Word] = []
    for index, match in enumerate(matches):
        after = _boundary_after(match.group())
        # No pause is spoken after the last word: the audio ends there.
        pause = _PAUSE_WEIGHT[after] if index < len(matches) - 1 else 0.0
        words.append(_Word(match.start(), match.end(), len(match.group()) + pause, after))
    return words


def _allowed_cuts(times: list[float], words: list[_Word], limit: float) -> list[int]:
    """Cut positions (index of the first word after the cut, plus the two ends) a piece may start
    or end at: sentence ends, plus finer ones only inside spans that do not fit ``limit``."""
    n = len(words)
    allowed = {0, n} | {i for i in range(1, n) if words[i - 1].after is Boundary.SENTENCE}
    for level in (Boundary.CLAUSE, Boundary.PAUSE):
        ordered = sorted(allowed)
        for low, high in zip(ordered, ordered[1:], strict=False):
            if times[high] - times[low] > limit + _EPS:
                allowed |= {i for i in range(low + 1, high) if words[i - 1].after <= level}
    return sorted(allowed)


def segment_narration(text: str, seconds: float, *, limit: float, soft_min: float) -> list[Segment]:
    """Cut ``text`` (spoken in ``seconds``) into pieces of at most ``limit`` seconds each.

    Text that already fits is returned whole. ``soft_min`` is the length below which a piece is a
    little too short: it is avoided when it costs nothing else, but never at the price of a less
    natural cut or an extra clip.
    """
    stripped = text.strip()
    words = _words(text)
    if seconds <= limit + _EPS or len(words) < 2:
        return [Segment(stripped, 0.0, seconds)]

    total = sum(w.weight for w in words)
    times = [0.0]
    for word in words:
        times.append(times[-1] + seconds * word.weight / total)
    times[-1] = seconds

    cuts = _allowed_cuts(times, words, limit)
    # best[j]: the cheapest way to cover the text up to cut j, and where its last piece starts.
    best: dict[int, tuple[_Cost, int]] = {0: (_Cost(), -1)}
    for j in range(1, len(cuts)):
        end = cuts[j]
        penalty = 0.0 if j == len(cuts) - 1 else _CUT_PENALTY[words[end - 1].after]
        options: list[tuple[_Cost, int]] = []
        for i in range(j):
            length = times[end] - times[cuts[i]]
            if length > limit + _EPS and i != j - 1:
                continue  # too long (unless no finer cut exists to make it shorter)
            options.append((best[i][0].plus(length, penalty, soft_min), i))
        best[j] = min(options, key=lambda option: option[0].key)

    pieces: list[tuple[int, int]] = []
    j = len(cuts) - 1
    while j > 0:
        i = best[j][1]
        pieces.append((cuts[i], cuts[j]))
        j = i
    return [
        Segment(
            text[words[first].start : words[last - 1].end],
            times[first],
            times[last],
        )
        for first, last in reversed(pieces)
    ]
