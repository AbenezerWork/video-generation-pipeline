# ruff: noqa: E501  (HTML and CSS templates read better unwrapped)
"""Build the vidpipe walkthrough video from code.

Reads the narration (``narration.md``) and the demo evidence written by ``capture.py``, then:

1. speaks each beat with Edge TTS, keeping word timings;
2. renders every slide, terminal frame and caption as HTML to 1920x1080 PNG with Playwright;
3. times each beat's frames to cue words in its narration and burns in the captions;
4. joins the beats with ffmpeg, normalises loudness to -16 LUFS and writes a frame sheet.

    uv run --with playwright python tools/walkthrough/build.py --capture <capture> --out <dir>

See README.md in this folder.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
W, H, FPS = 1920, 1080, 30
VOICE = "en-US-AndrewNeural"
RATE = "+10%"
LEAD, TAIL = 0.2, 0.35  # silence before and after each beat's narration, seconds
TITLE = "vidpipe"
AUTHOR = "Abenezer Workineh"
DATE = "26 November 2026"
DEMOS = Path.home() / ".t3" / "vidpipe-demos"
FILM_16x9 = DEMOS / "lions-whisker-16x9" / "out" / "lions-whisker-16x9_am.mp4"
FILM_9x16 = DEMOS / "lions-whisker-9x16" / "out" / "lions-whisker-9x16_am.mp4"
SOURCE = DEMOS / "lions-whisker-16x9"


# --------------------------------------------------------------------------------------------- tools


def tool(name: str) -> str:
    folder = os.environ.get("VIDPIPE_FFMPEG_DIR")
    if folder and (Path(folder) / f"{name}.exe").exists():
        return str(Path(folder) / f"{name}.exe")
    if folder and (Path(folder) / name).exists():
        return str(Path(folder) / name)
    found = shutil.which(name)
    if not found:
        sys.exit(f"{name} not found: set VIDPIPE_FFMPEG_DIR or put it on PATH")
    return found


def ffmpeg(*args: str) -> None:
    command = [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", *args]
    done = subprocess.run(command, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"ffmpeg failed: {' '.join(command)}\n{done.stderr}")


def duration(path: Path) -> float:
    out = subprocess.run(
        [tool("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(path)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return float(out.stdout.strip())


def digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ----------------------------------------------------------------------------------------- narration


def read_beats(path: Path) -> list[tuple[str, str]]:
    beats: list[tuple[str, str]] = []
    current: str | None = None
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^## (\S+)\s*$", line)
        if heading:
            if current:
                beats.append((current, " ".join(lines).strip()))
            current, lines = heading.group(1), []
        elif current is not None and line.strip():
            lines.append(line.strip())
    if current:
        beats.append((current, " ".join(lines).strip()))
    return beats


@dataclass
class Speech:
    path: Path | None
    seconds: float
    words: list[dict]  # {"text", "start", "end"}, seconds from the start of the speech


async def _speak(text: str, mp3: Path) -> list[dict]:
    import edge_tts

    words = []
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    with mp3.open("wb") as sink:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                sink.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"text": chunk["text"], "start": start,
                              "end": start + chunk["duration"] / 1e7})  # fmt: skip
    return words


def speak(text: str, work: Path) -> Speech:
    if not text:
        return Speech(None, 0.0, [])
    key = digest(text, VOICE, RATE)
    mp3, meta = work / "tts" / f"{key}.mp3", work / "tts" / f"{key}.json"
    mp3.parent.mkdir(parents=True, exist_ok=True)
    if not meta.exists():
        for attempt in range(3):
            try:
                words = asyncio.run(_speak(text, mp3))
                break
            except Exception as exc:  # network hiccups: try again
                if attempt == 2:
                    raise
                print("  edge-tts retry:", exc)
        meta.write_text(json.dumps(words), encoding="utf-8")
    return Speech(mp3, duration(mp3), json.loads(meta.read_text(encoding="utf-8")))


def norm(word: str) -> str:
    return re.sub(r"[^0-9a-z]", "", word.lower())


def token_times(tokens: list[str], speech: Speech) -> list[float]:
    """The time each written token is spoken, matched in order against the TTS word boundaries."""
    words = [norm(w["text"]) for w in speech.words]
    times: list[float | None] = []
    j = 0
    for token in tokens:
        t = norm(token)
        found = None
        for k in range(j, min(j + 5, len(words))):
            w = words[k]
            if t and w and (t == w or t.startswith(w) or w.startswith(t)):
                found = k
                break
        if found is None:
            times.append(None)
        else:
            times.append(speech.words[found]["start"])
            j = found + 1
    # Fill gaps by interpolating between matched neighbours.
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known:
        return [speech.seconds * i / max(1, len(tokens)) for i in range(len(tokens))]
    filled = []
    for i, t in enumerate(times):
        if t is not None:
            filled.append(t)
            continue
        before = [(a, b) for a, b in known if a < i]
        after = [(a, b) for a, b in known if a > i]
        if before and after:
            (a0, t0), (a1, t1) = before[-1], after[0]
            filled.append(t0 + (t1 - t0) * (i - a0) / (a1 - a0))
        elif before:
            filled.append(before[-1][1])
        else:
            filled.append(after[0][1])
    return filled


def cue_time(cue: str, speech: Speech, after: float = 0.0) -> float:
    """When the phrase ``cue`` starts in the speech (first occurrence at or after ``after``)."""
    target = [norm(w) for w in cue.split() if norm(w)]
    words = [norm(w["text"]) for w in speech.words]
    for i in range(len(words) - len(target) + 1):
        if speech.words[i]["start"] + 1e-6 < after:
            continue
        if all(words[i + k] and (words[i + k].startswith(t) or t.startswith(words[i + k]))
               for k, t in enumerate(target)):  # fmt: skip
            return speech.words[i]["start"]
    raise SystemExit(f"cue {cue!r} not found in the narration")


WEAK = {"a", "an", "the", "and", "or", "of", "in", "to", "for", "with", "by", "at", "on", "its"}


def caption_chunks(text: str, limit: int = 62) -> list[list[str]]:
    """Split text into caption lines: sentence ends first, then clause marks, then word wrap."""
    tokens = text.split()
    chunks: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        current.append(token)
        length = len(" ".join(current))
        if (token.endswith((".", "?", "!")) and length > 18) or (
            token.endswith((",", ":", ";")) and length > 38
        ):
            chunks.append(current)
            current = []
        elif length > limit:
            current.pop()
            carry = [token]
            # Don't end a line on a short function word: move it down with the next word.
            while len(current) > 3 and current[-1].lower() in WEAK:
                carry.insert(0, current.pop())
            chunks.append(current)
            current = carry
    if current:
        if chunks and len(" ".join(current)) < 14 and len(" ".join(chunks[-1] + current)) < 76:
            chunks[-1] += current
        else:
            chunks.append(current)
    return chunks


def captions(text: str, speech: Speech) -> list[tuple[str, float, float]]:
    tokens = text.split()
    times = token_times(tokens, speech)
    cues = []
    i = 0
    chunks = caption_chunks(text)
    for chunk in chunks:
        start = times[i]
        i += len(chunk)
        end = times[i] - 0.05 if i < len(tokens) else speech.seconds
        cues.append((" ".join(chunk), start, max(end, start + 0.4)))
    return cues


# ------------------------------------------------------------------------------------------ rendering

FONT_DIR = REPO / "src" / "vidpipe" / "ui" / "static" / "fonts"
ETHIOPIC = REPO / "assets" / "fonts"

CSS = f"""
@font-face {{ font-family: "Mona Sans"; src: url("{(FONT_DIR / "MonaSansVF.woff2").as_uri()}");
  font-weight: 200 900; font-stretch: 75% 125%; }}
