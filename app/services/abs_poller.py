import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.adapters.abs import ABSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.services.queue_manager import episode_queue

logger = logging.getLogger(__name__)


async def poll_abs_libraries():
    async with async_session() as session:
        result = await session.execute(
            select(SourceConfig).where(
                SourceConfig.source_type == "abs",
                SourceConfig.enabled == True,
            )
        )
        configs = result.scalars().all()

    await asyncio.gather(*(poll_abs_source(c.id) for c in configs), return_exceptions=True)


async def poll_abs_source(source_config_id):
    async with async_session() as session:
        config = await session.get(SourceConfig, source_config_id)
        if not config:
            return

        podcast = await session.get(Podcast, config.podcast_id)
        if not podcast:
            logger.warning("Podcast %s not found for source config %s", config.podcast_id, config.id)
            return

        abs_item_id = config.url
        if not abs_item_id:
            return

        adapter = ABSSourceAdapter()
        try:
            episodes_meta = await adapter.discover_new(abs_item_id)
        except Exception as e:
            logger.error("ABS poll failed for item %s: %s", abs_item_id, e)
            return

        new_episodes = []
        for meta in episodes_meta:
            existing = await session.execute(
                select(Episode).where(
                    Episode.podcast_id == podcast.id,
                    Episode.guid == meta.guid,
                )
            )
            if existing.scalar_one_or_none():
                continue

            if podcast.cover_url is None and meta.cover_url:
                podcast.cover_url = meta.cover_url
            if podcast.abs_item_id is None:
                podcast.abs_item_id = abs_item_id
            if podcast.media_type is None:
                podcast.media_type = meta.media_type

            episode = Episode(
                podcast_id=podcast.id,
                guid=meta.guid,
                title=meta.title,
                description=meta.description,
                audio_url=meta.audio_url,
                duration_seconds=meta.duration_seconds,
                published_at=meta.published_at,
                status="new",
                abs_item_id=meta.abs_item_id,
                abs_episode_id=meta.abs_episode_id,
                chapter_index=meta.chapter_index,
                media_type=meta.media_type,
            )
            session.add(episode)
            new_episodes.append(episode)

        await session.commit()

        if new_episodes and podcast.auto_process:
            await episode_queue.enqueue_episodes([str(ep.id) for ep in new_episodes])
            logger.info("ABS poll: enqueued %d new episodes for %s", len(new_episodes), podcast.title)

        config.last_polled_at = datetime.now(timezone.utc)
        await session.commit()
