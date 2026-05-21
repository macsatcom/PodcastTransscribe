import httpx
from app.config import settings


async def transcribe_local(audio_data: bytes, language: str | None = None) -> tuple[str, list | None]:
    files = {"audio_file": ("audio.mp3", audio_data, "audio/mpeg")}
    params = {"task": "transcribe", "response_format": "json"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            f"{settings.local_whisper_url}/asr",
            data=params,
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("text", ""), result.get("segments")


async def transcribe_self_hosted(audio_data: bytes, whisper_url: str, language: str | None = None) -> tuple[str, list | None]:
    files = {"file": ("audio.mp3", audio_data, "audio/mpeg")}
    data = {"response_format": "verbose_json", "temperature": "0.0", "temperature_inc": "0.2", "language": language or "auto"}

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            f"{whisper_url}/inference",
            data=data,
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        text = result.get("text", "") if isinstance(result, dict) else str(result)
        segments = result.get("segments") if isinstance(result, dict) else None
        return text, segments
