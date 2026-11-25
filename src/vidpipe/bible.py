"""The project bible (``bible.yaml``): who and where the story is about, and how it looks.

::

    style: {description: "Warm painterly storybook illustration."}
    characters:                      # the first one is the protagonist
      - id: aster
        name: Aster
        description: "A girl in an indigo dress."
        reference: bible/aster.png
    locations:
      - {id: village, name: the village, description: "Thatched stone houses on green slopes."}

Each entry has a ``description`` (English), a ``reference`` picture (a path relative to the project
directory), or both. A keyframe gets pictures for as many entries as its provider accepts, the
character first, then the location, then the style (ADR 0001); the prompt calls them "image 1",
"image 2". An entry whose picture is not passed contributes its description in words instead.

A storyboard shot names its ``character`` and ``location`` by id. A shot without a ``character``
shows the protagonist (``none``: nobody); a shot without a ``location`` has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

BIBLE_FILENAME = "bible.yaml"
#: A shot's ``character`` when no character appears in it.
NO_CHARACTER = "none"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


class BibleError(Exception):
    pass


class _Described(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = ""
    #: A picture of it, relative to the project directory (or absolute).
    reference: str | None = None

    @model_validator(mode="after")
    def _says_something(self) -> _Described:
        if not self.description.strip() and not self.reference:
            raise ValueError("give a description, a reference image, or both")
        return self


class Style(_Described):
    pass


class Entry(_Described):
    """A character or a location."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    #: How the prompt calls it (default: the id).
    name: str = ""

    @property
    def title(self) -> str:
        return self.name.strip() or self.id


class Bible(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: Style | None = None
    characters: list[Entry] = Field(default_factory=list[Entry])
    locations: list[Entry] = Field(default_factory=list[Entry])

    @model_validator(mode="after")
    def _distinct_ids(self) -> Bible:
        for kind, entries in (("character", self.characters), ("location", self.locations)):
            ids = [e.id for e in entries]
            if repeated := sorted({i for i in ids if ids.count(i) > 1}):
                raise ValueError(f"{kind} ids used twice: {', '.join(repeated)}")
            if NO_CHARACTER in ids:
                raise ValueError(f"{NO_CHARACTER!r} cannot be a {kind} id")
        return self

    def cast(
        self, character: str | None, location: str | None
    ) -> tuple[Entry | None, Entry | None]:
        """The entries a shot shows; :class:`BibleError` for an id the bible does not have."""
        found: list[Entry | None] = []
        default = self.characters[0] if self.characters else None
        for kind, wanted, entries, unnamed in (
            ("character", character, self.characters, default),
            ("location", location, self.locations, None),
        ):
            if wanted is None:
                found.append(unnamed)
            elif wanted == NO_CHARACTER:
                found.append(None)
            else:
                entry = next((e for e in entries if e.id == wanted), None)
                if entry is None:
                    known = ", ".join(e.id for e in entries) or "none defined"
                    raise BibleError(f"the bible has no {kind} {wanted!r} ({kind}s: {known})")
                found.append(entry)
        return found[0], found[1]

    def casting_instructions(self) -> str:
        """What the storyboarding model is told about the cast (empty without entries). Only ids
        and names, so rewording a description does not re-storyboard the video."""
        parts: list[str] = []
        if self.characters:
            parts.append(
                f'- `character`: the id of the character the shot shows, or "{NO_CHARACTER}" if '
                f"none appears. Characters:\n"
                + "\n".join(f"  - {e.id}: {e.title}" for e in self.characters)
            )
        if self.locations:
            parts.append(
                "- `location`: the id of the location where the shot takes place, or null if it "
                "is none of these. Locations:\n"
                + "\n".join(f"  - {e.id}: {e.title}" for e in self.locations)
            )
        return "\n".join(parts)


def load_bible(root: Path) -> Bible:
    """The project's bible; an empty one when there is no ``bible.yaml``."""
    path = root / BIBLE_FILENAME
    if not path.is_file():
        return Bible()
    try:
        return Bible.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        raise BibleError(f"{path}: invalid bible: {exc}") from exc


def reference_problems(bible: Bible, root: Path) -> list[str]:
    """Reference pictures that are named but cannot be used."""
    named = [(e.id, e.reference) for e in (*bible.characters, *bible.locations)]
    if bible.style is not None:
        named.append(("style", bible.style.reference))
    found: list[str] = []
    for entry, reference in named:
        if reference is None:
            continue
        if not (root / reference).is_file():
            found.append(f"bible: the reference image of {entry!r} does not exist: {reference}")
        elif Path(reference).suffix.lower() not in IMAGE_SUFFIXES:
            found.append(
                f"bible: the reference of {entry!r} is not an image "
                f"({', '.join(IMAGE_SUFFIXES)}): {reference}"
            )
    return found


@dataclass(frozen=True)
class Reference:
    id: str
    #: As written in the bible.
    name: str
    path: Path


@dataclass(frozen=True)
class KeyframeBrief:
    """What the keyframer is asked to draw for one shot."""

    prompt: str
    references: list[Reference]


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text[-1] in ".!?" else f"{text}."


def keyframe_brief(
    bible: Bible,
    root: Path,
    visual: str,
    *,
    character: str | None,
    location: str | None,
    max_references: int,
) -> KeyframeBrief:
    """The prompt and reference images for a shot whose storyboard description is ``visual``."""
    who, where = bible.cast(character, location)
    references: list[Reference] = []

    def image(entry_id: str, entry: _Described) -> int | None:
        """Pass the entry's picture if there is one and room for it; its "image N" number."""
        if entry.reference is None or len(references) >= max_references:
            return None
        references.append(Reference(entry_id, entry.reference, root / entry.reference))
        return len(references)

    sentences: list[str] = []
    if who is not None:
        if number := image(who.id, who):
            sentences.append(
                f"Main character: {who.title}, shown in image {number}. Keep the same face, hair "
                f"and clothes as in image {number}."
            )
        else:
            sentences.append(f"Main character: {who.title}. {_sentence(who.description)}")
    if where is not None:
        if number := image(where.id, where):
            sentences.append(f"Setting: {where.title}, the place shown in image {number}.")
        else:
            sentences.append(f"Setting: {where.title}. {_sentence(where.description)}")
    if (style := bible.style) is not None:
        words = _sentence(style.description)
        if number := image("style", style):
            words = f"{words} Match the art style of image {number}.".strip()
        if words:
            sentences.append(f"Style: {words}")
    if not sentences:
        return KeyframeBrief(visual.strip(), references)
    prompt = " ".join(s.strip() for s in (_sentence(visual), *sentences))
    return KeyframeBrief(prompt.strip(), references)
