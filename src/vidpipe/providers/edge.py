"""``edge-tts`` narration provider (Microsoft Edge neural voices over the network).

Default narration for English and Amharic. Voices are configurable per language::

    providers:
      narration:
        name: edge-tts
        options:
          voices: {am: am-ET-MekdesNeural}   # merged over DEFAULT_VOICES
          rate: "+0%"                        # optional edge-tts prosody rate
        fallback: [mms-tts]                  # declared only; the offline fallback is not built

``TTSResult.duration_s`` is read from the written MP3 itself (see ``_audio``), not from service
boundary events. Needs network, so the real-service conformance run carries the ``integration``
marker.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException

from vidpipe.contracts import (
    TTSCapabilities,
    TTSProvider,
    TTSRequest,
    TTSResult,
    UnsupportedRequest,
)
from vidpipe.providers._audio import audio_duration_s
from vidpipe.registry import register

DEFAULT_VOICES: dict[str, str] = {
    "en": "en-US-AriaNeural",
    "am": "am-ET-AmehaNeural",  # alternative: am-ET-MekdesNeural
}
ATTEMPTS = 3
_TRANSIENT = (EdgeTTSException, aiohttp.ClientError, TimeoutError)


@register
class EdgeTTS(TTSProvider):
    name = "edge-tts"

    def __init__(
        self, *, voices: dict[str, str] | None = None, rate: str = "+0%", **options: Any
    ) -> None:
        super().__init__(**options)
        self.voices = {**DEFAULT_VOICES, **(voices or {})}
        self.rate = rate
        self.capabilities = TTSCapabilities(languages=frozenset(self.voices))

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if request.language not in self.capabilities.languages:
            raise UnsupportedRequest(f"language {request.language!r}")
        voice = request.voice or self.voices[request.language]
        path = request.output_path.with_suffix(".mp3")
        path.parent.mkdir(parents=True, exist_ok=True)
        extras = {k: v for k, v in request.extras.items() if k in ("rate", "pitch", "volume")}
        extras.setdefault("rate", self.rate)
        last: Exception | None = None
        for _ in range(ATTEMPTS):
            try:
                asyncio.run(edge_tts.Communicate(request.text, voice, **extras).save(str(path)))
                return TTSResult(path=path, duration_s=audio_duration_s(path))
            except _TRANSIENT as exc:
                last = exc
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
        raise RuntimeError(f"edge-tts failed after {ATTEMPTS} attempts: {last}") from last
