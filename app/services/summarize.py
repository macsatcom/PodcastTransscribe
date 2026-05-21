import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

SUMMARIZATION_MODEL_KEY = "summarization_model"
DEFAULT_SUMMARIZATION_MODEL = "openai/gpt-4o-mini"


async def generate_summary(session, full_text: str, language: str | None) -> str:
    setting = await session.get(Setting, SUMMARIZATION_MODEL_KEY)
    model = setting.value if setting else DEFAULT_SUMMARIZATION_MODEL
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        summary = await client.summarize(model, full_text, language or "english")
        return summary
