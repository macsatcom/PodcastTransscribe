import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting
from app.adapters.abs import ABSSourceAdapter

router = APIRouter(prefix="/api/settings", tags=["settings"])

VALID_KEYS = {
    "openrouter_api_key",
    "transcription_model",
    "summarization_model",
    "embedding_model",
    "semantic_distance_threshold",
    "self_hosted_whisper_url",
    "abs_url",
    "abs_api_key",
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


def _classify_chat_model(mid: str, modality: str) -> list[str]:
    ml = mid.lower()
    mod = modality.lower()
    cats = []

    if "embed" in ml:
        cats.append("embedding")
        return cats

    has_slash = "/" in mid
    accepts_audio = "audio" in mod and "->text" in mod
    is_transcription_only = mod == "audio->transcription"

    if is_transcription_only:
        pass
    elif accepts_audio and has_slash:
        cats.append("chat_audio")
        cats.append("chat")
    elif has_slash:
        cats.append("chat")

    return cats


@router.get("/models")
async def list_models(db: AsyncSession = Depends(get_db)):
    setting = await db.get(Setting, "openrouter_api_key")
    api_key = setting.value if setting else ""

    defaults = {
        "transcription": [
            "openai/whisper-1",
            "openai/whisper-large-v3",
            "openai/whisper-large-v3-turbo",
            "openai/gpt-4o-mini-transcribe",
            "openai/gpt-4o-transcribe",
            "google/chirp-3",
            "mistralai/voxtral-mini-transcribe",
            "qwen/qwen3-asr-flash-2026-02-10",
        ],
        "chat_audio": [
            "openai/gpt-audio-mini",
            "openai/gpt-audio",
            "openai/gpt-4o-audio-preview",
            "mistralai/voxtral-small-24b-2507",
            "google/gemini-2.0-flash-001",
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
        headers = {"Authorization": f"Bearer {api_key}"}

        resp = await client.get(
            "https://openrouter.ai/api/v1/models?output_modalities=transcription",
            headers=headers,
        )
        transcription_models = set()
        if resp.status_code == 200:
            for m in resp.json().get("data", []):
                transcription_models.add(m.get("id", ""))

        resp = await client.get(
            "https://openrouter.ai/api/v1/models",
            headers=headers,
        )
        chat_audio_set = set()
        chat_set = set()
        embedding_set = set()

        if resp.status_code == 200:
            for m in resp.json().get("data", []):
                mid = m.get("id", "")
                arch = m.get("architecture", {}) or {}
                modality = arch.get("modality", "")
                for cat in _classify_chat_model(mid, modality):
                    if cat == "chat_audio":
                        chat_audio_set.add(mid)
                    elif cat == "chat":
                        chat_set.add(mid)
                    elif cat == "embedding":
                        embedding_set.add(mid)

    return {
        "transcription": sorted(transcription_models | set(defaults["transcription"])),
        "chat_audio": sorted(chat_audio_set | set(defaults["chat_audio"])),
        "chat": sorted(chat_set | set(defaults["chat"])),
        "embedding": sorted(embedding_set | set(defaults["embedding"])),
    }


@router.get("/abs/test")
async def test_abs_connection(db: AsyncSession = Depends(get_db)):
    abs_url_setting = await db.get(Setting, "abs_url")
    abs_key_setting = await db.get(Setting, "abs_api_key")
    url = (abs_url_setting.value if abs_url_setting else "").strip()
    key = (abs_key_setting.value if abs_key_setting else "").strip()
    if not url or not key:
        return {"ok": False, "error": "ABS URL and API key are required"}
    async with ABSSourceAdapter(abs_url=url, api_key=key) as adapter:
        try:
            await adapter.get_libraries()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
