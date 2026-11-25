"""Pure-Python audio duration, so narration timing needs neither ffprobe nor ffmpeg.

``audio_duration_s`` reads the length straight from the file: WAV via the stdlib ``wave`` module,
MP3 by walking the frame headers (what edge-tts returns). It sums real frame lengths, so it is exact
for CBR and VBR alike and does not rely on service-reported word or sentence boundaries.
"""

from __future__ import annotations

import wave
from pathlib import Path

# MPEG audio bitrate tables (kbit/s), Layer III only; index 0 is "free", 15 is invalid.
_BITRATES_V1_L3 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
_BITRATES_V2_L3 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
_SAMPLE_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


class AudioFormatError(ValueError):
    """The file is not audio this module can measure."""


def audio_duration_s(path: Path) -> float:
    suffix = path.suffix.lower()
    if suffix == ".wav":
        return _wav_duration_s(path)
    if suffix == ".mp3":
        return _mp3_duration_s(path.read_bytes())
    raise AudioFormatError(f"cannot measure the duration of {path.name!r} ({suffix} audio)")


def _wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def _id3v2_size(data: bytes) -> int:
    if data[:3] != b"ID3" or len(data) < 10:
        return 0
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    return 10 + size


def _mp3_duration_s(data: bytes) -> float:
    pos = _id3v2_size(data)
    seconds = 0.0
    frames = 0
    while pos + 4 <= len(data):
        header = int.from_bytes(data[pos : pos + 4], "big")
        parsed = _parse_frame_header(header)
        if parsed is None:  # not on a frame boundary (junk or a tag): resync byte by byte
            pos += 1
            continue
        length, samples, sample_rate = parsed
        body = data[pos : pos + length]
        # A leading Xing/Info frame carries metadata, not audio.
        if not (frames == 0 and (b"Xing" in body[:48] or b"Info" in body[:48])):
            seconds += samples / sample_rate
        frames += 1
        pos += length
    if frames == 0:
        raise AudioFormatError("no MP3 frames found")
    return seconds


def _parse_frame_header(header: int) -> tuple[int, int, int] | None:
    """Return (frame length in bytes, samples per frame, sample rate) of an MPEG Layer III frame."""
    if header >> 21 != 0x7FF:
        return None
    version = (header >> 19) & 0b11  # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5, 1 = reserved
    layer = (header >> 17) & 0b11  # 1 = Layer III
    bitrate_index = (header >> 12) & 0b1111
    rate_index = (header >> 10) & 0b11
    padding = (header >> 9) & 1
    if version == 1 or layer != 1 or not 1 <= bitrate_index <= 14 or rate_index == 3:
        return None
    sample_rate = _SAMPLE_RATES[version][rate_index]
    if version == 3:
        bitrate, samples = _BITRATES_V1_L3[bitrate_index] * 1000, 1152
    else:
        bitrate, samples = _BITRATES_V2_L3[bitrate_index] * 1000, 576
    length = samples // 8 * bitrate // sample_rate + padding
    return length, samples, sample_rate
