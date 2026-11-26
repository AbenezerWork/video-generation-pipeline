"""Subtitles: cues, the sidecar SRT, the fonts libass needs and the ffmpeg ``subtitles`` filter.

Cues come ready-made from the fit plan (each segment of narration, timed within its shot); this
module turns them into an SRT file and into the filter that burns that file into a render. Amharic
needs a font with Ethiopic glyphs, which libass finds in a folder named by ``fontsdir``: vidpipe
bundles Noto Sans Ethiopic (SIL OFL 1.1, ``assets/fonts``) and checks at plan time that the font a
language needs is in the folder in use.
"""

from __future__ import annotations

import struct
import textwrap
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


def wrap_cue(cue: Cue, *, columns: int) -> list[Cue]:
    """Wrap to 42 columns and at most two lines, dividing the cue time if needed."""
    lines = textwrap.wrap(" ".join(cue.text.split()), width=columns, break_on_hyphens=False)
    pages = ["\n".join(lines[i : i + 2]) for i in range(0, len(lines), 2)]
    if not pages:
        return []
    span = (cue.end_s - cue.start_s) / len(pages)
    return [
        Cue(
            text=text,
            start_s=cue.start_s + i * span,
            end_s=cue.end_s if i + 1 == len(pages) else cue.start_s + (i + 1) * span,
        )
        for i, text in enumerate(pages)
    ]


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


def subtitle_layout(width: int, height: int, font_size: int) -> tuple[int, int, int]:
    """Return libass font size, bottom margin and approximate text columns."""
    portrait = width < height
    # Limit the size of two lines so they fit within the caption band.
    short_side_size = min(font_size, 14 if portrait else 36)
    size = max(1, round(short_side_size * min(width, height) / height))
    play_width = 288 * width / height
    columns = max(1, min(42, int((play_width - 20) / (0.65 * size))))
    return size, 52 if portrait else 12, columns


def subtitles_filter(
    srt: Path,
    *,
    fonts_dir: Path | None,
    font: str | None,
    font_size: int,
    margin_v: int,
) -> str:
    """The ``subtitles`` filter that burns ``srt`` in. ``font`` (a family found in ``fonts_dir``)
    is forced when given; otherwise libass picks its default font."""
    style = [
        f"FontSize={font_size}",
        "Outline=1.5",
        "Shadow=0",
        f"MarginV={margin_v}",
        "WrapStyle=2",
    ]
    if font:
        style.insert(0, f"FontName={font}")
    options = [f"filename={escape_filter_value(str(srt))}"]
    if fonts_dir is not None:
        options.append(f"fontsdir={escape_filter_value(str(fonts_dir))}")
    options.append(f"force_style={escape_filter_value(','.join(style))}")
    return "subtitles=" + ":".join(options)


def ass_filter(ass: Path, *, fonts_dir: Path | None) -> str:
    """The ``subtitles`` filter that draws an ``.ass`` file as it is styled (no forced style)."""
    options = [f"filename={escape_filter_value(str(ass))}"]
    if fonts_dir is not None:
        options.append(f"fontsdir={escape_filter_value(str(fonts_dir))}")
    return "subtitles=" + ":".join(options)


# -------------------------------------------------------------------------------------- end card

#: The card's script height; sizes below are in these units (as for burned-in subtitles).
CARD_PLAY_RES_Y = 288


def _ass_time(seconds: float) -> str:
    centis = round(max(seconds, 0.0) * 100)
    hours, rest = divmod(centis, 360_000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_text(line: str) -> str:
    """Plain text as ASS dialogue text: no override blocks, no line-break escapes."""
    return line.replace("\\", "/").replace("{", "(").replace("}", ")").strip()


def end_card_ass(text: str, *, font: str | None, width: int, height: int, seconds: float) -> str:
    """An ASS script drawing the end card: ``text``'s first line as a headline, the others smaller
    and dimmer beneath it, centred, fading in and out over ``seconds``."""
    lines = [_ass_text(line) for line in text.splitlines() if line.strip()]
    headline, rest = (lines[0], lines[1:]) if lines else ("", [])
    play_x = round(CARD_PLAY_RES_Y * width / height)
    face = font or "Arial"
    newline = "\\N"  # ASS's hard line break
    body = newline.join(rest)
    dialogue = r"{\fs24\b1\c&HFFFFFF&}" + headline
    if body:
        # A small blank line between the headline and the rest, then the rest smaller and dimmer.
        dialogue += newline + r"{\fs8} " + newline + r"{\fs12\b0\c&HC8C8C8&}" + body
    fade_in, fade_out = round(min(0.8, seconds / 4) * 1000), round(min(0.6, seconds / 5) * 1000)
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {play_x}",
            f"PlayResY: {CARD_PLAY_RES_Y}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
            "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Card,{face},12,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,"
            "0,0,1,0,0,5,36,36,0,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            f"Dialogue: 0,{_ass_time(0)},{_ass_time(seconds)},Card,,0,0,0,,"
            rf"{{\an5\fad({fade_in},{fade_out})}}{dialogue}",
            "",
        ]
    )


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
