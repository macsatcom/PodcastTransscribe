import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])

VALID_KEYS = {
    "openrouter_api_key",
    "transcription_model",
    "summarization_model",
    "embedding_model",
}


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        Setting.__table__.select().where(Setting.key.in_(VALID_KEYS))
    )
    rows = result.fetchall()
    return {row.key: row.value for row in rows}


@router.put("")
async def update_settings(
    body: dict[str, str],
    db: AsyncSession = Depends(get_db),
):
    for key, value in body.items():
        if key in VALID_KEYS:
            existing = await db.get(Setting, key)
            if existing:
                existing.value = value
            else:
                db.add(Setting(key=key, value=value))
    await db.commit()
    return {"status": "saved"}


def _classify_model(mid: str, modality: str) -> list[str]:
    ml = mid.lower()
    mod = modality.lower()
    cats = []

    if "embed" in ml:
        cats.append("embedding")
        return cats

    is_chat = "/" in mid
    is_audio_model = "whisper" in ml or "deepgram" in ml or "assemblyai" in ml
    accepts_audio = "audio" in mod
    outputs_text = "->text" in mod

    if is_audio_model or (accepts_audio and outputs_text):
        cats.append("transcription")

    if is_chat:
        cats.append("chat")

    return cats


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    setting = await db.get(Setting, "openrouter_api_key")
    api_key = setting.value if setting else ""

    defaults = {
        "transcription": [
            "openai/gpt-audio-mini",
            "openai/gpt-audio",
            "openai/gpt-4o-audio-preview",
            "mistralai/voxtral-small-24b-2507",
        ],
        "chat": [
            "openai/gpt-4o-mini",
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-2.0-flash-001",
            "deepseek/deepseek-chat",
            "qwen/qwen-plus",
            "mistralai/mistral-small-3.1-24b-instruct",
        ],
        "embedding": [
            "openai/text-embedding-3-small",
            "openai/text-embedding-3-large",
        ],
    }

    if not api_key:
        return defaults

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if response.status_code != 200:
            return defaults
        data = response.json().get("data", [])

    classified = {"transcription": set(), "chat": set(), "embedding": set()}

    for m in data:
        mid = m.get("id", "")
        arch = m.get("architecture", {}) or {}
        modality = arch.get("modality", "")
        for cat in _classify_model(mid, modality):
            classified[cat].add(mid)

    return {
        "transcription": sorted(classified["transcription"] | set(defaults["transcription"])),
        "chat": sorted(classified["chat"] | set(defaults["chat"])),
        "embedding": sorted(classified["embedding"] | set(defaults["embedding"])),
    }