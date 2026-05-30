"""Re-embed all transcript chunks under a new embedding model.

Triggered when the `embedding_model` Setting changes. Walks every transcript
chunk whose `embedding_model` differs from the target, re-embeds the text,
and updates `embedding`, `embedding_model`, `embedding_dim` in place.

Single background task, batched commits (100 chunks). Tracks progress via
two Settings rows that the UI can poll:

- `reembed_status`: "idle" | "running" | "error"
- `reembed_progress`: f"{done}/{total}" (or "0/0" when idle)

The job is idempotent — chunks already at `target_model` are skipped, so a
restart-mid-run resumes naturally.
"""
import asyncio
import logging

from sqlalchemy import func, select, update

from app.database import async_session
from app.models.setting import Setting
from app.models.transcript import TranscriptChunk
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
STATUS_KEY = "reembed_status"
PROGRESS_KEY = "reembed_progress"
TARGET_KEY = "reembed_target_model"

_lock = asyncio.Lock()
_current_task: asyncio.Task | None = None


async def _set_setting(session, key: str, value: str) -> None:
    existing = await session.get(Setting, key)
    if existing:
        existing.value = value
    else:
        session.add(Setting(key=key, value=value))


async def _count_pending(session, target_model: str) -> int:
    result = await session.execute(
        select(func.count(TranscriptChunk.id)).where(
            TranscriptChunk.embedding_model != target_model
        )
    )
    return int(result.scalar() or 0)


async def get_status() -> dict:
    """Snapshot of the current re-embed run for the UI."""
    async with async_session() as session:
        rows = await session.execute(
            select(Setting).where(
                Setting.key.in_([STATUS_KEY, PROGRESS_KEY, TARGET_KEY])
            )
        )
        kv = {row.Setting.key: row.Setting.value for row in rows.all()}

    return {
        "status": kv.get(STATUS_KEY, "idle"),
        "progress": kv.get(PROGRESS_KEY, "0/0"),
        "target_model": kv.get(TARGET_KEY, ""),
    }


async def estimate(target_model: str) -> dict:
    """Count chunks/episodes that would be re-embedded under target_model."""
    async with async_session() as session:
        chunk_count = await _count_pending(session, target_model)
        ep_result = await session.execute(
            select(func.count(func.distinct(TranscriptChunk.transcript_id))).where(
                TranscriptChunk.embedding_model != target_model
            )
        )
        episode_count = int(ep_result.scalar() or 0)
    return {
        "chunks": chunk_count,
        "episodes": episode_count,
        "target_model": target_model,
    }


async def _reembed_loop(target_model: str) -> None:
    """The actual long-running worker — one chunk at a time, batched commits."""
    logger.info("Re-embed: starting under %s", target_model)
    total_done = 0
    try:
        async with async_session() as session:
            total = await _count_pending(session, target_model)
            await _set_setting(session, STATUS_KEY, "running")
            await _set_setting(session, PROGRESS_KEY, f"0/{total}")
            await _set_setting(session, TARGET_KEY, target_model)
            await session.commit()
            api_key = await get_api_key(session)

        if total == 0:
            async with async_session() as session:
                await _set_setting(session, STATUS_KEY, "idle")
                await _set_setting(session, PROGRESS_KEY, "0/0")
                await session.commit()
            logger.info("Re-embed: nothing to do")
            return

        async with OpenRouterClient(api_key=api_key) as client:
            while True:
                async with async_session() as session:
                    result = await session.execute(
                        select(TranscriptChunk)
                        .where(TranscriptChunk.embedding_model != target_model)
                        .limit(BATCH_SIZE)
                    )
                    batch = result.scalars().all()
                    if not batch:
                        break

                    for chunk in batch:
                        try:
                            embedding = await client.embed(target_model, chunk.text)
                        except Exception as e:
                            logger.exception(
                                "Re-embed: failed chunk %s: %s", chunk.id, e
                            )
                            raise
                        chunk.embedding = embedding
                        chunk.embedding_model = target_model
                        chunk.embedding_dim = len(embedding)

                    total_done += len(batch)
                    await _set_setting(
                        session, PROGRESS_KEY, f"{total_done}/{total}"
                    )
                    await session.commit()

        async with async_session() as session:
            await _set_setting(session, STATUS_KEY, "idle")
            await _set_setting(session, PROGRESS_KEY, f"{total_done}/{total_done}")
            await session.commit()
        logger.info("Re-embed: done — %d chunks under %s", total_done, target_model)

    except asyncio.CancelledError:
        logger.warning("Re-embed: cancelled at %d chunks", total_done)
        async with async_session() as session:
            await _set_setting(session, STATUS_KEY, "idle")
            await session.commit()
        raise
    except Exception as e:
        logger.exception("Re-embed: aborted: %s", e)
        async with async_session() as session:
            await _set_setting(session, STATUS_KEY, "error")
            await session.commit()


async def trigger_reembed(target_model: str) -> dict:
    """Start a background re-embed task. No-op if one is already running."""
    global _current_task
    async with _lock:
        if _current_task and not _current_task.done():
            return {"started": False, "reason": "already_running"}
        _current_task = asyncio.create_task(_reembed_loop(target_model))
    return {"started": True, "target_model": target_model}


async def cancel_reembed() -> dict:
    """Cancel an in-flight re-embed run."""
    global _current_task
    async with _lock:
        if _current_task and not _current_task.done():
            _current_task.cancel()
            return {"cancelled": True}
    return {"cancelled": False}
