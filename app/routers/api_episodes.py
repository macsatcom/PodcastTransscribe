from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.transcript import Transcript
from app.services.pipeline import reset_episode_safe
from app.services.queue_manager import episode_queue

router = APIRouter(prefix="/api/episodes", tags=["episodes"])


@router.get("")
async def list_episodes(
    podcast_id: UUID | None = None,
    status: str | None = None,
    media_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Episode)
    if podcast_id:
        query = query.where(Episode.podcast_id == podcast_id)
    if status:
        if status == "processing":
            query = query.where(Episode.status.in_(["downloading", "transcribing", "summarizing", "indexing"]))
        else:
            query = query.where(Episode.status == status)
    if media_type:
        query = query.where(Episode.media_type == media_type)
    query = query.order_by(Episode.published_at.desc())
    result = await db.execute(query)
    episodes = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "podcast_id": str(e.podcast_id),
            "title": e.title,
            "description": e.description,
            "duration_seconds": e.duration_seconds,
            "published_at": e.published_at.isoformat() if e.published_at else None,
            "status": e.status,
            "error_message": e.error_message,
            "model_used": e.model_used,
            "processing_seconds": e.processing_seconds,
            "cost": e.cost,
            "media_type": e.media_type,
            "abs_item_id": e.abs_item_id,
            "abs_episode_id": e.abs_episode_id,
            "chapter_index": e.chapter_index,
        }
        for e in episodes
    ]


@router.get("/{episode_id}")
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}
    result = await db.execute(
        select(Transcript).where(Transcript.episode_id == episode_id)
    )
    transcript = result.scalar_one_or_none()
    return {
        "id": str(episode.id),
        "podcast_id": str(episode.podcast_id),
        "title": episode.title,
        "description": episode.description,
        "duration_seconds": episode.duration_seconds,
        "published_at": episode.published_at.isoformat() if episode.published_at else None,
        "status": episode.status,
        "error_message": episode.error_message,
        "model_used": episode.model_used,
        "processing_seconds": episode.processing_seconds,
        "cost": episode.cost,
        "transcript": {
            "full_text": transcript.full_text if transcript else None,
            "summary": transcript.summary if transcript else None,
            "detected_language": transcript.detected_language if transcript else None,
        } if transcript else None,
    }


@router.post("/{episode_id}/reset")
async def reset_episode(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}
    result = await db.execute(
        select(Transcript).where(Transcript.episode_id == episode_id)
    )
    transcript = result.scalar_one_or_none()
    if transcript:
        await db.delete(transcript)
    episode.status = "new"
    episode.error_message = None
    episode.model_used = None
    episode.processing_seconds = None
    await db.commit()
    return {"status": "reset"}


@router.post("/{episode_id}/process")
async def process_episode_endpoint(episode_id: UUID):
    episode_queue.enqueue_episode(episode_id)
    return {"status": "enqueued"}


@router.post("/process-batch")
async def process_batch(data: dict):
    ids = data.get("ids", [])
    if not ids:
        return {"status": "no ids provided"}
    await episode_queue.enqueue_episodes(ids)
    return {"status": "enqueued", "count": len(ids)}


@router.post("/process-all-pending")
async def process_all_pending():
    count = await episode_queue.enqueue_all_pending()
    return {"status": "enqueued", "count": count}
