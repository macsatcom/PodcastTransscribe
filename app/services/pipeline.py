import asyncio
import logging
import time

from sqlalchemy import select, delete

from app.adapters import RSSSourceAdapter
from app.adapters.abs import ABSSourceAdapter
from app.config import settings
from app.database import async_session
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.models.setting import Setting
from app.services.transcribe import transcribe_audio
from app.services.summarize import generate_summary
from app.services.embedder import chunk_text, embed_chunks

logger = logging.getLogger(__name__)
_semaphore = asyncio.Semaphore(settings.max_concurrent_processing)

STAGE_TIMEOUTS = {
    "download": 900,
    "transcribe": 1800,
    "summarize": 300,
    "indexing": 600,
}


async def _run_with_timeout(coro, stage: str):
    timeout = STAGE_TIMEOUTS.get(stage, 300)
    return await asyncio.wait_for(coro, timeout=timeout)


async def process_episode(episode_id):
    t0 = time.monotonic()

    async with _semaphore:
        async with async_session() as session:
            episode = await session.get(Episode, episode_id)
            if not episode:
                return
            if episode.status == "ready":
                return

            try:
                episode.status = "downloading"
                episode.error_message = None
                await session.commit()

                if getattr(episode, "abs_item_id", None):
                    abs_url = (await session.get(Setting, "abs_url"))
                    abs_key = (await session.get(Setting, "abs_api_key"))
                    adapter = ABSSourceAdapter(
                        abs_url=abs_url.value if abs_url else "",
                        api_key=abs_key.value if abs_key else "",
                    )
                else:
                    adapter = RSSSourceAdapter()
                audio_data = (await _run_with_timeout(adapter.fetch_audio(episode.audio_url), "download")).read()
                t1 = time.monotonic()
                logger.info("EPISODE %s: download took %.0fs", episode_id, t1 - t0)

                episode.status = "transcribing"
                await session.commit()

                full_text, segments, model_used, transcribe_cost = await _run_with_timeout(
                    transcribe_audio(session, audio_data), "transcribe"
                )
                t2 = time.monotonic()
                logger.info("EPISODE %s: transcribe took %.0fs", episode_id, t2 - t1)

                da_chars = sum(1 for c in full_text if c in "\u00e6\u00f8\u00e5\u00c6\u00d8\u00c5")
                language = "danish" if da_chars > max(3, len(full_text) * 0.005) else "english"

                result = await session.execute(
                    select(Transcript).where(Transcript.episode_id == episode.id)
                )
                existing = result.scalar_one_or_none()
                if existing:
                    await session.execute(
                        delete(TranscriptChunk).where(TranscriptChunk.transcript_id == existing.id)
                    )
                    await session.delete(existing)
                    await session.flush()

                transcript = Transcript(
                    episode_id=episode.id,
                    full_text=full_text,
                    detected_language=language,
                    timestamps_json=segments,
                )
                session.add(transcript)
                await session.commit()

                episode.status = "summarizing"
                await session.commit()

                summary, summarize_cost = await _run_with_timeout(
                    generate_summary(session, full_text, language), "summarize"
                )
                transcript = await session.get(Transcript, transcript.id)
                if transcript:
                    transcript.summary = summary
                    await session.commit()
                t3 = time.monotonic()
                logger.info("EPISODE %s: summarize took %.0fs", episode_id, t3 - t2)

                episode.status = "indexing"
                await session.commit()

                chunks = chunk_text(full_text)
                embeddings = await _run_with_timeout(
                    embed_chunks(session, chunks), "indexing"
                )

                for i, (chunk_text_val, embedding) in enumerate(zip(chunks, embeddings)):
                    chunk = TranscriptChunk(
                        transcript_id=transcript.id,
                        chunk_index=i,
                        text=chunk_text_val,
                        embedding=embedding,
                    )
                    session.add(chunk)

                total = time.monotonic() - t0
                episode.model_used = model_used
                episode.processing_seconds = int(total)
                episode.cost = round(transcribe_cost + summarize_cost, 6)
                episode.status = "ready"
                await session.commit()
                logger.info("EPISODE %s: total %.0fs \u2014 ready", episode_id, total)

            except asyncio.TimeoutError:
                logger.error("EPISODE %s: timed out after %.0fs (status was %s)", episode_id, time.monotonic() - t0, episode.status)
                try:
                    await session.rollback()
                    await session.refresh(episode)
                    episode.status = "error"
                    episode.error_message = f"Timed out after {int(time.monotonic() - t0)}s in state: {episode.status}"
                    await session.commit()
                except Exception:
                    pass

            except Exception as e:
                logger.error("EPISODE %s: failed after %.0fs: %s", episode_id, time.monotonic() - t0, e)
                try:
                    await session.rollback()
                    refreshed = await session.get(Episode, episode_id)
                    if refreshed:
                        refreshed.status = "error"
                        refreshed.error_message = str(e)[:500]
                        await session.commit()
                except Exception:
                    pass


async def reset_episode_safe(episode_id):
    async with async_session() as session:
        episode = await session.get(Episode, episode_id)
        if not episode:
            return False

        result = await session.execute(
            select(Transcript).where(Transcript.episode_id == episode_id)
        )
        transcript = result.scalar_one_or_none()
        if transcript:
            await session.execute(
                delete(TranscriptChunk).where(TranscriptChunk.transcript_id == transcript.id)
            )
            await session.delete(transcript)
            await session.flush()

        episode.status = "new"
        episode.error_message = None
        episode.model_used = None
        episode.processing_seconds = None
        episode.cost = None
        await session.commit()
        return True