@font-face {{ font-family: "JetBrains Mono";
  src: url("{(FONT_DIR / "JetBrainsMono-Regular.woff2").as_uri()}"); font-weight: 400; }}
@font-face {{ font-family: "JetBrains Mono";
  src: url("{(FONT_DIR / "JetBrainsMono-SemiBold.woff2").as_uri()}"); font-weight: 600; }}
@font-face {{ font-family: "Noto Sans Ethiopic";
  src: url("{(ETHIOPIC / "NotoSansEthiopic-Regular.ttf").as_uri()}"); font-weight: 400; }}
@font-face {{ font-family: "Noto Sans Ethiopic";
  src: url("{(ETHIOPIC / "NotoSansEthiopic-Bold.ttf").as_uri()}"); font-weight: 700; }}
:root {{
  --bg: #0b0c0f; --surface: #121419; --raised: #1a1d24; --inset: #07080a; --line: #262a33;
  --line-strong: #6f7686; --text: #eceef2; --muted: #aab0bc; --faint: #8d94a2; --accent: #9db8ff;
  --done: #5fdc93; --reused: #9fb0c4; --failed: #ff7a72; --paused: #f4c64e;
  --words: #ffa477; --voice: #ff7fb8; --picture: #5fd6ea; --sound: #b79cff;
  --sans: "Mona Sans", "Noto Sans Ethiopic", "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", "Noto Sans Ethiopic", Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; background: var(--bg);
  color: var(--text); font-family: var(--sans); }}
html.transparent, html.transparent body {{ background: transparent; }}
.slide {{ position: absolute; inset: 0; padding: 64px 96px 150px; display: flex;
  flex-direction: column; gap: 26px; }}
.kicker {{ font: 600 22px/1 var(--mono); letter-spacing: .16em; text-transform: uppercase;
  color: var(--accent); display: flex; gap: 18px; align-items: center; }}
.kicker .num {{ color: var(--bg); background: var(--accent); padding: 6px 10px; border-radius: 6px; }}
h1 {{ font-size: 64px; font-weight: 800; font-stretch: 112%; margin: 0; letter-spacing: -.02em;
  line-height: 1.05; }}
h2 {{ font-size: 34px; font-weight: 600; margin: 0; color: var(--muted); line-height: 1.25; }}
.panel {{ background: var(--surface); border: 1px solid var(--line); border-radius: 18px;
  padding: 26px 30px; }}
.label {{ font: 600 18px/1 var(--mono); letter-spacing: .12em; text-transform: uppercase;
  color: var(--faint); margin-bottom: 16px; }}
