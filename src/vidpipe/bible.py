"""The project bible (``bible.yaml``): who and where the story is about, and how it looks.

::

    style: {description: "Photorealistic documentary footage, soft morning light."}
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

Without a ``style``, every shot gets :data:`DEFAULT_LOOK`: the video model animates live-action
footage far better than illustration, so realism is the default and a style is the exception.

A storyboard shot names its ``character`` and ``location`` by id. A shot without a ``character``
shows the protagonist (``none``: nobody); a shot without a ``location`` has none. A shot may also
list ``others``: the ids of further bible characters seen in it, who are described in words in its
keyframe prompt so they look the same in every shot. Without that list, the characters its visual
mentions by id or name count as its others. ``people``, when the storyboard gives it, is said in so
many words: the image model fills empty space with strangers unless told how many people there are.

Why each sentence is there: ``docs/research/model-strengths.md``.
"""

from __future__ import annotations

import re
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

    def mentioned_in(self, text: str) -> bool:
        """Whether ``text`` mentions this entry as present, by id (``wise-elder`` as "wise elder")
        or name, either without a leading article. A possessive ("the lion's whisker") does not
        count: the lion need not be in the picture."""
        names = {re.sub(r"[-_]", " ", self.id), self.title}
        names |= {re.sub(r"^(?:the|a|an)\s+", "", n, flags=re.IGNORECASE) for n in names}
        return any(
            re.search(rf"\b{re.escape(n)}\b(?!['\u2019]s\b)", text, flags=re.IGNORECASE)
            for n in names
        )


#: The look of every shot when the bible sets no style. Camera, lens and the direction of the
#: light make FLUX.2 more photographic than "realistic" alone; the video model animates
#: photographic footage far better than illustration.
DEFAULT_LOOK = (
    "Photorealistic live-action film still, shot on a cinema camera with a 35 mm lens: real "
    "people, places and materials, natural light with a clear direction, realistic skin texture, "
    "sharp focus on the subject. No illustration, painting or animation."
)

#: Said in every keyframe prompt, whatever the style: the image model otherwise adds captions,
#: insets and split panels, and the video model animates one continuous picture.
FRAME = (
    "One continuous full-frame image with a single composition: no text, captions, borders, split "
    "panels or inset pictures."
)

_COUNT_WORDS = {2: "two", 3: "three", 4: "four"}


def headcount(people: int | None) -> str:
    """How many people the picture shows, as said to the image model (empty when unknown). Stated
    positively, as there is no negative prompt in the distilled model."""
    if people is None:
        return ""
    if people == 0:
        return "No people anywhere in the picture."
    if people == 1:
        return "Exactly one person in the picture, with no other people anywhere in the background."
    return (
        f"Exactly {_COUNT_WORDS.get(people, str(people))} people in the picture, each shown once, "
        "with nobody else in the background."
    )


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

    @property
    def look(self) -> str:
        """How every shot should look: the style's description, or :data:`DEFAULT_LOOK`."""
        described = self.style.description.strip() if self.style else ""
        return described or DEFAULT_LOOK

    def others(self, ids: list[str] | None, visual: str, main: Entry | None) -> list[Entry]:
        """The characters besides ``main`` that a shot shows: ``ids`` when the storyboard lists
        them, else those ``visual`` mentions. :class:`BibleError` for an id the bible lacks."""
        if ids is None:
            return [e for e in self.characters if e is not main and e.mentioned_in(visual)]
        found: list[Entry] = []
        for wanted in ids:
            entry = next((e for e in self.characters if e.id == wanted), None)
            if entry is None:
                known = ", ".join(e.id for e in self.characters) or "none defined"
                raise BibleError(f"the bible has no character {wanted!r} (characters: {known})")
            if entry is not main and entry not in found:
                found.append(entry)
        return found

    def casting_instructions(self) -> str:
        """What the storyboarding model is told about the cast (empty without entries). It sees
        every description, so it does not invent clothes that contradict them; rewording one
        re-storyboards the video."""

        def listed(entries: list[Entry]) -> str:
            return "\n".join(
                f"  - {e.id}: {e.title}"
                + (f". {_sentence(e.description)}" if e.description.strip() else "")
                for e in entries
            )

        parts: list[str] = []
        if self.characters:
            parts.append(
                f'- `character`: the id of the character the shot is about, or "{NO_CHARACTER}" if '
                "no character appears. Characters (each description is sent to the image model "
                f"with every shot they appear in):\n{listed(self.characters)}\n"
                "- `others`: the ids of the other characters from this list who are also seen in "
                "the shot, or [] if none.\n"
                "- In `visual`, call these characters by their names. Never give them other "
                "clothes, hair, age or skin than their description says; repeat a detail from it "
                "word for word if it helps, and otherwise describe only their pose, expression and "
                "place in the frame."
            )
        if self.locations:
            parts.append(
                "- `location`: the id of the location where the shot takes place, or null if it "
                f"is none of these. Locations:\n{listed(self.locations)}"
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
    others: list[str] | None = None,
    people: int | None = None,
) -> KeyframeBrief:
    """The prompt and reference images for a shot whose storyboard description is ``visual``.

    In the order FLUX.2 weighs most: the shot itself, who is in it, how many people, where, then
    the look. Every bible character in the shot is described, not just the main one, so a
    secondary character (the lion) keeps its look from shot to shot."""
    who, where = bible.cast(character, location)
    company = bible.others(others, visual, who)
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
    for entry in company:
        # In words: the reference slots go to the main character, the place and the style.
        # Worded as the one the visual already names: "Also in the shot: the lion" drew two lions.
        title = entry.title[0].upper() + entry.title[1:]
        description = f": {_sentence(entry.description)}" if entry.description.strip() else "."
        sentences.append(f"{title} appears exactly once in the picture{description}")
    if count := headcount(people):
        sentences.append(count)
    if who is not None and (people is None or people >= 2):
        # Without this, the character's description is applied to everyone in the picture.
        sentences.append(
            "Anyone else in the shot looks clearly different from the main character: another "
            "age, other clothes and hair."
        )
    if where is not None:
        if number := image(where.id, where):
            sentences.append(f"Setting: {where.title}, the place shown in image {number}.")
        else:
            sentences.append(f"Setting: {where.title}. {_sentence(where.description)}")
    words = _sentence(bible.look)
    if bible.style is not None and (number := image("style", bible.style)):
        words = f"{words} Match the look of image {number}."
    sentences.append(FRAME)
    sentences.append(f"Style: {words}")
    prompt = " ".join(s.strip() for s in (_sentence(visual), *sentences))
    return KeyframeBrief(prompt.strip(), references)
