import logging
import re

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_endpoint_cache: dict[str, str] = {}


def _format_text(text: str | None, segments: list[dict] | None, gap_threshold: float = 1.5) -> str:
    text = text or ""
    if not segments:
        return text

    parts = []
    for i, seg in enumerate(segments):
        chunk = seg.get("text", "").strip()
        if not chunk:
            continue
        gap = segments[i + 1].get("start", 0) - seg.get("end", 0) if i + 1 < len(segments) else 0
        if gap > gap_threshold:
            parts.append(f"{chunk}\n\n")
        elif i + 1 < len(segments):
            parts.append(f"{chunk} ")
        else:
            parts.append(chunk)

    return "".join(parts).strip()


async def _discover_endpoint(whisper_url: str) -> str:
    if whisper_url in _endpoint_cache:
        return _endpoint_cache[whisper_url]

    base = whisper_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(base + "/")
            resp.raise_for_status()
            m = re.search(r'<form[^>]*\s+action="([^"]+)"', resp.text)
            endpoint = m.group(1) if m else "/inference"
    except Exception:
        endpoint = "/inference"

    _endpoint_cache[whisper_url] = endpoint
    return endpoint


async def transcribe_local(audio_data: bytes, language: str | None = None) -> tuple[str, list | None]:
    files = {"audio_file": ("audio.mp3", audio_data, "audio/mpeg")}
    params = {"task": "transcribe", "response_format": "json"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=1800) as client:
        response = await client.post(
            f"{settings.local_whisper_url}/asr",
            data=params,
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        segments = result.get("segments")
        raw = result.get("text", "")
        text = _format_text(raw, segments)
        return text, segments


async def transcribe_self_hosted(audio_data: bytes, whisper_url: str, language: str | None = None) -> tuple[str, list | None]:
    endpoint = await _discover_endpoint(whisper_url)
    files = {"file": ("audio.mp3", audio_data, "audio/mpeg")}
    data = {"response_format": "verbose_json", "temperature": "0.0", "temperature_inc": "0.2", "language": language or "auto"}

    async with httpx.AsyncClient(timeout=1800) as client:
        response = await client.post(
            f"{whisper_url.rstrip('/')}{endpoint}",
            data=data,
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        segments = result.get("segments") if isinstance(result, dict) else None
        raw = result.get("text", "") if isinstance(result, dict) else str(result)
        text = _format_text(raw, segments)
        return text, segments
