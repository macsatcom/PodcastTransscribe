import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text, update, func

from app.database import engine, Base, async_session
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.portal import Portal
from app.models.topic import TopicCluster, EpisodeTopic
from app.models.setting import Setting
from app.models.source_config import SourceConfig
from app.services.rss_poller import poll_all_feeds
from app.services.abs_poller import poll_abs_libraries
from app.services.clustering import run_clustering
from app.services.queue_manager import episode_queue
from app.portal_manager import portal_manager
from app.config import settings

scheduler = AsyncIOScheduler()


async def _deduplicate_abs_podcasts():
    async with async_session() as session:
        already_done = await session.get(Setting, "abs_dedup_2025")
        if already_done:
            return

        dupes_result = await session.execute(
            select(Podcast.abs_item_id, func.count().label("cnt"))
            .where(Podcast.abs_item_id.is_not(None))
            .group_by(Podcast.abs_item_id)
            .having(func.count() > 1)
        )
        duplicate_ids = [row[0] for row in dupes_result.all()]

        if not duplicate_ids:
            session.add(Setting(key="abs_dedup_2025", value="1"))
            await session.commit()
            return

        logger.info("Dedup: found %d abs_item_id values with duplicate podcasts", len(duplicate_ids))

        for abs_id in duplicate_ids:
            pods_result = await session.execute(
                select(Podcast).where(Podcast.abs_item_id == abs_id)
            )
            podcasts = list(pods_result.scalars().all())
            if len(podcasts) < 2:
                continue

            scored = []
            for p in podcasts:
                ready_r = await session.execute(
                    select(func.count(Episode.id)).where(
                        Episode.podcast_id == p.id, Episode.status == "ready"
                    )
                )
                ready_count = ready_r.scalar_one() or 0
                total_r = await session.execute(
                    select(func.count(Episode.id)).where(Episode.podcast_id == p.id)
                )
                total_count = total_r.scalar_one() or 0
                scored.append((p, ready_count, total_count))

            scored.sort(key=lambda x: (x[1], x[2]), reverse=True)
            keep = scored[0][0]
            losers = [s[0] for s in scored[1:]]

            logger.info(
                "Dedup: keeping %s (ready=%d total=%d), removing %d duplicates",
                keep.title, scored[0][1], scored[0][2], len(losers),
            )

            keep_guids_result = await session.execute(
                select(Episode.guid).where(Episode.podcast_id == keep.id)
            )
            keep_guids = {row[0] for row in keep_guids_result.all()}

            for loser in losers:
                los_eps = await session.execute(
                    select(Episode).where(Episode.podcast_id == loser.id)
                )
                for ep in los_eps.scalars().all():
                    if ep.guid in keep_guids:
                        await session.delete(ep)
                    else:
                        ep.podcast_id = keep.id

                await session.flush()

                await session.execute(
                    update(SourceConfig)
                    .where(SourceConfig.podcast_id == loser.id)
                    .values(podcast_id=keep.id)
                )

                await session.delete(loser)

            await session.flush()

        session.add(Setting(key="abs_dedup_2025", value="1"))
        await session.commit()
        logger.info("Dedup: cleanup complete")


async def _run_alembic_upgrade() -> None:
    """Run ``alembic upgrade head`` programmatically.

    Alembic's CLI is sync and expects to manage its own engine. We call it in
    a worker thread so we don't block the event loop, and we let alembic.ini
    + alembic/env.py drive the connection (they already build an async engine
    against the same DATABASE_URL).
    """
    import asyncio
    from alembic import command
    from alembic.config import Config

    def _do_upgrade() -> None:
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_do_upgrade)


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.portal_images_dir, exist_ok=True)
    os.makedirs(settings.audio_temp_dir, exist_ok=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # Apply Alembic migrations. 0001 is a no-op baseline; 0002+ carry the real
    # deltas with idempotent guards, so this is safe on both fresh databases
    # (where create_all already produced the latest schema) and legacy
    # databases that pre-date Alembic.
    await _run_alembic_upgrade()

    await _deduplicate_abs_podcasts()

    await episode_queue.start()

    scheduler.add_job(
        poll_all_feeds,
        trigger="interval",
        hours=6,
        id="rss_poll",
        replace_existing=True,
    )
    scheduler.add_job(
        poll_abs_libraries,
        trigger="interval",
        hours=6,
        id="abs_poll",
        replace_existing=True,
    )
    scheduler.add_job(
        episode_queue.stale_check,
        trigger="interval",
        minutes=5,
        id="stale_check",
        replace_existing=True,
    )
    scheduler.add_job(
        run_clustering,
        trigger="cron",
        hour=3,
        minute=0,
        id="daily_clustering",
        replace_existing=True,
    )
    scheduler.start()

    async with async_session() as session:
        result = await session.execute(select(Portal))
        portals = result.scalars().all()
        await portal_manager.start_all(portals)

    yield
    await portal_manager.stop_all()
    scheduler.shutdown(wait=False)
    await episode_queue.stop()
    await engine.dispose()


app = FastAPI(title="Podcast Transcription and Search", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals, api_abs, api_insights

app.include_router(api_podcasts.router)
app.include_router(api_episodes.router)
app.include_router(api_queue.router)
app.include_router(api_search.router)
app.include_router(api_settings.router)
app.include_router(ui.router)
app.include_router(api_portals.router)
app.include_router(api_abs.router)
app.include_router(api_insights.router)
