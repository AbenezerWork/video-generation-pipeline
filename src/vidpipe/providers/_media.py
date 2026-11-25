"""Stdlib-only writers for the tiny deterministic assets the fake providers produce.

* PNG images (solid colour), WAV audio (sine tone) and Y4M video (raw YUV 4:2:0, which ffmpeg reads
  natively), so the fakes need no ffmpeg and no third-party packages.
"""

from __future__ import annotations

import hashlib
import math
import struct
import wave
import zlib
from pathlib import Path

SAMPLE_RATE = 16000
Y4M_FPS = 8


def stable_int(*parts: object) -> int:
    """A deterministic integer derived from the parts (stable across processes)."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def color_from(*parts: object) -> tuple[int, int, int]:
    n = stable_int(*parts)
    return (n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF)


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    row = b"\x00" + bytes(rgb) * width  # filter type 0 + pixels
    raw = row * height
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def png_size(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path} is not a PNG")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


def write_wav(
    path: Path,
    duration_s: float,
    frequency: float,
    amplitude: float = 0.3,
    *,
    silence_s: float = 0.0,
) -> None:
    """A sine tone of ``duration_s``, then ``silence_s`` of silence."""
    frames = round(duration_s * SAMPLE_RATE)
    samples = (
        int(amplitude * 32767 * math.sin(2 * math.pi * frequency * i / SAMPLE_RATE))
        for i in range(frames)
    )
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
        out.writeframes(b"\x00\x00" * round(silence_s * SAMPLE_RATE))


def write_y4m(path: Path, width: int, height: int, frames: int, base: tuple[int, int, int]) -> None:
    """Write a raw YUV 4:2:0 clip whose brightness drifts so frames differ. Needs even sizes."""
    if width % 2 or height % 2:
        raise ValueError("Y4M fake clips need even dimensions")
    r, g, b = base
    y0 = int(0.299 * r + 0.587 * g + 0.114 * b)
    u = int(128 - 0.169 * r - 0.331 * g + 0.5 * b) & 0xFF
    v = int(128 + 0.5 * r - 0.419 * g - 0.081 * b) & 0xFF
    chroma = (width // 2) * (height // 2)
    with path.open("wb") as out:
        out.write(f"YUV4MPEG2 W{width} H{height} F{Y4M_FPS}:1 Ip A1:1 C420jpeg\n".encode())
        for i in range(frames):
            y = min(255, y0 // 2 + 40 + (i * 8) % 80)
            out.write(b"FRAME\n")
            out.write(bytes([y]) * (width * height))
            out.write(bytes([u]) * chroma)
            out.write(bytes([v]) * chroma)
