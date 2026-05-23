import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text

from app.database import engine, Base, async_session
from app.models.portal import Portal
from app.services.rss_poller import poll_all_feeds
from app.portal_manager import portal_manager
from app.config import settings

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.portal_images_dir, exist_ok=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    scheduler.add_job(
        poll_all_feeds,
        trigger="interval",
        hours=6,
        id="rss_poll",
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
    await engine.dispose()


app = FastAPI(title="Podcast Transcription and Search", lifespan=lifespan)

from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals

app.include_router(api_podcasts.router)
app.include_router(api_episodes.router)
app.include_router(api_queue.router)
app.include_router(api_search.router)
app.include_router(api_settings.router)
app.include_router(ui.router)
app.include_router(api_portals.router)
