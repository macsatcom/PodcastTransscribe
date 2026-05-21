import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key
from app.services.whisper_client import transcribe_local, transcribe_jetson
from httpx import HTTPStatusError

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL_KEY = "transcription_model"
CHAT_AUDIO_MODEL_KEY = "chat_audio_model"
JETSON_URL_KEY = "jetson_whisper_url"
DEFAULT_CHAT_AUDIO_MODEL = "openai/gpt-audio-mini"


async def transcribe_audio(session, audio_data: bytes) -> tuple[str, dict | None]:
    setting = await session.get(Setting, TRANSCRIPTION_MODEL_KEY)
    model = setting.value if setting else None

    if model == "local-whisper":
        return await transcribe_local(audio_data)

    if model == "jetson-whisper":
        url_setting = await session.get(Setting, JETSON_URL_KEY)
        url = url_setting.value if url_setting else "http://192.168.1.75:9000"
        return await transcribe_jetson(audio_data, url)

    api_key = await get_api_key(session)

    if model:
        async with OpenRouterClient(api_key=api_key) as client:
            result = await client.transcribe_with_timestamps(model, audio_data)
            full_text = result.get("text", "")
            segments = result.get("segments", None)
            if full_text:
                return full_text, segments

    setting = await session.get(Setting, CHAT_AUDIO_MODEL_KEY)
    fallback = setting.value if setting else DEFAULT_CHAT_AUDIO_MODEL
    async with OpenRouterClient(api_key=api_key) as client:
        result = await client.transcribe_with_timestamps(fallback, audio_data)
        full_text = result.get("text", "")
        segments = result.get("segments", None)
        return full_text, segments
