"""Script translation through the text contract, with a back-translation check.

:class:`TextTranslator` is a :class:`~vidpipe.contracts.TranslationProvider` made of a chain of text
providers (``translation: [gemini-cli, claude-cli]`` in ``vidpipe.yaml``). It translates the
script lines in one request, numbered, and rejects (so the model is re-prompted) a reply that loses,
invents or renumbers a line, or leaves a line without the target language's script.

The check (:meth:`TextTranslator.review`) runs after translating. It asks a model to translate the
target text back to English *without seeing the source*, then to compare that back-translation with
the source line by line. Each line comes out ``ok`` or ``drift`` (with a short reason). Which model
checks:

* **The checker is never the translator when the chain has another provider.** The translator is
  the chain member that answered the translation (recorded in the artifact, so it is known on a
  later run); the checker is built from the *other* members only. If all of them fail, the check
  fails: it does not quietly fall back to the translator.
* A chain with no other distinct provider (one provider, or the same one listed twice) runs the
  check anyway with the translator itself, and the review records ``same_model: true``.

Two members are the "same model" when their ``fingerprint()`` (name and options) is equal, so
``gemini-cli`` with two different ``model:`` options counts as two models.

The review is written next to the translation as ``translation/<lang>.review.json`` (a
:class:`TranslationReview`) and its drifted line ids are in the ledger record's ``data``, so a gate
or report can show them. :func:`drift_flags` and :func:`report_lines` read them back.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from vidpipe.artifacts import digest
from vidpipe.contracts import (
    TextProvider,
    TranslationCapabilities,
    TranslationProvider,
    TranslationRequest,
    TranslationResponse,
    UnsupportedRequest,
)
from vidpipe.models import Script, ScriptLine
from vidpipe.project import Project
from vidpipe.text import FallbackTextProvider, TextProviderError, ask, failure_count, fallback_note

#: Languages the text translator is declared (and checked) for: English to Amharic is the demo.
LANGUAGES = frozenset({"en", "am"})
LANGUAGE_NAMES = {"en": "English", "am": "Amharic"}
#: Back-translation goes to this language, the one a reviewer reads (and the script's source).
REVIEW_LANGUAGE = "en"

#: The Unicode blocks of the Ge'ez (Ethiopic) script. A translation into a language written in it
#: must contain some, which catches a model that answers in English or in Latin transliteration.
_ETHIOPIC = re.compile("[ሀ-᎟ⶀ-⷟꬀-꬯]")
SCRIPT_PATTERNS: dict[str, re.Pattern[str]] = {"am": _ETHIOPIC}

DriftStatus = Literal["ok", "drift"]


class TranslationError(Exception):
    """The translation (or its check) could not be completed."""


# ---------------------------------------------------------------------------------- reply models


class NumberedLine(BaseModel):
    id: int
    text: str


class NumberedLines(BaseModel):
    lines: list[NumberedLine] = Field(min_length=1)


class Verdict(BaseModel):
    id: int
    status: DriftStatus
    reason: str = ""


class Verdicts(BaseModel):
    lines: list[Verdict] = Field(min_length=1)


# ----------------------------------------------------------------------------------- the review


class LineCheck(BaseModel):
    id: int
    status: DriftStatus
    source: str
    translation: str
    back_translation: str
    #: Why the line drifted (one sentence); empty when ``status`` is ``ok``.
    reason: str = ""


class TranslationReview(BaseModel):
    """The back-translation check of one translated script (``translation/<lang>.review.json``)."""

    language: str
    source_language: str
    #: Provider(s) that translated and checked (names, as in the ledger).
    translator: str
    checker: str
    #: The checker was the translator: the chain had no other distinct provider.
    same_model: bool
    lines: list[LineCheck]

    @property
    def drifted(self) -> list[LineCheck]:
        return [line for line in self.lines if line.status == "drift"]


class DriftFlag(BaseModel):
    """One line a human should review: the shape later tickets (gates, report) consume."""

    language: str
    line_id: int
    source: str
    translation: str
    back_translation: str
    reason: str


@dataclass
class Translated:
    script: Script
    #: Small result values for the ledger: who translated (needed again by the check).
    data: dict[str, Any]
    fallback: str | None


@dataclass
class Reviewed:
    review: TranslationReview
    fallback: str | None


# --------------------------------------------------------------------------------------- checks


def _same_ids(expected: Sequence[int], got: Sequence[int]) -> None:
    """Raise ``ValueError`` (so the model is re-prompted) unless ``got`` is exactly ``expected``."""
    problems: list[str] = []
    if duplicated := sorted({i for i in got if list(got).count(i) > 1}):
        problems.append(f"ids repeated: {duplicated}")
    if missing := sorted(set(expected) - set(got)):
        problems.append(f"lines missing: {missing}")
    if unknown := sorted(set(got) - set(expected)):
        problems.append(f"ids that are not in the request: {unknown}")
    if problems:
        raise ValueError(
            f"reply must contain exactly the ids {list(expected)}: " + "; ".join(problems)
        )


def _lines_by_id(lines: Sequence[NumberedLine]) -> dict[int, str]:
    return {line.id: line.text for line in lines}


# -------------------------------------------------------------------------------- prompt texts

_TRANSLATE = (
    "Translate the numbered narration lines of a short video from {source} into {target}. The "
    "translation is read aloud as narration, so write natural, spoken {target}, not a word-for-"
    "word rendering.\n\n"
    "Rules:\n"
    "- Return every line, with the same `id` it has below, exactly once. Do not merge, split, "
    "drop, add or renumber lines.\n"
    "- Keep the meaning, names, numbers and tone of each line.{script_rule}\n"
    "- Plain text only: no notes, transliteration or markup.\n\n"
    "Lines:\n{lines}"
)
_BACK_TRANSLATE = (
    "Below are numbered narration lines in {language}. Translate each one into English as "
    "literally and faithfully as you can. This is a check of the {language} text, so translate "
    "what is actually written: do not smooth it over, improve it or guess what it was meant to "
    "say.\n\n"
    "Return every line with the same `id` it has below, exactly once.\n\n"
    "Lines:\n{lines}"
)
_COMPARE = (
    "A narration script was translated from English into {language} and then translated back to "
    "English by someone who never saw the original. For each numbered line below you get the "
    "ORIGINAL English line and the BACK-TRANSLATION.\n\n"
    "Decide per line whether the back-translation still says what the original says: same "
    "events, people, things, numbers, order and tone. Differences of wording or style are fine. "
    "Set `status` to `ok`, or to `drift` when meaning was lost, added or changed. For `drift` "
    "give a short `reason` (one sentence) saying what changed; for `ok` leave `reason` empty.\n\n"
    "Return every line with the same `id`, exactly once.\n\n"
    "{lines}"
)
#: Hashed into the provider's fingerprint: rewording a prompt regenerates what it produced.
_PROMPTS = digest([_TRANSLATE, _BACK_TRANSLATE, _COMPARE])


def _numbered(texts: Sequence[str], ids: Sequence[int]) -> str:
    return "\n".join(f"{i}. {text}" for i, text in zip(ids, texts, strict=True))


# -------------------------------------------------------------------------------- the provider


class TextTranslator(TranslationProvider):
    """Translation by a chain of text providers, with a back-translation check by another one."""

    capabilities = TranslationCapabilities(source_languages=LANGUAGES, target_languages=LANGUAGES)

    def __init__(self, providers: Sequence[TextProvider]) -> None:
        if not providers:
            raise ValueError("a translation chain needs at least one text provider")
        super().__init__()
        self.providers = list(providers)
        self.chain = FallbackTextProvider(self.providers)

    @property
    def name(self) -> str:  # pyright: ignore[reportIncompatibleVariableOverride]
        """``gemini-cli > claude-cli``: what plan, the manifest and the ledger show."""
        return self.chain.name

    def fingerprint(self) -> dict[str, Any]:
        return {"name": self.name, "chain": self.chain.fingerprint(), "prompts": _PROMPTS}

    # ------------------------------------------------------------------------ translating

    def translate(self, request: TranslationRequest) -> TranslationResponse:
        caps = self.capabilities
        if request.source_language not in caps.source_languages:
            raise UnsupportedRequest(f"source language {request.source_language!r}")
        if request.target_language not in caps.target_languages:
            raise UnsupportedRequest(f"target language {request.target_language!r}")
        ids = list(range(1, len(request.texts) + 1))  # the stage maps these back to line ids
        script_pattern = SCRIPT_PATTERNS.get(request.target_language)

        def check(reply: NumberedLines) -> None:
            _same_ids(ids, [line.id for line in reply.lines])
            by_id = _lines_by_id(reply.lines)
            if blank := [i for i in ids if not by_id[i].strip()]:
                raise ValueError(f"lines are blank: {blank}")
            if script_pattern is not None:
                wrong = [
                    i
                    for i, source in zip(ids, request.texts, strict=True)
                    if any(c.isalpha() for c in source) and not script_pattern.search(by_id[i])
                ]
                if wrong:
                    target = LANGUAGE_NAMES.get(request.target_language, request.target_language)
                    raise ValueError(f"lines {wrong} are not written in {target} script")

        prompt = _TRANSLATE.format(
            source=LANGUAGE_NAMES.get(request.source_language, request.source_language),
            target=LANGUAGE_NAMES.get(request.target_language, request.target_language),
            script_rule=(
                " Write in Ge'ez (Ethiopic) script." if request.target_language == "am" else ""
            ),
            lines=_numbered(request.texts, ids),
        )
        reply = ask(self.chain, prompt, NumberedLines, check)
        by_id = _lines_by_id(reply.lines)
        return TranslationResponse(texts=[by_id[i].strip() for i in ids])

    @property
    def translated_by(self) -> TextProvider | None:
        """The chain member that answered the most recent translation."""
        index = self.chain.last_index
        return None if index is None else self.providers[index]

    # --------------------------------------------------------------------------- checking

    def checkers(self, translator: dict[str, Any] | None) -> tuple[list[TextProvider], bool]:
        """The providers that may check a translation by ``translator`` (a fingerprint), and
        whether they are the translator itself (no other distinct provider exists)."""
        others = [p for p in self.providers if p.fingerprint() != translator]
        return (others, False) if others else (list(self.providers), True)

    def review(
        self,
        source: Script,
        translated: Script,
        *,
        translator: str,
        translator_fingerprint: dict[str, Any] | None,
    ) -> Reviewed:
        """Back-translate ``translated`` and compare it with ``source``, line by line."""
        pool, same_model = self.checkers(translator_fingerprint)
        ids = [line.id for line in source.lines]
        target = LANGUAGE_NAMES.get(translated.language, translated.language)
        answered: list[str] = []
        notes: list[str] = []

        def ask_pool[M: BaseModel](
            providers: list[TextProvider],
            prompt: str,
            model: type[M],
            check: Callable[[M], None],
        ) -> tuple[M, FallbackTextProvider]:
            chain = FallbackTextProvider(providers)
            since = failure_count(chain)
            reply = ask(chain, prompt, model, check)
            if note := fallback_note(chain, since):
                notes.append(note)
            if chain.last_used is not None and chain.last_used not in answered:
                answered.append(chain.last_used)
            return reply, chain

        def check_ids(reply: NumberedLines | Verdicts) -> None:
            _same_ids(ids, [line.id for line in reply.lines])

        def check_back(reply: NumberedLines) -> None:
            check_ids(reply)
            if blank := [line.id for line in reply.lines if not line.text.strip()]:
                raise ValueError(f"lines are blank: {blank}")

        def check_verdicts(reply: Verdicts) -> None:
            check_ids(reply)
            if bare := [v.id for v in reply.lines if v.status == "drift" and not v.reason.strip()]:
                raise ValueError(f"lines {bare} are marked drift but give no reason")

        back_prompt = _BACK_TRANSLATE.format(
            language=target,
            lines=_numbered([line.text for line in translated.lines], ids),
        )
        try:
            back, chain = ask_pool(pool, back_prompt, NumberedLines, check_back)
            back_by_id = _lines_by_id(back.lines)
            # Compare with the member that back-translated, falling back to the rest of the pool.
            first = pool[0] if chain.last_index is None else pool[chain.last_index]
            ordered = [first, *(p for p in pool if p is not first)]
            comparison = "\n\n".join(
                f"{line.id}.\nORIGINAL: {line.text}\nBACK-TRANSLATION: {back_by_id[line.id]}"
                for line in source.lines
            )
            compare_prompt = _COMPARE.format(language=target, lines=comparison)
            verdict, _ = ask_pool(ordered, compare_prompt, Verdicts, check_verdicts)
        except TextProviderError as exc:
            raise TranslationError(f"back-translation check failed: {exc}") from exc

        verdict_by_id = {v.id: v for v in verdict.lines}
        translated_by_id = {line.id: line.text for line in translated.lines}
        checks = [
            LineCheck(
                id=line.id,
                status=verdict_by_id[line.id].status,
                source=line.text,
                translation=translated_by_id[line.id],
                back_translation=back_by_id[line.id].strip(),
                reason=verdict_by_id[line.id].reason.strip(),
            )
            for line in source.lines
        ]
        review = TranslationReview(
            language=translated.language,
            source_language=source.language,
            translator=translator,
            checker=" + ".join(answered),
            same_model=same_model,
            lines=checks,
        )
        return Reviewed(review=review, fallback="; ".join(notes) or None)


# ----------------------------------------------------------------------------------- the stage


def translate_script(provider: TranslationProvider, script: Script, target: str) -> Translated:
    """Translate ``script`` into ``target``: the same line ids, in order."""
    since = failure_count(provider.chain) if isinstance(provider, TextTranslator) else 0
    try:
        response = provider.translate(
            TranslationRequest(
                texts=[line.text for line in script.lines],
                source_language=script.language,
                target_language=target,
            )
        )
    except TextProviderError as exc:
        raise TranslationError(str(exc)) from exc
    if len(response.texts) != len(script.lines):
        raise TranslationError(f"translation into {target!r} returned the wrong number of lines")
    translated = Script(
        language=target,
        title=script.title,
        lines=[
            ScriptLine(id=line.id, text=text)
            for line, text in zip(script.lines, response.texts, strict=True)
        ],
    )
    if not isinstance(provider, TextTranslator):
        return Translated(script=translated, data={}, fallback=None)
    by = provider.translated_by
    return Translated(
        script=translated,
        data={
            "translator": by.name if by else provider.name,
            "translator_fingerprint": by.fingerprint() if by else None,
        },
        fallback=fallback_note(provider.chain, since),
    )


def review_path(language: str) -> str:
    """Where ``language``'s review lives, relative to ``build/``."""
    return f"translation/{language}.review.json"


