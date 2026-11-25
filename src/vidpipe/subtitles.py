"""Subtitles: cues, the sidecar SRT, the fonts libass needs and the ffmpeg ``subtitles`` filter.

Cues come ready-made from the fit plan (each segment of narration, timed within its shot); this
module turns them into an SRT file and into the filter that burns that file into a render. Amharic
needs a font with Ethiopic glyphs, which libass finds in a folder named by ``fontsdir``: vidpipe
bundles Noto Sans Ethiopic (SIL OFL 1.1, ``assets/fonts``) and checks at plan time that the font a
language needs is in the folder in use.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from vidpipe.config import SubtitleConfig

FONT_SUFFIXES = {".ttf", ".otf", ".ttc"}


class Cue(BaseModel):
    text: str
    #: Seconds from the start of the render.
    start_s: float
    end_s: float


# ---------------------------------------------------------------------------------------- SRT


def srt_timestamp(seconds: float) -> str:
    total_ms = round(max(seconds, 0.0) * 1000)
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_srt(cues: Sequence[Cue]) -> str:
    """The cues as SRT. A cue never runs past the next one's start, and empty cues are dropped."""
    kept = [c for c in cues if c.text.strip()]
    blocks: list[str] = []
    for number, cue in enumerate(kept, start=1):
        end = cue.end_s if number == len(kept) else min(cue.end_s, kept[number].start_s)
        blocks.append(
            f"{number}\n{srt_timestamp(cue.start_s)} --> {srt_timestamp(end)}\n{cue.text.strip()}\n"
        )
    return "\n".join(blocks)


def write_srt(path: Path, cues: Sequence[Cue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_srt(cues), encoding="utf-8", newline="\n")


# ------------------------------------------------------------------------- ffmpeg filter text


def escape_filter_value(value: str) -> str:
    """Escape ``value`` to be one option value in an ffmpeg filtergraph (``-filter_complex``).

    ffmpeg unescapes twice: the filtergraph parser first (it treats ``\\ ' [ ] , ;`` as special),
    then the filter's option parser (``\\ ' :``). So the text is escaped for the second level first
    and the result for the first. That is what makes ``C:`` in a Windows path, or a quote, comma or
    bracket in a folder name, arrive intact. Backslashes in paths are turned into ``/`` (which
    Windows accepts) rather than escaped, to keep the result readable.
    """
    value = value.replace("\\", "/")
    option_level = "".join("\\" + ch if ch in "\\':" else ch for ch in value)
    return "".join("\\" + ch if ch in "\\'[],;" else ch for ch in option_level)


def subtitles_filter(srt: Path, *, fonts_dir: Path | None, font: str | None, font_size: int) -> str:
    """The ``subtitles`` filter that burns ``srt`` in. ``font`` (a family found in ``fonts_dir``)
    is forced when given; otherwise libass picks its default font."""
    style = [f"FontSize={font_size}", "Outline=1.5", "Shadow=0", "MarginV=12"]
    if font:
        style.insert(0, f"FontName={font}")
    options = [f"filename={escape_filter_value(str(srt))}"]
    if fonts_dir is not None:
        options.append(f"fontsdir={escape_filter_value(str(fonts_dir))}")
    options.append(f"force_style={escape_filter_value(','.join(style))}")
    return "subtitles=" + ":".join(options)


# ----------------------------------------------------------------------------------------- fonts


def font_families(path: Path) -> set[str]:
    """Family names in a TrueType/OpenType font file (empty when it cannot be read)."""
    try:
        data = path.read_bytes()
        offsets = [0]
        if data[:4] == b"ttcf":  # a collection: one font per offset
            (count,) = struct.unpack(">I", data[8:12])
            offsets = list(struct.unpack(f">{count}I", data[12 : 12 + 4 * count]))
        names: set[str] = set()
        for base in offsets:
            (tables,) = struct.unpack(">H", data[base + 4 : base + 6])
            for i in range(tables):
                tag, _, offset, length = struct.unpack(">4sIII", data[base + 12 + 16 * i :][:16])
                if tag == b"name":
                    names |= _family_names(data[offset : offset + length])
        return names
    except (OSError, struct.error):
        return set()


def _family_names(table: bytes) -> set[str]:
    count, string_offset = struct.unpack(">HH", table[2:6])
    names: set[str] = set()
    for i in range(count):
        platform, _, _, name_id, length, offset = struct.unpack(
            ">HHHHHH", table[6 + 12 * i : 18 + 12 * i]
        )
        if name_id not in (1, 16):  # family, typographic family
            continue
        raw = table[string_offset + offset : string_offset + offset + length]
        names.add(raw.decode("utf-16-be" if platform in (0, 3) else "latin-1", errors="ignore"))
    return names


def font_files(fonts_dir: Path, family: str) -> list[Path]:
    """The font files in ``fonts_dir`` that belong to ``family`` (compared case-insensitively)."""
    wanted = family.casefold()
    return sorted(
        path
        for path in fonts_dir.iterdir()
        if path.suffix.lower() in FONT_SUFFIXES
        and wanted in {name.casefold() for name in font_families(path)}
    )


def bundled_fonts_dir() -> Path | None:
    """The fonts shipped with vidpipe: in an installed package, or in a checkout's assets/fonts."""
    here = Path(__file__).resolve()
    for candidate in (here.parent / "_fonts", here.parents[2] / "assets" / "fonts"):
        if candidate.is_dir():
            return candidate
    return None


def resolve_fonts_dir(project_root: Path, config: SubtitleConfig) -> Path:
    """Where libass looks for fonts: the configured folder (relative to the project), else the
    project's ``fonts/`` if it exists, else the bundled fonts."""
    if config.fonts_dir:
        configured = Path(config.fonts_dir).expanduser()
        return configured if configured.is_absolute() else project_root / configured
    own = project_root / "fonts"
    if own.is_dir():
        return own
    return bundled_fonts_dir() or own


def font_problems(
    config: SubtitleConfig, languages: Sequence[str], project_root: Path
) -> list[str]:
    """Why burned-in subtitles cannot be drawn with the configured fonts (empty when they can)."""
    needed = {lang: family for lang, family in config.fonts.items() if lang in languages}
    if not config.burn_in or not needed:
        return []
    fonts_dir = resolve_fonts_dir(project_root, config)
    fix = "set `subtitles.fonts_dir` in vidpipe.yaml to a folder that has it"
    if not fonts_dir.is_dir():
        return [f"subtitles: fonts folder {fonts_dir} does not exist; {fix}"]
    return [
        f"subtitles: font {family!r} (for language {lang!r}) is not in the fonts folder "
        f"{fonts_dir}; {fix}, or change `subtitles.fonts`"
        for lang, family in needed.items()
        if not font_files(fonts_dir, family)
    ]
