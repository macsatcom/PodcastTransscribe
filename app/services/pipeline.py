import logging

from app.adapters import RSSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.services.transcribe import transcribe_audio
from app.services.summarize import generate_summary
from app.services.embedder import chunk_text, embed_chunks

logger = logging.getLogger(__name__)


async def process_episode(episode_id):
    async with async_session() as session:
        episode = await session.get(Episode, episode_id)
        if not episode or episode.status == "ready":
            return

        episode.status = "downloading"
        await session.commit()

        try:
            adapter = RSSSourceAdapter()
            audio_data = (await adapter.fetch_audio(episode.audio_url)).read()

            episode.status = "transcribing"
            await session.commit()

            full_text, segments = await transcribe_audio(session, audio_data)

            da_chars = sum(1 for c in full_text if c in "æøåÆØÅ")
            language = "danish" if da_chars > max(5, len(full_text) * 0.02) else "english"

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

            summary = await generate_summary(session, full_text, language)
            transcript.summary = summary
            await session.commit()

            episode.status = "indexing"
            await session.commit()

            chunks = chunk_text(full_text)
            embeddings = await embed_chunks(session, chunks)

            for i, (chunk_text_val, embedding) in enumerate(zip(chunks, embeddings)):
                chunk = TranscriptChunk(
                    transcript_id=transcript.id,
                    chunk_index=i,
                    text=chunk_text_val,
                    embedding=embedding,
                )
                session.add(chunk)

            episode.status = "ready"
            await session.commit()

        except Exception as e:
            await session.rollback()
            episode.status = "error"
            episode.error_message = str(e)
            try:
                await session.commit()
            except Exception:
                pass
            logger.error("Failed to process episode %s: %s", episode_id, e)
