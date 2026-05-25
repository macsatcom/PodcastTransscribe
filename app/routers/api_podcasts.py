from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.services.rss_poller import poll_feed

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


class CreatePodcastRequest(BaseModel):
    title: str
    rss_url: str
    auto_process: bool = True


@router.get("")
async def list_podcasts(
    source_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Podcast)
    if source_type:
        query = query.join(Podcast.source_configs).where(
            SourceConfig.source_type == source_type
        ).distinct()
    result = await db.execute(query.order_by(Podcast.title))
    podcasts = result.scalars().all()

    counts_q = select(
        Episode.podcast_id,
        func.count(Episode.id).label("count"),
        func.max(Episode.published_at).label("latest"),
    ).group_by(Episode.podcast_id)
    counts_result = await db.execute(counts_q)
    counts = {row.podcast_id: row for row in counts_result}

    return [
        {
            "id": str(p.id),
            "title": p.title,
            "author": p.author,
            "description": p.description,
            "cover_url": p.cover_url,
            "language": p.language,
            "auto_process": p.auto_process,
            "media_type": p.media_type,
            "abs_item_id": p.abs_item_id,
            "narrator": p.narrator,
            "episode_count": counts.get(p.id, None).count if p.id in counts else 0,
            "latest_episode": counts.get(p.id, None).latest.isoformat() if p.id in counts and counts[p.id].latest else None,
        }
        for p in podcasts
    ]


@router.post("")
async def create_podcast(
    body: CreatePodcastRequest,
    db: AsyncSession = Depends(get_db),
):
    podcast = Podcast(title=body.title, auto_process=body.auto_process)
    db.add(podcast)
    await db.flush()

    config = SourceConfig(
        podcast_id=podcast.id,
        source_type="rss",
        url=body.rss_url,
        enabled=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(podcast)
    return {"id": str(podcast.id), "title": podcast.title}


@router.get("/{podcast_id}")
async def get_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}
    result = await db.execute(
        select(SourceConfig).where(SourceConfig.podcast_id == podcast_id)
    )
    configs = result.scalars().all()
    return {
        "id": str(podcast.id),
        "title": podcast.title,
        "author": podcast.author,
        "description": podcast.description,
        "cover_url": podcast.cover_url,
        "language": podcast.language,
        "auto_process": podcast.auto_process,
        "media_type": podcast.media_type,
        "abs_item_id": podcast.abs_item_id,
        "narrator": podcast.narrator,
        "sources": [
            {
                "id": str(c.id),
                "source_type": c.source_type,
                "url": c.url,
                "enabled": c.enabled,
            }
            for c in configs
        ],
    }


class UpdatePodcastRequest(BaseModel):
    title: str | None = None
    author: str | None = None
    description: str | None = None
    cover_url: str | None = None
    language: str | None = None
    auto_process: bool | None = None


@router.patch("/{podcast_id}")
async def update_podcast(
    podcast_id: UUID,
    body: UpdatePodcastRequest,
    db: AsyncSession = Depends(get_db),
):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}
    for field in ("title", "author", "description", "cover_url", "language", "auto_process"):
        val = getattr(body, field, None)
        if val is not None:
            setattr(podcast, field, val)
    await db.commit()
    await db.refresh(podcast)
    return {
        "id": str(podcast.id),
        "title": podcast.title,
        "author": podcast.author,
        "description": podcast.description,
        "cover_url": podcast.cover_url,
        "language": podcast.language,
        "auto_process": podcast.auto_process,
        "media_type": podcast.media_type,
        "abs_item_id": podcast.abs_item_id,
        "narrator": podcast.narrator,
    }


@router.post("/{podcast_id}/poll")
async def poll_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}
    result = await db.execute(
        select(SourceConfig).where(
            SourceConfig.podcast_id == podcast_id,
            SourceConfig.enabled == True,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        await poll_feed(config.id)
    return {"status": "polled"}


@router.delete("/{podcast_id}")
async def delete_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}
    await db.delete(podcast)
    await db.commit()
    return {"status": "deleted"}