def drift_flags(project: Project) -> list[DriftFlag]:
    """Every drifted line of every translation that has been checked, for a gate or report."""
    flags: list[DriftFlag] = []
    for language in project.config.languages[1:]:
        if not (project.build / review_path(language)).is_file():
            continue
        review = project.read_model(review_path(language), TranslationReview)
        flags += [
            DriftFlag(
                language=language,
                line_id=line.id,
                source=line.source,
                translation=line.translation,
                back_translation=line.back_translation,
                reason=line.reason,
            )
            for line in review.drifted
        ]
    return flags


def report_lines(project: Project) -> list[str]:
    """Human-readable warnings about translations that need review (empty when all is well)."""
    out: list[str] = []
    for language in project.config.languages[1:]:
        if not (project.build / review_path(language)).is_file():
            continue
        review = project.read_model(review_path(language), TranslationReview)
        if review.same_model:
            out.append(
                f"warning: translation {language} was checked by the same model that translated "
                f"it ({review.translator}): no other provider was available"
            )
        for line in review.drifted:
            out += [
                f"warning: translation {language} line {line.id} may have drifted: {line.reason}",
                f"  en:   {line.source}",
                f"  {language}:   {line.translation}",
                f"  back: {line.back_translation}",
            ]
        if review.drifted:
            out.append(f"review: build/{review_path(language)}")
    return out