.dim {{ opacity: .25; }}
.hl {{ outline: 3px solid var(--accent); outline-offset: 4px; }}
code, pre {{ font-family: var(--mono); }}
pre {{ margin: 0; font-size: 21px; line-height: 1.5; white-space: pre; }}
.k {{ color: #ff9fd0; }} .s {{ color: #a8e6a1; }} .n {{ color: #ffc98a; }} .c {{ color: var(--faint); }}
.f {{ color: var(--picture); }} .key {{ color: var(--accent); }}
.term {{ background: var(--inset); border: 1px solid var(--line); border-radius: 16px; flex: 1;
  display: flex; flex-direction: column; overflow: hidden; }}
.term .bar {{ display: flex; gap: 10px; align-items: center; padding: 14px 20px;
  background: var(--raised); border-bottom: 1px solid var(--line); font: 18px var(--mono);
  color: var(--faint); }}
.term .bar i {{ width: 14px; height: 14px; border-radius: 50%; background: var(--line-strong);
  display: inline-block; }}
.term .body {{ padding: 22px 28px; font: 23px/1.48 var(--mono); white-space: pre; }}
.term .prompt {{ color: var(--done); }} .term .cmd {{ color: var(--text); font-weight: 600; }}
.term .warn {{ color: var(--faint); }}
.term .ran {{ color: var(--done); font-weight: 600; }}
.term .ranbox {{ background: rgba(95,220,147,.16); }}
.term .skipbox {{ background: rgba(159,176,196,.13); }}
.term .del {{ color: var(--failed); }} .term .add {{ color: var(--done); }}
.term .hunk {{ color: var(--picture); }}
.badge {{ display: inline-flex; gap: 12px; align-items: center; font: 600 24px var(--mono);
  padding: 12px 20px; border-radius: 12px; background: var(--raised);
  border: 1px solid var(--line); }}
.badge.ok {{ color: var(--done); border-color: rgba(95,220,147,.5); }}
.row {{ display: flex; gap: 26px; }}
.caption {{ position: absolute; left: 50%; bottom: 44px; transform: translateX(-50%);
  max-width: 1640px; padding: 14px 30px 16px; border-radius: 14px; background: rgba(7,8,10,.86);
  border: 1px solid rgba(255,255,255,.08); font: 600 38px/1.3 var(--sans); text-align: center;
  color: #fff; white-space: nowrap; }}
.am {{ font-family: "Noto Sans Ethiopic", var(--sans); }}
"""


def page(body: str, *, transparent: bool = False) -> str:
    cls = ' class="transparent"' if transparent else ""
    return f"<!doctype html><html{cls}><meta charset=utf-8><style>{CSS}</style><body>{body}</body></html>"


class Renderer:
    """Renders HTML pages to 1920x1080 PNGs, cached by content."""

    def __init__(self, work: Path) -> None:
        from playwright.sync_api import sync_playwright

        self.dir = work / "frames"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._page = self._browser.new_page(viewport={"width": W, "height": H})

    def png(self, markup: str, *, transparent: bool = False) -> Path:
        doc = page(markup, transparent=transparent)
        out = self.dir / f"{digest(doc)}.png"
        if not out.exists():
            src = out.with_suffix(".html")
            src.write_text(doc, encoding="utf-8")
            self._page.goto(src.as_uri())
            self._page.evaluate("document.fonts.ready")
            self._page.wait_for_timeout(60)
            self._page.screenshot(path=out, omit_background=transparent)
        return out

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()


def esc(text: str) -> str:
    return html.escape(text, quote=False)


PY_TOKENS = re.compile(
    r'(?P<c>#.*$)|(?P<s>f?"[^"]*")|(?P<k>@\w+|(?:class|def|return|lambda|import|from|for|in))'
)
DATA_TOKENS = re.compile(
    r'(?P<c>#.*$)|(?P<key>^\s*-?\s*[\w.-]+(?=:)|"[^"]*"(?=:))|(?P<s>"[^"]*")'
    r"|(?P<n>(?<![\w.-])-?\d[\d.]*(?![\w-]))"
)
CLASSES = {"c": "c", "s": "s", "k": "k", "key": "key", "n": "n"}


def highlight(code: str, tokens: re.Pattern[str]) -> str:
    """Colour code in one pass, so no replacement ever sees another's markup."""
    out = []
    for line in code.splitlines():
        parts, pos = [], 0
        for m in tokens.finditer(line):
            parts.append(esc(line[pos : m.start()]))
            kind = m.lastgroup or ""
            text = m.group(0)
            if kind == "key":  # keep a list dash or indent outside the colour
                lead = len(text) - len(text.lstrip(" -"))
                parts.append(esc(text[:lead]))
                text = text[lead:]
            parts.append(f'<span class="{CLASSES[kind]}">{esc(text)}</span>')
            pos = m.end()
        parts.append(esc(line[pos:]))
        out.append("".join(parts))
    return "\n".join(out)


def highlight_python(code: str) -> str:
    return highlight(code, PY_TOKENS)


def highlight_data(code: str) -> str:
    """JSON or YAML: keys, strings and numbers."""
    return highlight(code, DATA_TOKENS)


def rounded(value: object) -> object:
    """Floats to 3 decimals for display (ledger records carry full precision)."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rounded(v) for v in value]
    return value


def header(num: str, kicker: str, title: str = "", sub: str = "") -> str:
    parts = [f'<div class="kicker"><span class="num">{num}</span>{esc(kicker)}</div>']
    if title:
        parts.append(f"<h1>{title}</h1>")
    if sub:
        parts.append(f"<h2>{sub}</h2>")
    return "".join(parts)


# ---------------------------------------------------------------------------------------- the visuals


@dataclass
class Frame:
    png: Path
    cue: str | None = None  # the frame appears when this phrase is spoken (None: at the start)


@dataclass
class Beat:
    id: str
    text: str
    speech: Speech
    frames: list[Frame] = field(default_factory=list)
    video: Callable[[float, Path], Path] | None = (
        None  # custom base video (gets duration, work dir)
    )
    lead: float = LEAD
    fixed_seconds: float | None = None  # a beat without narration lasts this long
    captions: bool = True


class Visuals:
    def __init__(self, render: Renderer, capture: Path, work: Path) -> None:
        self.r = render
        self.capture = capture
        self.work = work
        self.evidence = json.loads((capture / "evidence.json").read_text(encoding="utf-8"))
        self.project = Path(self.evidence["project"])

    # ------------------------------------------------------------------ helpers

    def text(self, name: str) -> str:
        raw = (self.capture / name).read_text(encoding="utf-8")
        return "\n".join(line for line in raw.splitlines() if "VIRTUAL_ENV" not in line)

    def still(self, path: Path, t: float, out: Path, width: int | None = None) -> Path:
        if not out.exists():
            scale = ["-vf", f"scale={width}:-2"] if width else []
            ffmpeg("-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", *scale, str(out))
        return out

    def shot_start(self, fit_plan: Path, shot: int, lang: str = "am") -> float:
        plan = json.loads(fit_plan.read_text(encoding="utf-8"))
        return sum(s["languages"][lang]["seconds"] for s in plan["shots"] if s["shot_id"] < shot)

    def terminal(self, title: str, lines: list[tuple[str, str]], head: str = "",
                 foot: str = "") -> Path:  # fmt: skip
        body = "\n".join(f'<span class="{cls}">{esc(text) if text else " "}</span>'
                         for cls, text in lines)  # fmt: skip
        markup = (
            f'<div class="slide" style="gap:20px">{head}'
            f'<div class="term"><div class="bar"><i></i><i></i><i></i>&nbsp;{esc(title)}</div>'
            f'<div class="body">{body}</div></div>{foot}</div>'
        )
        return self.r.png(markup)

    def run_lines(self, output: str) -> list[tuple[str, str]]:
        lines = []
        for line in output.splitlines():
            if line.startswith(("warning:", "  en:", "  am:", "  back:", "review:")):
                lines.append(("warn", line))
            else:
                lines.append(("", line))
        return lines

    # ------------------------------------------------------------------ beats

    def title(self) -> list[Frame]:
        bg = (SOURCE / "build" / "keyframes" / "shot_13.png").as_uri()
        markup = f"""
<div style="position:absolute;inset:0;background:url('{bg}') right center/cover;filter:saturate(.9)"></div>
<div style="position:absolute;inset:0;background:linear-gradient(90deg,var(--bg) 34%,rgba(11,12,15,.82) 58%,rgba(11,12,15,.35))"></div>
<div class="slide" style="justify-content:center;gap:30px">
  <div class="kicker">Walkthrough · Heritage Short challenge</div>
  <div style="font-size:190px;font-weight:850;font-stretch:118%;letter-spacing:-.04em;line-height:.9">{TITLE}</div>
  <h2 style="max-width:980px;font-size:42px;color:var(--text)">A studio pipeline that turns a written brief into a narrated, scored, subtitled short film.</h2>
  <div class="row" style="gap:14px;margin-top:10px">
    <span class="badge">architecture</span><span class="badge">one hard decision</span>
    <span class="badge ok">one shot regenerated live</span></div>
  <div style="font:26px var(--mono);color:var(--muted);margin-top:24px">{esc(AUTHOR)} · {DATE}</div>
</div>
<div style="position:absolute;top:44px;right:56px;font:600 22px var(--mono);color:var(--paused);
  border:2px solid var(--paused);border-radius:10px;padding:10px 16px;background:rgba(11,12,15,.7)">
  Narration: AI voice</div>"""
        return [Frame(self.r.png(markup))]

    def film(self, seconds: float, work: Path) -> Path:
        """The finished film, 16:9 and 9:16 side by side, with its own sound under the narration."""
        markup = """
<div class="slide" style="padding-top:34px">
  <div class="kicker" style="justify-content:space-between;width:100%">
    <span>The Lion's Whisker · ያንበሳው ጢም · made by vidpipe</span>
    <span style="color:var(--faint)">16:9 · 1280×720 &nbsp;&nbsp;&nbsp; 9:16 · 720×1280</span></div>
</div>"""
        bg = self.r.png(markup)
        out = work / f"film-{seconds:.2f}.mp4"
        start = 41.6  # shots 10-13: the lion in the ravine
        vol = "if(lt(t,2.4),1,if(lt(t,3.1),1-(t-2.4)/0.7*0.84,0.16))"
        ffmpeg(
            "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(bg),
            "-ss", f"{start}", "-t", f"{seconds:.3f}", "-i", str(FILM_16x9),
            "-ss", f"{start}", "-t", f"{seconds:.3f}", "-i", str(FILM_9x16),
            "-filter_complex",
            "[1:v]scale=1352:760,setsar=1[a];[2:v]scale=428:760,setsar=1[b];"
            "[0:v][a]overlay=50:96[t];[t][b]overlay=1442:96,fps=30,format=yuv420p[v];"
            f"[1:a]volume='{vol}':eval=frame,afade=t=out:st={seconds - 1.0:.3f}:d=1.0,"
            "aresample=48000,aformat=channel_layouts=stereo[a1]",
            "-map", "[v]", "-map", "[a1]", "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            str(out),
        )  # fmt: skip
        return out

    def arch_stages(self) -> list[Frame]:
        phases = [
            ("words", "Write the words", ["Brief", "Script", "Translation", "Storyboard"],
             "text CLI · Claude"),
            ("voice", "Give it a voice", ["Narration", "Fit planning"], "Edge TTS · fit planner"),
            ("picture", "Make the pictures", ["Keyframes", "Moving shots"],
             "FLUX.2 · Wan 2.2 (ComfyUI)"),
            ("sound", "Score and finish", ["Music", "Assembly"], "ACE-Step · FFmpeg"),
        ]  # fmt: skip

        def diagram(focus: str | None) -> Path:
            cols = []
            n = 0
            for key, name, stages, who in phases:
                chips = []
                for stage in stages:
                    n += 1
                    chips.append(
                        f'<div style="display:flex;gap:14px;align-items:center;padding:14px 16px;'
                        f'background:var(--raised);border-radius:12px;border-left:5px solid var(--{key})">'
                        f'<span style="font:600 20px var(--mono);color:var(--faint)">{n:02d}</span>'
                        f'<span style="font-size:27px;font-weight:600">{stage}</span></div>'
                    )
                dim = " dim" if focus and focus not in (key, "all") else ""
                ring = f";outline:3px solid var(--{key});outline-offset:6px" if focus == key else ""
                cols.append(
                    f'<div class="panel{dim}" style="flex:1;display:flex;flex-direction:column;gap:12px{ring}">'
                    f'<div style="font:600 19px var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--{key})">{name}</div>'
                    f'{"".join(chips)}<div style="margin-top:auto;font:19px var(--mono);color:var(--faint)">{who}</div></div>'
                )
            proj_dim = " dim" if focus and focus not in ("project", "all") else ""
            proj_ring = (
                ";outline:3px solid var(--accent);outline-offset:6px" if focus == "project" else ""
            )
            project = (
                f'<div class="panel{proj_dim}" style="width:250px{proj_ring}"><div class="label">project/</div>'
                '<pre style="font-size:22px;line-height:1.75">brief.md\nvidpipe.yaml\nbible.yaml\nbible/*.png</pre></div>'
            )
            outbox = (
                f'<div class="panel{proj_dim if focus == "project" else (" dim" if focus and focus != "sound" and focus != "all" else "")}" style="width:250px">'
                '<div class="label">out/</div><pre style="font-size:22px;line-height:1.75">'
                "film_am.mp4\nfilm_am.srt\nfilm_en.mp4\nfilm_en.srt</pre></div>"
            )
            arrow = '<div style="align-self:center;font-size:40px;color:var(--line-strong)">→</div>'
            under_dim = " dim" if focus and focus != "all" else ""
            markup = f"""
<div class="slide">{header("01", "Architecture", "Ten stages, four phases")}
<div class="row" style="align-items:stretch;gap:18px">{project}{arrow}{"".join(cols)}{arrow}{outbox}</div>
<div class="row{under_dim}" style="gap:18px">
  <div class="panel" style="flex:2;padding:18px 26px;font-size:25px"><b style="color:var(--accent)">build/ledger.json</b>
   &nbsp;every artifact: input hash · provider · seed · GPU s · outputs → reuse what didn't change</div>
  <div class="panel" style="flex:1;padding:18px 26px;font-size:25px"><b style="color:var(--paused)">runner</b>
   &nbsp;gates · run state · one-run lock</div></div>
</div>"""
            return self.r.png(markup)

        return [
            Frame(diagram("project")),
            Frame(diagram("all"), "vidpipe walks"),
            Frame(diagram("words"), "Write the words"),
            Frame(diagram("voice"), "Give them a voice"),
            Frame(diagram("picture"), "Make the pictures"),
            Frame(diagram("sound"), "Then music"),
        ]

    def arch_contracts(self) -> list[Frame]:
        src = (REPO / "src" / "vidpipe" / "contracts.py").read_text(encoding="utf-8")
        snippet = []
        for name in ("TTSProvider", "KeyframerProvider", "ImageToVideoProvider", "MusicProvider"):
            m = re.search(rf"class {name}\(.*?\n(?=\n\n)", src, re.S)
            if not m:
                sys.exit(f"{name} not found in contracts.py")
            snippet.append(m.group(0).rstrip())
        contracts = "\n\n".join(snippet)
        yaml = (self.project / "vidpipe.yaml").read_text(encoding="utf-8")
        providers = yaml[yaml.index("providers:") : yaml.index("end_card")].rstrip()
        build = (
            "build/\n  brief.json\n  script.json\n  translation/am.json\n  storyboard.json\n"
            "  narration.json\n  fit_plan.json\n  keyframes.json\n  video.json\n  music.json\n"
            "  ledger.json"
        )

        def slide(focus: str, badge: bool = False) -> Path:
            def p(name: str) -> str:
                return "" if focus == name else " dim"

            tests = (
                '<div class="badge ok" style="align-self:flex-start">tests/conformance: one shared '
                "suite every provider must pass</div>"
                if badge
                else ""
            )
            markup = f"""
<div class="slide">{header("01", "Architecture", "Typed contracts, swappable providers")}
<div class="row" style="flex:1;min-height:0">
  <div class="panel{p("build")}" style="width:330px"><div class="label">stage → stage</div>
    <pre style="font-size:22px;line-height:1.62">{esc(build)}</pre>
    <div style="margin-top:16px;font-size:21px;color:var(--muted)">JSON, validated with Pydantic</div></div>
  <div class="panel{p("contracts")}" style="flex:1.2;overflow:hidden"><div class="label">src/vidpipe/contracts.py</div>
    <pre style="font-size:16.5px;line-height:1.5">{highlight_python(contracts)}</pre></div>
  <div class="panel{p("yaml")}" style="flex:1;overflow:hidden"><div class="label">vidpipe.yaml</div>
    <pre style="font-size:16.5px;line-height:1.5">{highlight_data(providers)}</pre></div>
</div>{tests}</div>"""
            return self.r.png(markup)

        return [
            Frame(slide("build")),
            Frame(slide("contracts"), "Every model"),
            Frame(slide("yaml"), "Here"),
            Frame(slide("yaml", badge=True), "Swapping"),
        ]

    def arch_ledger(self) -> list[Frame]:
        stages = (REPO / "src" / "vidpipe" / "stages.py").read_text(encoding="utf-8")
        m = re.search(r"( *)made = ctx\.produce\(\n\s*key,\n\s*inputs=Inputs\(values=\{\"text\": text\}\),.*?\n\1\)",
                      stages, re.S)  # fmt: skip
        if not m:
            sys.exit("narration produce() call not found in stages.py")
        indent = len(m.group(1))
        produce = "\n".join(line[indent:] for line in m.group(0).splitlines())
        produce = (
            '# src/vidpipe/stages.py, narration stage\nkey = f"narration/{lang}/shot_{shot.id:02d}"\n'
            + produce
        )
        record = dict(self.evidence["changed"]["narration/am/shot_15"]["after"])
        for k in ("stage", "provider_options", "fallback"):
            record.pop(k, None)
        rec = json.dumps(rounded(record), ensure_ascii=False, indent=2)
        rec = re.sub(r'"([0-9a-f]{12})[0-9a-f]{40,}"', r'"\1…"', rec)

        def slide(step: int) -> Path:
            chips = ""
            if step >= 1:
                chips = (
                    '<div class="row" style="gap:16px">'
                    '<span class="badge">same hash → <b style="color:var(--reused)">reuse</b></span>'
                    '<span class="badge">new hash → <b style="color:var(--done)">regenerate</b> + record</span>'
                )
                if step >= 2:
                    chips += ('<span class="badge ok">caching</span><span class="badge ok">crash resume</span>'
                              '<span class="badge ok">single-shot re-roll</span>')  # fmt: skip
                chips += "</div>"
            markup = f"""
<div class="slide">{header("01", "Architecture", "The ledger: everything hashed by content")}
<div class="row" style="flex:1;min-height:0">
  <div class="panel" style="flex:1"><div class="label">declare inputs where the artifact is made</div>
    <pre style="font-size:23px;line-height:1.5">{highlight_python(produce)}</pre></div>
  <div class="panel" style="flex:1;overflow:hidden"><div class="label">build/ledger.json · one record</div>
    <pre style="font-size:19px;line-height:1.36">{highlight_data(rec)}</pre></div>
</div>{chips}</div>"""
            return self.r.png(markup)

        return [
            Frame(slide(0)),
            Frame(slide(1), "Same hash"),
            Frame(slide(2), "That one mechanism"),
        ]

    def decision_problem(self) -> list[Frame]:
        def slide(step: int) -> Path:
            order = """
<div class="row" style="gap:16px;align-items:center;font-size:30px;font-weight:600">
  <span class="badge" style="border-color:var(--voice);color:var(--voice)">narration</span>→
  <span class="badge" style="border-color:var(--voice);color:var(--voice)">real length, measured</span>→
  <span class="badge" style="border-color:var(--voice);color:var(--voice)">fit plan</span>→
  <span class="badge" style="border-color:var(--picture);color:var(--picture)">how much video to make</span></div>"""
            cost = ""
            if step >= 1:
                cost = """
<div class="row" style="gap:22px">
  <div class="panel" style="flex:1"><div class="label">Wan 2.2 TI2V 5B</div><div style="font-size:54px;font-weight:800">2 – 5 s</div><div style="font-size:24px;color:var(--muted)">per generated clip</div></div>
  <div class="panel" style="flex:1"><div class="label">GPU cost (RTX 4060 Laptop, 8 GB)</div><div style="font-size:54px;font-weight:800">≈ 40 GPU-s</div><div style="font-size:24px;color:var(--muted)">per second of video, at 640×352</div></div>
  <div class="panel" style="flex:1"><div class="label">The Lion's Whisker</div><div style="font-size:54px;font-weight:800">48 GPU-min</div><div style="font-size:24px;color:var(--muted)">for 72 s of video, one language set</div></div></div>"""
            bars = ""
            if step >= 2:
                bars = """
<div class="panel" style="display:grid;grid-template-columns:330px 1fr;gap:16px 22px;align-items:center;font-size:26px">
  <span>narration, line 1</span><div style="height:40px;width:1132px;background:var(--voice);border-radius:8px;display:flex;align-items:center;padding-left:16px;color:var(--bg);font:600 24px var(--mono)">5.66 s</div>
  <span>longest Wan clip</span><div style="display:flex"><div style="height:40px;width:1000px;background:var(--picture);border-radius:8px 0 0 8px;display:flex;align-items:center;padding-left:16px;color:var(--bg);font:600 24px var(--mono)">5.00 s</div><div style="height:40px;width:132px;border:3px dashed var(--failed);border-left:none;border-radius:0 8px 8px 0;color:var(--failed);font:600 22px var(--mono);display:flex;align-items:center;justify-content:center">?</div></div></div>"""
            markup = f"""
<div class="slide">{header("02", "A hard decision", "Fitting the pictures to the voice")}
{order}{cost}{bars}</div>"""
            return self.r.png(markup)

        return [Frame(slide(0)), Frame(slide(1), "But Wan"), Frame(slide(2), "In the sample")]

    def decision_options(self) -> list[Frame]:
        options = [
            ("Freeze the last frame", "looks broken", False),
            ("Time-stretch the voice", "sounds wrong", False),
            ("Video per language", "2× the GPU bill", False),
            ("Bend the video", "speed ×0.77 – ×1.3, then a continuation clip", True),
        ]

        def slide(shown: int, chosen: bool, continuation: bool) -> Path:
            cards = []
            for i, (name, why, good) in enumerate(options):
                if i >= shown:
                    cards.append('<div class="panel" style="flex:1;opacity:0"></div>')
                    continue
                mark, color = ("✓", "var(--done)") if good else ("✗", "var(--failed)")
                ring = (
                    ";outline:3px solid var(--done);outline-offset:5px" if good and chosen else ""
                )
                cards.append(
                    f'<div class="panel" style="flex:1{ring}"><div style="font-size:56px;color:{color};font-weight:800">{mark}</div>'
                    f'<div style="font-size:34px;font-weight:700;margin:8px 0 10px">{name}</div>'
                    f'<div style="font-size:26px;color:var(--muted)">{why}</div></div>'
                )
            how = ""
            if chosen:
                how = """
<div class="panel" style="display:flex;flex-direction:column;gap:18px">
 <div class="label">fit planner · src/vidpipe/fit.py</div>
 <div class="row" style="align-items:center;gap:18px;font-size:26px">
   <span class="badge" style="color:var(--picture)">5.00 s clip</span> played at <b style="font:600 30px var(--mono)">0.88×</b> →
   <span class="badge" style="color:var(--voice)">lasts 5.66 s = the line</span>
   <span style="color:var(--faint)">narration is never time-stretched</span></div>"""
                if continuation:
                    how += """
 <div class="row" style="align-items:center;gap:18px;font-size:26px">
   <span style="color:var(--muted)">still too long?</span>
   <span class="badge" style="font-family:var(--sans);font-weight:600;white-space:nowrap">split at a sentence end, then a clause mark (incl. Amharic <span class="am">።&#8201;፣&#8201;፤</span>), then a pause</span>→
   <span class="badge" style="color:var(--picture)">clip 2 starts from clip 1's last frame</span></div>"""
                how += "</div>"
            markup = f"""
<div class="slide">{header("02", "A hard decision", "Four options")}
<div class="row" style="align-items:stretch">{"".join(cards)}</div>{how}</div>"""
            return self.r.png(markup)

        return [
            Frame(slide(1, False, False)),
            Frame(slide(2, False, False), "I could stretch"),
            Frame(slide(3, False, False), "Or render"),
            Frame(slide(4, True, False), "Instead"),
            Frame(slide(4, True, True), "Only when"),
        ]

    def decision_plan(self) -> list[Frame]:
        plan = self.text("plan.txt").splitlines()
        table = plan[: plan.index("") if "" in plan else 11]
        fit_at = next(i for i, ln in enumerate(plan) if ln.startswith("fit plan"))

        def block(shot: int) -> list[str]:
            start = plan.index(f"shot {shot}")
            return plan[start : start + 6]

        renders = next(ln for ln in plan if ln.startswith("renders:"))

        def lines(am: bool) -> list[tuple[str, str]]:
            out = [("prompt", "$ vidpipe plan ."), ("", "")]
            out += [("warn", table[-1]), ("", ""), ("", plan[fit_at])]
            for shot in (1, 15):
                for ln in block(shot):
                    cls = (
                        "ran"
                        if am and ln.strip().startswith("0.00") and re.search(r"[ሀ-፿]", ln)
                        else ""
                    )
                    out.append((cls, ln))
            out.append(("", "…"))
            out.append(("ran" if am else "", renders))
            return out

        head = header(
            "02", "A hard decision", "", "vidpipe plan: the whole fit, before any GPU time"
        )
        return [
            Frame(self.terminal("vidpipe plan · lions-whisker-16x9", lines(False), head)),
            Frame(
                self.terminal("vidpipe plan · lions-whisker-16x9", lines(True), head),
                "In The Lion's",
            ),
        ]

    def demo_baseline(self) -> list[Frame]:
        out = self.text("run_baseline.txt")
        lines = [("prompt", "$ cd lions-whisker-16x9   # a scratch copy of the finished project"),
                 ("prompt", "$ vidpipe run . --auto"), ("", "")] + self.run_lines(out)  # fmt: skip
        head = header("03", "Live: change one line", "", "An unchanged re-run")
        foot = (f'<div class="badge ok" style="align-self:flex-start">nothing changed → 10 of 10 '
                f'stages skipped · {self.evidence["baseline_seconds"]:.0f} s</div>')  # fmt: skip
        return [Frame(self.terminal("bash · lions-whisker-16x9", lines, head, foot))]

    def demo_edit(self) -> list[Frame]:
        diff = self.text("diff.txt").splitlines()
        lines = [("prompt", "$ # edit one narration line: shot 15, the elder's advice"),
                 ("prompt", "$ diff -u am.json.orig build/translation/am.json"), ("", "")]  # fmt: skip
        for ln in diff:
            cls = ("hunk" if ln.startswith("@@") else "del" if ln.startswith("-") and not ln.startswith("---")
                   else "add" if ln.startswith("+") and not ln.startswith("+++") else "warn" if ln.startswith(("---", "+++")) else "")  # fmt: skip
            lines.append((cls, ln))
        old, new = self.evidence["old_line"], self.evidence["new_line"]
        foot = f"""
<div class="row" style="gap:22px">
 <div class="panel" style="flex:1"><div class="label" style="color:var(--failed)">before</div>
  <div class="am" style="font-size:36px">{esc(old)}</div>
  <div style="font-size:24px;color:var(--muted);margin-top:8px">"Be as patient with the boy as you were with the lion."</div></div>
 <div class="panel" style="flex:1"><div class="label" style="color:var(--done)">after</div>
  <div class="am" style="font-size:36px">{esc(new)}</div>
  <div style="font-size:24px;color:var(--muted);margin-top:8px">"As you were patient with the lion, be patient with the boy too."</div></div></div>"""
        head = header(
            "03", "Live: change one line", "", "The whole edit: one line of Amharic narration"
        )
        return [Frame(self.terminal("bash · lions-whisker-16x9", lines, head, foot))]

    def demo_run(self) -> list[Frame]:
        out = self.text("run_edit.txt")
        base = [("prompt", "$ vidpipe run . --auto"), ("", "")] + self.run_lines(out)
        head = header("03", "Live: change one line", "", "The same command again")
        e = self.evidence
        steps = [
            (None, set(), False, False),
            ("Translation re-runs", {"translation"}, False, False),
            ("Narration generates", {"translation", "narration"}, False, False),
            ("The fit plan", {"translation", "narration", "fit-planning"}, False, False),
            (
                "assembly renders",
                {"translation", "narration", "fit-planning", "assembly"},
                False,
                False,
            ),
            (
                "Keyframes, video",
                {"translation", "narration", "fit-planning", "assembly"},
                True,
                False,
            ),
            (
                "Under a minute",
                {"translation", "narration", "fit-planning", "assembly"},
                True,
                True,
            ),
        ]
        frames = []
        for cue, lit, skipped, badge in steps:
            lines = []
            for cls, text in base:
                stage = text.split(" ")[0] if text else ""
                if stage in lit and "ran (" in text:
                    cls = "ran ranbox"
                elif skipped and stage in {"keyframes", "video", "music"}:
                    cls = "skipbox"
                lines.append((cls, text))
            foot = ""
            if badge:
                foot = (f'<div class="row" style="gap:16px"><span class="badge ok">exit 0 · {e["run_seconds"]:.0f} s</span>'
                        f'<span class="badge ok">GPU time: {e["gpu_seconds"]:.0f} s</span>'
                        '<span class="badge">keyframes · video · music: skipped</span></div>')  # fmt: skip
            frames.append(Frame(self.terminal("bash · lions-whisker-16x9", lines, head, foot), cue))
        return frames

    def demo_ledger(self) -> list[Frame]:
        e = self.evidence
        before_all = json.loads(json.dumps(e["hashes_before"]))
        after_all = e["hashes_after"]
        changed = set(e["records_changed"])
        keys = list(
            json.loads((self.project / "build" / "ledger.json").read_text(encoding="utf-8"))[
                "artifacts"
            ]
        )

        chips = "".join(
            f'<span style="font:17px var(--mono);padding:6px 9px;border-radius:7px;'
            f'{"background:rgba(95,220,147,.2);color:var(--done);font-weight:600;outline:2px solid var(--done)" if k in changed else "background:var(--raised);color:var(--faint)"}">{esc(k)}</span>'
            for k in keys
        )
        grid = f"""
<div class="slide">{header("03", "Live: change one line", f"{len(changed)} of {len(keys)} ledger records changed")}
<div class="panel" style="display:flex;flex-wrap:wrap;gap:9px;align-content:flex-start">{chips}</div></div>"""

        def trim(rec: dict) -> dict:
            keep = (
                "input_hash",
                "inputs",
                "provider",
                "parameters",
                "wall_seconds",
                "started_at",
                "outputs",
                "data",
            )
            r = {k: rec[k] for k in keep if k in rec}
            r["wall_seconds"] = round(r["wall_seconds"], 2)
            return r

        b = trim(e["changed"]["narration/am/shot_15"]["before"])
        a = trim(e["changed"]["narration/am/shot_15"]["after"])

        def show(rec: dict, other: dict) -> str:
            text = json.dumps(rounded(rec), ensure_ascii=False, indent=2)
            text = re.sub(r'"([0-9a-f]{10})[0-9a-f]{40,}"', r'"\1…"', text)
            other_text = re.sub(
                r'"([0-9a-f]{10})[0-9a-f]{40,}"',
                r'"\1…"',
                json.dumps(rounded(other), ensure_ascii=False, indent=2),
            )
            other_lines = set(other_text.splitlines())
            out = []
            for line in highlight_data(text).splitlines():
                plain = re.sub(r"<[^>]+>", "", line)
                plain = html.unescape(plain)
                if plain not in other_lines and plain.strip() not in (
                    "{",
                    "}",
                    "[",
                    "]",
                    "],",
                    "},",
                ):
                    out.append(
                        f'<span style="background:rgba(255,164,119,.18);display:inline-block;width:100%">{line}</span>'
                    )
                else:
                    out.append(line)
            return "\n".join(out)

        records = f"""
<div class="slide">{header("03", "Live: change one line", "", "narration/am/shot_15 in build/ledger.json")}
<div class="row" style="flex:1;min-height:0">
 <div class="panel" style="flex:1;overflow:hidden"><div class="label">before</div><pre style="font-size:19px;line-height:1.38">{show(b, a)}</pre></div>
 <div class="panel" style="flex:1;overflow:hidden"><div class="label" style="color:var(--done)">after</div><pre style="font-size:19px;line-height:1.38">{show(a, b)}</pre></div>
</div></div>"""

        def count(prefix: str, suffix: str) -> tuple[int, int]:
            files = [k for k in after_all if k.startswith(prefix) and k.endswith(suffix)]
            same = sum(1 for k in files if before_all.get(k) == after_all[k])
            return same, len(files)

        rows = [
            ("Keyframes", "build/keyframes/", ".png"),
            ("Video clips", "build/video/", ".mp4"),
            ("Score", "build/music/", ".flac"),
            ("Narration (en + am)", "build/narration/", ".mp3"),
            ("English cut", "out/lions-whisker-16x9_en", ".mp4"),
            ("Amharic cut", "out/lions-whisker-16x9_am", ".mp4"),
        ]
        trs = []
        for name, prefix, suffix in rows:
            same, total = count(prefix, suffix)
            new = total - same
            status = ('<b style="color:var(--reused)">unchanged</b>' if new == 0
                      else f'<b style="color:var(--done)">{new} regenerated</b>')  # fmt: skip
            trs.append(f'<tr><td>{name}</td><td style="font-family:var(--mono);color:var(--faint)">{prefix}*{suffix}</td>'
                       f'<td style="font-family:var(--mono)">{same} / {total} identical</td><td>{status}</td></tr>')  # fmt: skip
        table = f"""
<div class="slide">{header("03", "Live: change one line", "Byte for byte: what changed on disk")}
<div class="panel"><table style="width:100%;border-collapse:collapse;font-size:31px">
<tr style="color:var(--faint);font:600 19px var(--mono);letter-spacing:.1em;text-transform:uppercase"><td>artifact</td><td>files</td><td>sha-256 before = after</td><td></td></tr>
{"".join(trs)}</table></div>
<style>td{{padding:14px 10px;border-top:1px solid var(--line)}}</style>
<div class="badge ok" style="align-self:flex-start">GPU time for the whole re-run: {e["gpu_seconds"]:.0f} s</div></div>"""
        return [Frame(self.r.png(grid)), Frame(self.r.png(records), "Here's"),
                Frame(self.r.png(table), "All sixteen")]  # fmt: skip

    def demo_result(self) -> list[Frame]:
        e = self.evidence
        stills = self.work / "stills"
        stills.mkdir(exist_ok=True)
        old_start = self.shot_start(SOURCE / "build" / "fit_plan.json", 15)
        new_start = self.shot_start(self.project / "build" / "fit_plan.json", 15)
        old_png = self.still(FILM_16x9, old_start + 1.7, stills / "shot15-before.png")
        new_png = self.still(self.project / "out" / "lions-whisker-16x9_am.mp4", new_start + 1.7,
                             stills / "shot15-after.png")  # fmt: skip

        def card(png: Path, label: str, color: str, line: str) -> str:
            return (f'<div style="flex:1;display:flex;flex-direction:column;gap:14px">'
                    f'<div class="label" style="color:{color};margin:0">{label}</div>'
                    f'<img src="{png.as_uri()}" style="width:100%;border-radius:14px;border:1px solid var(--line)">'
                    f'<div class="am" style="font-size:30px">{esc(line)}</div></div>')  # fmt: skip

        markup = f"""
<div class="slide">{header("03", "Live: change one line", "Shot 15, before and after")}
<div class="row" style="gap:30px">{card(old_png, "before · original render", "var(--failed)", e["old_line"])}
{card(new_png, "after · regenerated render", "var(--done)", e["new_line"])}</div></div>"""
        return [Frame(self.r.png(markup))]

    def demo_clip_seconds(self) -> tuple[float, float]:
        start = self.shot_start(self.project / "build" / "fit_plan.json", 15)
        end = self.shot_start(self.project / "build" / "fit_plan.json", 16)
        return start - 0.4, (end - start) + 1.2

    def demo_clip(self, seconds: float, work: Path) -> Path:
        start, _ = self.demo_clip_seconds()
        markup = """
<div class="slide" style="padding-top:34px">
  <div class="kicker" style="justify-content:space-between;width:100%">
    <span><span class="num">03</span>&nbsp; the regenerated Amharic cut, shot 15</span>
    <span style="color:var(--faint)">out/lions-whisker-16x9_am.mp4</span></div></div>"""
        bg = self.r.png(markup)
        out = work / f"clip-{seconds:.2f}.mp4"
        film = self.project / "out" / "lions-whisker-16x9_am.mp4"
        ffmpeg(
            "-loop", "1", "-t", f"{seconds:.3f}", "-i", str(bg),
            "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(film),
            "-filter_complex",
            "[1:v]scale=1600:900,setsar=1[a];[0:v][a]overlay=160:110,fps=30,format=yuv420p[v];"
            f"[1:a]afade=t=in:d=0.25,afade=t=out:st={seconds - 0.4:.3f}:d=0.4,"
            "aresample=48000,aformat=channel_layouts=stereo[a1]",
            "-map", "[v]", "-map", "[a1]", "-t", f"{seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            str(out),
        )  # fmt: skip
        return out

    def ui(self) -> list[Frame]:
        def shot(png: str, title: str) -> Path:
            markup = f"""
<div class="slide" style="gap:18px;padding-top:40px">{header("04", "The console: vidpipe ui", "")}
<div style="font-size:30px;color:var(--muted);margin-top:-8px">{title}</div>
<img src="{(self.capture / png).as_uri()}" style="width:1424px;border-radius:14px;border:1px solid var(--line-strong);align-self:center;box-shadow:0 20px 60px rgba(0,0,0,.5)"></div>"""
            return self.r.png(markup)

        return [
            Frame(shot("ui_run.png", "Run view after the re-run: 4 stages done, 6 reused")),
            Frame(
                shot(
                    "ui_keyframes.png",
                    "Each stage shows its outputs: keyframes, with redo per shot",
                ),
                "Each stage",
            ),
            Frame(
                shot(
                    "ui_config.png",
                    "Config view: provider readiness, YAML preview, next-run estimate",
                ),
                "And the config",
            ),
        ]

    def close(self) -> list[Frame]:
        e = self.evidence
        markup = f"""
<div class="slide" style="justify-content:center;gap:34px">
  <div class="kicker">Summary</div>
  <div style="font-size:150px;font-weight:850;font-stretch:118%;letter-spacing:-.04em;line-height:.9">{TITLE}</div>
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:10px">
    <div class="panel"><div class="label" style="color:var(--words)">architecture</div><div style="font-size:30px">10 stages · typed JSON contracts · providers chosen in YAML</div></div>
    <div class="panel"><div class="label" style="color:var(--voice)">hard decision</div><div style="font-size:30px">fit planner: speed ×0.77–×1.3, then continuation clips</div></div>
    <div class="panel"><div class="label" style="color:var(--done)">live demo</div><div style="font-size:30px">one line edited → {len(e["records_changed"])} of {e["records_total"]} records redone, 0 GPU-s</div></div>
  </div>
  <div style="font:28px var(--mono);color:var(--muted)">github.com/AbenezerWork/video-generation-pipeline · experiments.md · docs/adr/</div>
  <div style="font:22px var(--mono);color:var(--paused)">Made with AI: narration is a synthetic voice (Edge TTS, {VOICE}); film footage, music and voices by FLUX.2, Wan 2.2, ACE-Step and Edge TTS.</div>
</div>"""
        return [Frame(self.r.png(markup))]


# ------------------------------------------------------------------------------------------ assembly


def caption_png(render: Renderer, text: str) -> Path:
    return render.png(f'<div class="caption">{esc(text)}</div>', transparent=True)


def build_beat(
    beat: Beat, render: Renderer, work: Path, index: int
) -> tuple[Path, list[tuple[str, float, float]]]:
    speech = beat.speech
    seconds = (
        beat.fixed_seconds if beat.fixed_seconds is not None else beat.lead + speech.seconds + TAIL
    )
    out = work / "beats" / f"{index:02d}-{beat.id}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    # The picture: a custom video, or the beat's frames timed to their cue words.
    has_audio = False
    if beat.video is not None:
        base = beat.video(seconds, work / "beats")
        has_audio = True
    else:
        times, after = [], 0.0
        for frame in beat.frames:
            t = (
                0.0
                if frame.cue is None
                else beat.lead + cue_time(frame.cue, speech, after - beat.lead)
            )
            times.append(t)
            after = t
        lst = work / "beats" / f"{index:02d}-{beat.id}.txt"
        rows = []
        for i, frame in enumerate(beat.frames):
            end = times[i + 1] if i + 1 < len(times) else seconds
            rows.append(
                f"file '{frame.png.as_posix()}'\nduration {max(end - times[i], 1 / FPS):.4f}"
            )
        rows.append(f"file '{beat.frames[-1].png.as_posix()}'")
        lst.write_text("\n".join(rows) + "\n", encoding="utf-8")
        base = work / "beats" / f"{index:02d}-{beat.id}-base.mp4"
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-t", f"{seconds:.3f}",
               "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "medium",
               "-crf", "16", str(base))  # fmt: skip

    cues = [(t, beat.lead + s, beat.lead + e) for t, s, e in captions(beat.text, speech)] if (
        beat.text and beat.captions) else []  # fmt: skip

    inputs = ["-i", str(base)]
    filters = []
    v = "[0:v]"
    for n, (text, start, end) in enumerate(cues):
        inputs += ["-i", str(caption_png(render, text))]
        filters.append(f"{v}[{n + 1}:v]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[v{n}]")
        v = f"[v{n}]"
    filters.append(f"{v}fps={FPS},format=yuv420p[vout]")
    audio_inputs = []
    if speech.path:
        inputs += ["-i", str(speech.path)]
        k = len(cues) + 1
        delay = int(beat.lead * 1000)
        filters.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,"
                       f"adelay={delay}|{delay},apad[nar]")  # fmt: skip
        audio_inputs.append("[nar]")
    if has_audio:
        filters.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,apad[bed]")
        audio_inputs.append("[bed]")
    if not audio_inputs:
        filters.append("anullsrc=r=48000:cl=stereo[sil]")
        audio_inputs.append("[sil]")
    if len(audio_inputs) == 1:
        filters.append(f"{audio_inputs[0]}anull[aout]")
    else:
        filters.append(
            f"{''.join(audio_inputs)}amix=inputs={len(audio_inputs)}:normalize=0:duration=longest[aout]"
        )
    ffmpeg(*inputs, "-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]",
           "-t", f"{seconds:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
           "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-ac", "2", str(out))  # fmt: skip
    return out, cues


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--capture", type=Path, required=True, help="folder written by capture.py")
    parser.add_argument("--out", type=Path, required=True, help="output folder")
    parser.add_argument("--work", type=Path, help="scratch folder (default: <out>/work)")
    args = parser.parse_args()
    out: Path = args.out
    work: Path = args.work or out / "work"
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    beats_text = read_beats(HERE / "narration.md")
    # Speak everything first: Playwright's sync API keeps an event loop running in this thread.
    speeches = {beat_id: speak(text, work) for beat_id, text in beats_text}
    print(f"narration: {sum(s.seconds for s in speeches.values()):.1f} s of speech")
    render = Renderer(work)
    try:
        vis = Visuals(render, args.capture, work)
        clip_seconds = vis.demo_clip_seconds()[1]
        specs: dict[str, dict] = {
            "title": {"frames": vis.title},
            "film": {"video": vis.film, "lead": 3.0},
            "arch-stages": {"frames": vis.arch_stages},
            "arch-contracts": {"frames": vis.arch_contracts},
            "arch-ledger": {"frames": vis.arch_ledger},
            "decision-problem": {"frames": vis.decision_problem},
            "decision-options": {"frames": vis.decision_options},
            "decision-plan": {"frames": vis.decision_plan},
            "demo-baseline": {"frames": vis.demo_baseline},
            "demo-edit": {"frames": vis.demo_edit},
            "demo-run": {"frames": vis.demo_run},
            "demo-ledger": {"frames": vis.demo_ledger},
            "demo-result": {"frames": vis.demo_result},
            "demo-clip": {"video": vis.demo_clip, "fixed": clip_seconds, "captions": False},
            "ui": {"frames": vis.ui},
            "close": {"frames": vis.close},
        }
        missing = [b for b, _ in beats_text if b not in specs]
        if missing:
            sys.exit(f"no visual for beats: {missing}")
        parts, srt, clock = [], [], 0.0
        for index, (beat_id, text) in enumerate(beats_text):
            spec = specs[beat_id]
            print(f"[{index + 1:02d}/{len(beats_text)}] {beat_id}")
            speech = speeches[beat_id]
            beat = Beat(
                beat_id, text, speech,
                frames=spec["frames"]() if "frames" in spec else [],
                video=spec.get("video"), lead=spec.get("lead", LEAD),
                fixed_seconds=spec.get("fixed"), captions=spec.get("captions", True),
            )  # fmt: skip
            path, cues = build_beat(beat, render, work, index)
            parts.append(path)
            srt += [(t, clock + s, clock + e) for t, s, e in cues]
            clock += duration(path)
    finally:
        render.close()

    joined = work / "joined.mp4"
    lst = work / "parts.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined))

    # Loudness: two-pass EBU R128 to -16 LUFS, true peak -1.5 dBTP.
    probe = subprocess.run(
        [tool("ffmpeg"), "-hide_banner", "-i", str(joined), "-af",
         "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )  # fmt: skip
    stats = json.loads(probe.stderr[probe.stderr.rindex("{") : probe.stderr.rindex("}") + 1])
    final = out / "walkthrough.mp4"
    ffmpeg("-i", str(joined), "-c:v", "copy", "-af",
           f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
           f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
           f"offset={stats['target_offset']}:linear=true,aresample=48000",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(final))  # fmt: skip

    (out / "walkthrough.srt").write_text(
        "\n".join(
            f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n" for i, (t, s, e) in enumerate(srt, 1)
        ),
        encoding="utf-8",
    )
    total = duration(final)
    sheet = out / "walkthrough_frames.jpg"
    step = total / 30
    ffmpeg("-i", str(final), "-vf", f"fps=1/{step:.3f},scale=384:216,tile=6x5:padding=6:color=0x0b0c0f",
           "-frames:v", "1", "-q:v", "3", str(sheet))  # fmt: skip
    print(f"wrote {final} ({total:.1f} s), {sheet}")
    if total > 300:
        sys.exit("the walkthrough is over five minutes")


if __name__ == "__main__":
    main()
