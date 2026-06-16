from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.transcript import Transcript
from app.services.queue_manager import episode_queue

router = APIRouter(prefix="/api/episodes", tags=["episodes"])


def _serialize_episode(
    e: Episode,
    queued_ids: set[str],
    podcast_title: str | None = None,
    char_count: int | None = None,
) -> dict:
    # word_count: char_count includes spaces; average ~5.5 chars per word in
    # speech transcripts (English ~4.5 letter word + 1 space).
    word_count = round(char_count / 5.5) if char_count else None
    return {
        "id": str(e.id),
        "podcast_id": str(e.podcast_id),
        "podcast_title": podcast_title,
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
        "queued": str(e.id) in queued_ids,
        "transcript_char_count": char_count,
        "transcript_word_count": word_count,
    }


@router.get("")
async def list_episodes(
    podcast_id: UUID | None = None,
    podcast_ids: str | None = None,
    status: str | None = None,
    media_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    ids = []
    if podcast_ids is not None and podcast_ids.strip() != "":
        try:
            ids = [UUID(item.strip()) for item in podcast_ids.split(",") if item.strip()]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid UUID in podcast_ids") from exc

    # Always join Podcast (title) and LEFT JOIN Transcript (transcript stats).
    # Consolidates the two former code paths into one consistent query shape.
    query = (
        select(
            Episode,
            Podcast.title.label("podcast_title"),
            func.char_length(Transcript.full_text).label("char_count"),
        )
        .join(Podcast, Podcast.id == Episode.podcast_id)
        .outerjoin(Transcript, Transcript.episode_id == Episode.id)
    )

    if ids:
        query = query.where(Episode.podcast_id.in_(ids))
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
    if offset:
        query = query.offset(offset)
    query = query.limit(limit)

    result = await db.execute(query)
    queued_ids = {str(eid) for eid in episode_queue.get_queued_ids()}
    rows = result.all()
    return [_serialize_episode(row.Episode, queued_ids, row.podcast_title, row.char_count) for row in rows]


@router.get("/{episode_id}")
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}
    result = await db.execute(select(Transcript).where(Transcript.episode_id == episode_id))
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
        }
        if transcript
        else None,
    }


@router.get("/{episode_id}/chunks")
async def get_episode_chunks(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    from app.models.transcript import TranscriptChunk

    result = await db.execute(select(Transcript).where(Transcript.episode_id == episode_id))
    transcript = result.scalar_one_or_none()
    if not transcript:
        return []
    chunks_result = await db.execute(
        select(TranscriptChunk)
        .where(TranscriptChunk.transcript_id == transcript.id)
        .order_by(TranscriptChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()
    return [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "start_time": c.start_time,
            "end_time": c.end_time,
        }
        for c in chunks
    ]


@router.post("/{episode_id}/reset")
async def reset_episode(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}
    result = await db.execute(select(Transcript).where(Transcript.episode_id == episode_id))
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
