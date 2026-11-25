"""The fit planner: from real narration durations to the clips each shot needs.

Per shot it decides, before any video is generated:

* how many clips to generate and how long each is. A shot's narration is first fitted to ONE clip by
  changing playback speed by at most ``max_speed`` (1.3x either way). Only when that is not enough
  does it split the narration at natural boundaries (see :mod:`vidpipe.segmentation`) and add a
  *continuation clip* per extra segment, started from the previous clip's last frame;
* how each language's render plays those clips: at what speed, how much is trimmed, how long the
  shot lasts. A shot always lasts exactly as long as its narration in that language, so narration
  never outruns the picture and the picture never freezes.

``visuals`` decides who shares clips: ``shared`` (one clip set per shot, sized to the longer
narration, so the shorter language is sped up or trimmed to fit), ``per_language`` (a clip set per
language) or ``primary_only`` (the primary language's clips, which the other languages must fit).
Both renders must stay within ``max_render_s``.

Speed is a playback rate applied to the video: ``0.88`` plays a clip slower so it lasts longer than
it was generated, ``1.3`` plays it faster. Narration is never time-stretched.

The planner is pure: durations in, a :class:`~vidpipe.models.FitPlan` out. ``plan`` and ``run`` both
use it, so a dry-run shows exactly what a run would do.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from vidpipe.config import Visuals
from vidpipe.contracts import ImageToVideoCapabilities
from vidpipe.models import (
    ClipPlan,
    ClipUse,
    FitLimits,
    FitPlan,
    LanguageFit,
    SegmentPlan,
    ShotPlan,
    VisualSet,
)
from vidpipe.segmentation import Segment, segment_narration

#: Bump when the planning rules change: it is hashed into the fit-plan artifact.
FIT_VERSION = 2
MAX_SPEED = 1.3
MAX_RENDER_S = 90.0
#: Clip lengths are rounded up to a multiple of this.
QUANTUM_S = 0.25
_EPS = 1e-6


@dataclass(frozen=True)
class NarrationInput:
    text: str
    duration_s: float
    #: Estimated from the text rather than measured from generated audio.
    estimated: bool = False


@dataclass(frozen=True)
class ShotInput:
    shot_id: int
    narration: Mapping[str, NarrationInput]  # language -> narration


def limits_for(caps: ImageToVideoCapabilities) -> FitLimits:
    return FitLimits(
        min_clip_s=caps.min_seconds,
        max_clip_s=caps.max_seconds,
        max_speed=MAX_SPEED,
        max_render_s=MAX_RENDER_S,
    )


def _round_up(seconds: float) -> float:
    return math.ceil(seconds / QUANTUM_S - _EPS) * QUANTUM_S


def _play(clip_s: float, shot_s: float, max_speed: float) -> tuple[float, float] | None:
    """(speed, seconds of the clip used) to make a ``clip_s`` clip last ``shot_s``, or ``None`` when
    even the slowest allowed speed leaves the narration longer than the picture."""
    if shot_s > clip_s + _EPS:  # narration outlasts the clip: play it slower
        speed = clip_s / shot_s
        return None if speed < 1 / max_speed - _EPS else (speed, clip_s)
    if clip_s - shot_s <= QUANTUM_S + _EPS:  # only rounding to spare: trim it
        return 1.0, shot_s
    speed = min(clip_s / shot_s, max_speed)  # clearly longer: play it faster, trim what is left
    return speed, shot_s * speed


class _Planner:
    def __init__(self, limits: FitLimits) -> None:
        self.limits = limits
        self.problems: list[str] = []

    # ------------------------------------------------------------------------------ one clip set

    def _clip_length(self, seconds: float) -> float:
        low, high = self.limits.min_clip_s, self.limits.max_clip_s
        return min(high, max(low, _round_up(seconds)))

    def cut(self, narration: NarrationInput) -> list[Segment]:
        """The narration cut at natural boundaries into pieces that each fit one clip."""
        return segment_narration(
            narration.text,
            narration.duration_s,
            limit=self.limits.max_clip_s * self.limits.max_speed,
            soft_min=self.limits.min_clip_s,
        )

    def own_clips(
        self, driver: str, narration: NarrationInput, segments: Sequence[Segment]
    ) -> tuple[list[ClipPlan], list[ClipUse]]:
        """Clips sized to the driver's own segments, and how the driver's render plays them."""
        clips: list[ClipPlan] = []
        uses: list[ClipUse] = []
        for index, segment in enumerate(segments):
            length = self._clip_length(segment.seconds)
            clips.append(
                ClipPlan(
                    index=index,
                    seconds=length,
                    continues=index - 1 if index else None,
                    text=segment.text,
                )
            )
            played = _play(length, segment.seconds, self.limits.max_speed)
            speed, source = played if played else (1 / self.limits.max_speed, length)
            # The next clip starts on this clip's last frame. Play through that frame when
            # the segment can fit it within the speed cap.
            if index + 1 < len(segments) and source < length:
                full_speed = length / segment.seconds
                if full_speed <= self.limits.max_speed:
                    speed, source = full_speed, length
            uses.append(
                ClipUse(
                    clip=index,
                    speed=round(speed, 4),
                    source_s=round(source, 4),
                    seconds=round(source / speed, 4),
                )
            )
        return clips, uses

    def follow(
        self, shot_id: int, language: str, narration: NarrationInput, clips: Sequence[ClipPlan]
    ) -> list[ClipUse]:
        """How a language that did not size the clips plays them, as one run of video."""
        total = sum(c.seconds for c in clips)
        played = _play(total, narration.duration_s, self.limits.max_speed)
        if played is None:
            self.problems.append(
                f"shot {shot_id}: {language} narration is {narration.duration_s:.2f}s but its "
                f"clips last {total:.2f}s and can be slowed by at most {self.limits.max_speed}x; "
                "use visuals: shared or per_language"
            )
            return []
        speed, source = played
        uses: list[ClipUse] = []
        left = source
        for clip in clips:
            take = min(clip.seconds, left)
            if round(take, 4) <= 0:
                break
            left -= take
            uses.append(
                ClipUse(
                    clip=clip.index,
                    speed=round(speed, 4),
                    source_s=round(take, 4),
                    seconds=round(take / speed, 4),
                )
            )
        return uses

    # --------------------------------------------------------------------------------- one shot

    def checked(self, shot: ShotInput) -> ShotInput:
        """The shot, with any narration that has no length given the shortest clip length."""
        silent = [lang for lang, n in shot.narration.items() if n.duration_s <= 0]
        if not silent:
            return shot
        self.problems.append(f"shot {shot.shot_id}: {', '.join(silent)} narration has no duration")
        return ShotInput(
            shot.shot_id,
            {
                lang: NarrationInput(n.text, self.limits.min_clip_s, n.estimated)
                if lang in silent
                else n
                for lang, n in shot.narration.items()
            },
        )

    def shot(
        self,
        shot: ShotInput,
        sets: Sequence[tuple[str, str, Sequence[str]]],
    ) -> ShotPlan:
        visual_sets: dict[str, VisualSet] = {}
        fits: dict[str, LanguageFit] = {}
        for set_id, driver, languages in sets:
            driver_narration = shot.narration[driver]
            segments = self.cut(driver_narration)
            clips, driver_uses = self.own_clips(driver, driver_narration, segments)
            visual_sets[set_id] = VisualSet(
                id=set_id, driver=driver, languages=list(languages), clips=clips
            )
            for language in languages:
                narration = shot.narration[language]
                uses = (
                    driver_uses
                    if language == driver
                    else self.follow(shot.shot_id, language, narration, clips)
                )
                spans = segments if language == driver else self.cut(narration)
                fits[language] = LanguageFit(
                    language=language,
                    visual_set=set_id,
                    narration_s=round(narration.duration_s, 4),
                    estimated=narration.estimated,
                    seconds=round(narration.duration_s, 4),
                    clips=uses,
                    segments=self.segment_plans(spans, uses),
                )
        return ShotPlan(shot_id=shot.shot_id, visual_sets=visual_sets, languages=fits)

    @staticmethod
    def segment_plans(spans: Sequence[Segment], uses: Sequence[ClipUse]) -> list[SegmentPlan]:
        ends: list[float] = []
        elapsed = 0.0
        for use in uses:
            elapsed += use.seconds
            ends.append(elapsed)
        plans: list[SegmentPlan] = []
        for span in spans:
            middle = (span.start + span.end) / 2
            index = next((i for i, end in enumerate(ends) if middle < end), len(ends) - 1)
            clip = uses[index].clip if uses else 0
            plans.append(
                SegmentPlan(
                    text=span.text,
                    start_s=round(span.start, 4),
                    end_s=round(span.end, 4),
                    clip=clip,
                )
            )
        return plans


def _visual_sets(
    shot: ShotInput, languages: Sequence[str], primary: str, visuals: Visuals
) -> list[tuple[str, str, Sequence[str]]]:
    """(set id, driver language, languages using the set) for one shot."""
    if visuals is Visuals.PER_LANGUAGE:
        return [(lang, lang, [lang]) for lang in languages]
    if visuals is Visuals.PRIMARY_ONLY:
        return [(primary, primary, list(languages))]
    longest = max(languages, key=lambda lang: (shot.narration[lang].duration_s, lang == primary))
    return [("shared", longest, list(languages))]


def plan_fit(
    shots: Sequence[ShotInput],
    *,
    languages: Sequence[str],
    primary_language: str,
    visuals: Visuals,
    limits: FitLimits,
) -> FitPlan:
    """Plan every shot; ``problems`` on the result says why it cannot be used, if it cannot."""
    planner = _Planner(limits)
    shots = [planner.checked(shot) for shot in shots]
    planned = [
        planner.shot(shot, _visual_sets(shot, languages, primary_language, visuals))
        for shot in shots
    ]
    render_seconds = {
        lang: round(sum(s.languages[lang].seconds for s in planned), 4) for lang in languages
    }
    problems = planner.problems + [
        f"{lang} render would last {seconds:.1f}s, over the {limits.max_render_s:.0f}s limit"
        for lang, seconds in render_seconds.items()
        if seconds > limits.max_render_s + _EPS
    ]
    return FitPlan(
        visuals=visuals,
        limits=limits,
        shots=planned,
        render_seconds=render_seconds,
        problems=problems,
    )
