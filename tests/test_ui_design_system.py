"""The studio console design system: tokens, contrast, motion rules and bundled fonts.

These check the shipped static assets themselves (what the browser receives), not markup
details: every colour pair the UI draws text or status with meets WCAG 2.2 AA in both themes,
animation only runs when the user has not asked for reduced motion, and the fonts and their
licences travel inside the built wheel so the UI works offline.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "vidpipe" / "ui" / "static"
TOKENS = STATIC / "tokens.css"
CONSOLE = STATIC / "console.css"
FONTS = STATIC / "fonts"

THEMES = ("dark", "light")
BACKGROUNDS = ("bg", "surface", "raised", "inset", "selected")
STATUSES = ("waiting", "running", "done", "reused", "paused", "failed")
PHASES = ("words", "voice", "picture", "sound")
# Everything drawn as text (labels, numerals, status words, phase names) on any background.
TEXT = (
    "text",
    "text-muted",
    "text-faint",
    "accent",
    *(f"status-{s}" for s in STATUSES),
    *(f"phase-{p}" for p in PHASES),
)
# Text drawn on a filled colour rather than on a background.
FILLED = (("on-accent", "accent"), ("on-failed", "status-failed"))
# Component boundaries and focus indicators (WCAG 1.4.11 non-text contrast).
BOUNDARIES = ("line-strong", "focus")

RAW = re.compile(r"--color-([a-z-]+?)-(dark|light)\s*:\s*(#[0-9a-fA-F]{6})\s*;")
SEMANTIC = re.compile(r"--color-([a-z-]+)\s*:\s*light-dark\(([^;]*)\)\s*;")


def palette() -> dict[str, dict[str, str]]:
    themes: dict[str, dict[str, str]] = {t: {} for t in THEMES}
    for name, theme, value in RAW.findall(TOKENS.read_text(encoding="utf-8")):
        themes[theme][name] = value.lower()
    return themes


def luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_every_colour_token_exists_in_both_themes_and_follows_the_scheme() -> None:
    themes = palette()
    needed = {*BACKGROUNDS, *TEXT, *BOUNDARIES, *(fg for fg, _ in FILLED), "line"}
    for theme in THEMES:
        assert needed <= themes[theme].keys(), f"{theme} is missing {needed - themes[theme].keys()}"
    assert themes["dark"].keys() == themes["light"].keys()

    semantic = dict(SEMANTIC.findall(TOKENS.read_text(encoding="utf-8")))
    for name in themes["dark"]:
        assert name in semantic, f"--color-{name} has no light-dark() semantic token"
        assert semantic[name].replace(" ", "") == (
            f"var(--color-{name}-light),var(--color-{name}-dark)"
        )


@pytest.mark.parametrize("theme", THEMES)
def test_text_and_status_colours_meet_wcag_aa(theme: str) -> None:
    colours = palette()[theme]
    failures = [
        f"{fg} on {bg}: {contrast(colours[fg], colours[bg]):.2f}"
        for fg in TEXT
        for bg in BACKGROUNDS
        if contrast(colours[fg], colours[bg]) < 4.5
    ]
    failures += [
        f"{fg} on {bg}: {contrast(colours[fg], colours[bg]):.2f}"
        for fg, bg in FILLED
        if contrast(colours[fg], colours[bg]) < 4.5
    ]
    assert not failures, failures


@pytest.mark.parametrize("theme", THEMES)
def test_boundaries_and_focus_meet_non_text_contrast(theme: str) -> None:
    colours = palette()[theme]
    failures = [
        f"{fg} on {bg}: {contrast(colours[fg], colours[bg]):.2f}"
        for fg in BOUNDARIES
        for bg in BACKGROUNDS
        if contrast(colours[fg], colours[bg]) < 3.0
    ]
    assert not failures, failures


def animated_rules(css: str) -> list[tuple[list[str], str]]:
    """Every declaration that starts an animation, with the chain of blocks around it."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: list[tuple[list[str], str]] = []
    stack: list[str] = []
    buffer = ""
    for char in css:
        if char == "{":
            stack.append(buffer.strip())
            buffer = ""
        elif char in ";}":
            declaration = buffer.strip()
            if re.match(r"animation(-name)?\s*:", declaration) and "none" not in declaration:
                found.append((list(stack), declaration))
            buffer = ""
            if char == "}" and stack:
                stack.pop()
        else:
            buffer += char
    return found


def test_animation_only_runs_without_a_reduced_motion_preference() -> None:
    rules = animated_rules(CONSOLE.read_text(encoding="utf-8"))
    assert rules, "console.css should animate something (ring, pulse, status changes)"
    for blocks, declaration in rules:
        assert any("prefers-reduced-motion: no-preference" in b for b in blocks), (
            f"{declaration!r} in {blocks} runs under reduced motion"
        )


def font_faces() -> list[str]:
    return re.findall(r"url\(\"?([^\")]+)\"?\)", TOKENS.read_text(encoding="utf-8"))


def test_fonts_are_local_woff2_with_their_licences() -> None:
    urls = font_faces()
    assert urls, "tokens.css declares no @font-face sources"
    for url in urls:
        assert not re.match(r"[a-z]+://|//", url), f"{url} is not served from the package"
        path = STATIC / url
        assert path.suffix == ".woff2"
        assert path.read_bytes()[:4] == b"wOF2", f"{url} is not a woff2 file"
    licences = sorted(FONTS.glob("*.txt"))
    assert len(licences) >= 2
    for licence in licences:
        assert "SIL OPEN FONT LICENSE VERSION 1.1" in licence.read_text(encoding="utf-8").upper()
    assert (FONTS / "README.md").is_file()


def test_static_assets_never_reach_the_network() -> None:
    for path in STATIC.rglob("*"):
        if path.suffix in {".css", ".js", ".html"}:
            text = path.read_text(encoding="utf-8")
            assert not re.search(r"(src|href)=\"(https?:)?//", text), path
            assert not re.search(r"url\(\"?(https?:)?//", text), path
            assert "@import" not in text, path


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is needed to build the wheel")
def test_built_wheel_ships_the_fonts_licences_and_style_page(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("vidpipe-*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    shipped = "vidpipe/ui/static/"
    for path in STATIC.rglob("*"):
        if path.is_file():
            assert shipped + path.relative_to(STATIC).as_posix() in names
    assert any(n.startswith(shipped + "fonts/") and n.endswith(".woff2") for n in names)
    assert sum(n.startswith(shipped + "fonts/") and n.endswith(".txt") for n in names) >= 2
