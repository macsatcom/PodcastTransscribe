from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.topic import EpisodeTopic
from app.models.transcript import Transcript, TranscriptChunk
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


@router.get("/quality-stats")
async def quality_stats(db: AsyncSession = Depends(get_db)):
    """Per-podcast WPM quality summary for all podcasts with at least one ready episode."""
    sql = text(
        """
        SELECT
            p.id::text AS podcast_id,
            p.title AS podcast_title,
            COUNT(e.id) FILTER (WHERE e.status = 'ready') AS transcribed,
            ROUND(
                AVG(
                    char_length(t.full_text) * 60.0 / (5.5 * e.duration_seconds)
                ) FILTER (WHERE e.status = 'ready' AND e.duration_seconds > 0 AND t.full_text IS NOT NULL)
            )::int AS avg_wpm,
            COUNT(e.id) FILTER (
                WHERE e.status = 'ready'
                  AND e.duration_seconds > 0
                  AND t.full_text IS NOT NULL
                  AND char_length(t.full_text) * 60.0 / (5.5 * e.duration_seconds) < 80
            ) AS below_80,
            COUNT(e.id) FILTER (
                WHERE e.status = 'ready'
                  AND e.duration_seconds > 0
                  AND t.full_text IS NOT NULL
                  AND char_length(t.full_text) * 60.0 / (5.5 * e.duration_seconds) < 120
            ) AS below_120
        FROM podcasts p
        LEFT JOIN episodes e ON e.podcast_id = p.id
        LEFT JOIN transcripts t ON t.episode_id = e.id
        GROUP BY p.id, p.title
        HAVING COUNT(e.id) FILTER (WHERE e.status = 'ready') > 0
        ORDER BY avg_wpm ASC NULLS LAST
        """
    )
    result = await db.execute(sql)
    rows = result.mappings().all()
    return [
        {
            "podcast_id": row["podcast_id"],
            "podcast_title": row["podcast_title"],
            "transcribed": row["transcribed"],
            "avg_wpm": row["avg_wpm"],
            "below_80": row["below_80"],
            "below_80_pct": round(row["below_80"] / row["transcribed"] * 100) if row["transcribed"] else 0,
            "below_120": row["below_120"],
            "below_120_pct": round(row["below_120"] / row["transcribed"] * 100) if row["transcribed"] else 0,
        }
        for row in rows
    ]


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
    # Remove stale topic assignments derived from this transcript.
    await db.execute(delete(EpisodeTopic).where(EpisodeTopic.episode_id == episode_id))
    # Delete transcript (TranscriptChunk cascades via FK at DB level or ORM).
    result = await db.execute(select(Transcript).where(Transcript.episode_id == episode_id))
    transcript = result.scalar_one_or_none()
    if transcript:
        await db.execute(delete(TranscriptChunk).where(TranscriptChunk.transcript_id == transcript.id))
        await db.delete(transcript)
    episode.status = "new"
    episode.error_message = None
    episode.model_used = None
    episode.processing_seconds = None
    episode.cost = None
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


class ResetTruncatedRequest(BaseModel):
    wpm_threshold: float = 120.0
    podcast_id: UUID | None = None
    dry_run: bool = False


@router.post("/reset-truncated")
async def reset_truncated(req: ResetTruncatedRequest, db: AsyncSession = Depends(get_db)):
    """Find ready episodes with WPM below threshold and reset them to 'new' for re-processing.

    Uses char_length(full_text) / 5.5 / (duration_seconds / 60) as the WPM proxy.
    Only targets episodes with status='ready' that have a transcript and duration.
    """
    # Identify candidate episodes: ready + has transcript + below WPM threshold
    candidate_query = (
        select(Episode.id, Episode.title, Podcast.title.label("podcast_title"))
        .join(Transcript, Transcript.episode_id == Episode.id)
        .join(Podcast, Podcast.id == Episode.podcast_id)
        .where(Episode.status == "ready")
        .where(Episode.duration_seconds > 0)
        .where(Transcript.full_text.is_not(None))
        .where(func.char_length(Transcript.full_text) * 60.0 / (5.5 * Episode.duration_seconds) < req.wpm_threshold)
    )
    if req.podcast_id:
        candidate_query = candidate_query.where(Episode.podcast_id == req.podcast_id)

    result = await db.execute(candidate_query)
    rows = result.all()
    episode_ids = [row[0] for row in rows]
    count = len(episode_ids)

    preview = [
        {
            "id": str(row[0]),
            "title": row[1],
            "podcast": row[2],
        }
        for row in rows[:10]
    ]

    if req.dry_run or not episode_ids:
        return {"affected": count, "dry_run": True, "preview": preview}

    # Bulk delete/reset — ordered to respect FK constraints:
    # 1. Remove stale topic assignments
    await db.execute(delete(EpisodeTopic).where(EpisodeTopic.episode_id.in_(episode_ids)))

    # 2. Get transcript IDs, then delete chunks, then transcripts
    tr_result = await db.execute(select(Transcript.id).where(Transcript.episode_id.in_(episode_ids)))
    transcript_ids = [r[0] for r in tr_result.all()]
    if transcript_ids:
        await db.execute(delete(TranscriptChunk).where(TranscriptChunk.transcript_id.in_(transcript_ids)))
        await db.execute(delete(Transcript).where(Transcript.id.in_(transcript_ids)))

    # 3. Reset episode fields
    await db.execute(
        update(Episode)
        .where(Episode.id.in_(episode_ids))
        .values(
            status="new",
            model_used=None,
            cost=None,
            processing_seconds=None,
            error_message=None,
        )
    )
    await db.commit()

    return {"affected": count, "dry_run": False, "preview": preview}
