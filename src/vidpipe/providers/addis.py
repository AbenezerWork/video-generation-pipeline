"""Addis Voices 2 for Amharic narration, with Edge TTS for English."""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from vidpipe.contracts import GenerationError, TTSRequest, TTSResult
from vidpipe.providers._audio import AudioFormatError, audio_duration_s
from vidpipe.providers.edge import EdgeTTS
from vidpipe.registry import register

_GENERATIONS = "https://api.addisassistant.com/api/v1/voice/generations"
_USER_AGENT = "vidpipe/0.1"


@register
class AddisAI(EdgeTTS):
    name = "addis-ai"

    def __init__(self, *, amharic_voice: str = "am-hamen", **options: Any) -> None:
        super().__init__(**options)
        self.amharic_voice = amharic_voice

    def fingerprint(self) -> dict[str, Any]:
        return {**super().fingerprint(), "amharic_voice": self.amharic_voice}

    def synthesize(self, request: TTSRequest) -> TTSResult:
        if request.language != "am":
            return super().synthesize(request)
        api_key = os.environ.get("ADDIS_API_KEY", "").strip()
        if not api_key:
            raise GenerationError("Addis AI narration requires ADDIS_API_KEY")

        path = request.output_path.with_suffix(".mp3")
        payload = {
            "language": "am",
            "voice_id": request.voice or self.amharic_voice,
            "text": request.text,
            "output_format": "mp3_44100",
        }
        # Reuse the generation after an interrupted download without conflating separate shots.
        identity = json.dumps([str(path.resolve()), payload], sort_keys=True)
        payload["client_request_id"] = sha256(identity.encode()).hexdigest()
        generation = Request(
            _GENERATIONS,
            data=json.dumps(payload).encode(),
            headers={
                "x-api-key": api_key,
                "Content-Type": "application/json",
                "User-Agent": _USER_AGENT,
            },
        )
        action = "generation"
        try:
            with urlopen(generation, timeout=60) as response:
                audio_url = json.load(response)["data"]["audio_url"]
            if not isinstance(audio_url, str) or urlsplit(audio_url).scheme != "https":
                raise ValueError("invalid audio URL")
            action = "audio download"
            audio = Request(audio_url, headers={"User-Agent": _USER_AGENT})
            with urlopen(audio, timeout=60) as response:
                content = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=path.parent) as directory:
                temporary = Path(directory) / path.name
                temporary.write_bytes(content)
                duration = audio_duration_s(temporary)
                if duration <= 0:
                    raise AudioFormatError("empty clip")
                temporary.replace(path)
        except HTTPError as exc:
            raise GenerationError(f"Addis AI {action} failed (HTTP {exc.code})") from None
        except (URLError, TimeoutError, KeyError, TypeError, ValueError):
            raise GenerationError(f"Addis AI {action} failed or returned invalid audio") from None
        return TTSResult(path=path, duration_s=duration)
