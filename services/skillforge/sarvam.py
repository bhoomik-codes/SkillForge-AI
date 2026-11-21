"""Relay short recordings to Sarvam's documented speech-to-text API."""

import httpx

from . import config

MAX_AUDIO = 4 * 1024 * 1024
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav"}


def enabled():
    return bool(config.SARVAM_API_KEY)


async def transcribe(audio, media_type):
    async with httpx.AsyncClient(timeout=25, follow_redirects=False) as http:
        response = await http.post(
            "https://api.sarvam.ai/speech-to-text",
            headers={"api-subscription-key": config.SARVAM_API_KEY},
            files={"file": (f"question.{AUDIO_TYPES[media_type]}", audio, media_type)},
            data={"model": "saaras:v4", "mode": "transcribe", "language_code": "unknown",
                  "keyterms": '["Futon","Neo4j","GitHub","pull request"]'},
        )
        response.raise_for_status()
        result = response.json()["transcript"]
    if not isinstance(result, str) or not result.strip():
        raise ValueError("Empty transcription")
    return result.strip()[:1500]
