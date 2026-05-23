import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key
from app.services.whisper_client import transcribe_local, transcribe_self_hosted
from httpx import HTTPStatusError

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL_KEY = "transcription_model"
SELF_HOSTED_URL_KEY = "self_hosted_whisper_url"
DEFAULT_MODEL = "openai/gpt-audio-mini"


async def transcribe_audio(session, audio_data: bytes) -> tuple[str, dict | None, str, float]:
    setting = await session.get(Setting, TRANSCRIPTION_MODEL_KEY)
    model = setting.value if setting else DEFAULT_MODEL

    if model == "local-whisper":
        text, segs = await transcribe_local(audio_data)
        return text, segs, model, 0.0

    if model == "self-hosted-whisper":
        url_setting = await session.get(Setting, SELF_HOSTED_URL_KEY)
        url = url_setting.value if url_setting else "http://192.168.1.75:9000"
        text, segs = await transcribe_self_hosted(audio_data, url)
        return text, segs, model, 0.0

    api_key = await get_api_key(session)
    async with OpenRouterClient(api_key=api_key) as client:
        result = await client.transcribe_with_timestamps(model, audio_data)
        full_text = result.get("text", "")
        segments = result.get("segments", None)
        cost = result.get("cost", 0.0)
        return full_text, segments, model, cost
