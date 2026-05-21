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
    import subprocess, tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio_data)
        mp3_path = f.name

    try:
        wav_path = mp3_path + ".wav"
        subprocess.run(
            ["ffmpeg", "-y", "-i", mp3_path, "-vn", "-ar", "16000", "-ac", "1",
             "-sample_fmt", "s16", "-f", "wav", "-map_metadata", "-1",
             "-write_bext", "0", "-write_ima_adpcm", "0", wav_path],
            capture_output=True, timeout=120,
        )
        with open(wav_path, "rb") as f:
            wav_data = f.read()
    finally:
        os.unlink(mp3_path)
        if os.path.exists(wav_path):
            os.unlink(wav_path)

    files = {"file": ("audio.wav", wav_data, "audio/wav")}
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
