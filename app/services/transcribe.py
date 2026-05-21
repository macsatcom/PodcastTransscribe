import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL_KEY = "transcription_model"
DEFAULT_TRANSCRIPTION_MODEL = "openai/gpt-audio-mini"


async def transcribe_audio(session, audio_data: bytes) -> tuple[str, dict | None]:
    setting = await session.get(Setting, TRANSCRIPTION_MODEL_KEY)
    model = setting.value if setting else DEFAULT_TRANSCRIPTION_MODEL
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        result = await client.transcribe_with_timestamps(model, audio_data)
        full_text = result.get("text", "")
        segments = result.get("segments", None)
        return full_text, segments
