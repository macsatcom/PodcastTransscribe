import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.adapters.abs import ABSSourceAdapter
from app.database import get_db
from app.models.setting import Setting
from app.services import reembed

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


class AuthUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    username: str | None = None
    password: str | None = None


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(Setting.__table__.select().where(Setting.key.in_(VALID_KEYS)))
    rows = result.fetchall()
    return {row.key: row.value for row in rows}


@router.put("")
async def update_settings(
    body: dict[str, str],
    db: AsyncSession = Depends(get_db),
):
    embedding_model_changed_to: str | None = None
    for key, value in body.items():
        if key in VALID_KEYS:
            existing = await db.get(Setting, key)
            old_value = existing.value if existing else None
            if existing:
                existing.value = value
            else:
                db.add(Setting(key=key, value=value))
            if key == "embedding_model" and value and value != old_value:
                embedding_model_changed_to = value
    await db.commit()

    response: dict = {"status": "saved"}
    if embedding_model_changed_to:
        result = await reembed.trigger_reembed(embedding_model_changed_to)
        response["reembed"] = result
    return response


@router.get("/auth")
async def get_auth_settings(db: AsyncSession = Depends(get_db)):
    enabled_row = await db.get(Setting, auth.AUTH_MAIN_ENABLED)
    user_row = await db.get(Setting, auth.AUTH_MAIN_USERNAME)
    return {
        "enabled": bool(enabled_row and enabled_row.value == "1"),
        "username": (user_row.value if user_row else "") or "",
    }


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.put("/auth")
async def update_auth_settings(body: AuthUpdate, db: AsyncSession = Depends(get_db)):
    enabled_row = await db.get(Setting, auth.AUTH_MAIN_ENABLED)

    if body.username is not None:
        await _set_setting(db, auth.AUTH_MAIN_USERNAME, body.username.strip())

    if body.password is not None:
        if body.password.strip():
            await _set_setting(
                db,
                auth.AUTH_MAIN_PASSWORD_HASH,
                auth.hash_password(body.password),
            )

    user_row = await db.get(Setting, auth.AUTH_MAIN_USERNAME)
    hash_row = await db.get(Setting, auth.AUTH_MAIN_PASSWORD_HASH)
    has_username = bool(user_row and user_row.value and user_row.value.strip())
    has_password = bool(hash_row and hash_row.value)

    resulting_enabled = (
        body.enabled
        if body.enabled is not None
        else bool(enabled_row and enabled_row.value == "1")
    )

    if resulting_enabled and not (has_username and has_password):
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Set a username and password before enabling login.",
        )

    if body.enabled is not None:
        await _set_setting(db, auth.AUTH_MAIN_ENABLED, "1" if body.enabled else "0")

    await db.commit()
    auth.invalidate_main_auth_cache()
    return {"status": "saved"}


@router.get("/reembed/status")
async def reembed_status():
    return await reembed.get_status()


@router.get("/reembed/estimate")
async def reembed_estimate(target_model: str):
    return await reembed.estimate(target_model)


@router.post("/reembed/cancel")
async def reembed_cancel():
    return await reembed.cancel_reembed()


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
