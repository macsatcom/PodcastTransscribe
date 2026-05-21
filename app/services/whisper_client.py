import httpx
from app.config import settings


async def transcribe_local(audio_data: bytes, language: str | None = None) -> tuple[str, list | None]:
    files = {"audio_file": ("audio.mp3", audio_data, "audio/mpeg")}
    params = {"response_format": "json"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            f"{settings.local_whisper_url}/asr",
            data={"task": "transcribe", **params},
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("text", ""), result.get("segments")


async def transcribe_jetson(audio_data: bytes, jetson_url: str, language: str | None = None) -> tuple[str, list | None]:
    files = {"audio_file": ("audio.mp3", audio_data, "audio/mpeg")}
    params = {"response_format": "json"}
    if language:
        params["language"] = language

    async with httpx.AsyncClient(timeout=600) as client:
        response = await client.post(
            f"{jetson_url}/asr",
            data={"task": "transcribe", **params},
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("text", ""), result.get("segments")
