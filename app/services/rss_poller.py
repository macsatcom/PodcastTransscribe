import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.adapters.rss import RSSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.services.queue_manager import episode_queue

logger = logging.getLogger(__name__)


async def poll_all_feeds():
    async with async_session() as session:
        result = await session.execute(
            select(SourceConfig).where(
                SourceConfig.source_type == "rss",
                SourceConfig.enabled,
            )
        )
        configs = result.scalars().all()

    for cfg in configs:
        try:
            await poll_feed(cfg.id)
        except Exception as e:
            logger.error("RSS poll failed for config %s: %s", cfg.id, e)


async def poll_feed(source_config_id):
    async with async_session() as session:
        result = await session.execute(select(SourceConfig).where(SourceConfig.id == source_config_id))
        config = result.scalar_one_or_none()
        if not config:
            return

        adapter = RSSSourceAdapter()
        try:
            episodes_meta = await adapter.discover_new(config.url)
        except Exception as e:
            logger.error("RSS parse failed for %s: %s", config.url, e)
            return

        podcast = await session.get(Podcast, config.podcast_id)
        if not podcast:
            logger.warning("Podcast %s not found for source config %s", config.podcast_id, config.id)
            return

        auto_process = podcast.auto_process
        new_episode_ids = []
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

            episode = Episode(
                podcast_id=podcast.id,
                guid=meta.guid,
                title=meta.title,
                description=meta.description,
                audio_url=meta.audio_url,
                duration_seconds=meta.duration_seconds,
                published_at=meta.published_at,
                status="new",
            )
            session.add(episode)
            await session.flush()
            new_episode_ids.append(episode.id)

        config.last_polled_at = datetime.now(UTC)
        await session.commit()

    if auto_process and new_episode_ids:
        await episode_queue.enqueue_episodes(new_episode_ids)
        logger.info("RSS poll: enqueued %d new episodes for podcast %s", len(new_episode_ids), podcast.id)
