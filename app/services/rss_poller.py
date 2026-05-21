import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.adapters.rss import RSSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig

logger = logging.getLogger(__name__)


async def poll_all_feeds():
    async with async_session() as session:
        result = await session.execute(
            select(SourceConfig).where(
                SourceConfig.source_type == "rss",
                SourceConfig.enabled == True,
            )
        )
        configs = result.scalars().all()

    await asyncio.gather(*(poll_feed(c.id) for c in configs), return_exceptions=True)


async def poll_feed(source_config_id):
    async with async_session() as session:
        result = await session.execute(
            select(SourceConfig).where(SourceConfig.id == source_config_id)
        )
        config = result.scalar_one_or_none()
        if not config:
            return

        adapter = RSSSourceAdapter()
        try:
            episodes_meta = await adapter.discover_new(config.url)
        except Exception as e:
            logger.error("RSS poll failed for %s: %s", config.url, e)
            return

        podcast = await session.get(Podcast, config.podcast_id)
        if not podcast:
            logger.warning("Podcast %s not found for source config %s", config.podcast_id, config.id)
            return

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

        config.last_polled_at = datetime.now(timezone.utc)
        await session.commit()
