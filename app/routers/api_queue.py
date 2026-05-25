from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.episode import Episode
from app.services.queue_manager import episode_queue, RUNNING_STATUSES

router = APIRouter(prefix="/api", tags=["queue"])


def _serialize(episode: Episode) -> dict:
    return {
        "id": str(episode.id),
        "podcast_id": str(episode.podcast_id),
        "podcast_title": episode.podcast.title if episode.podcast else None,
        "title": episode.title,
        "status": episode.status,
        "error_message": episode.error_message,
        "processing_seconds": episode.processing_seconds,
        "media_type": episode.media_type,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
    }


@router.get("/queue")
async def get_queue(db: AsyncSession = Depends(get_db)):
    total_query = select(Episode.status, func.count().label("cnt")).group_by(Episode.status)
    total_result = await db.execute(total_query)
    total_by_status = {row[0]: row[1] for row in total_result.all()}

    total_counts = {
        "running": sum(total_by_status.get(s, 0) for s in RUNNING_STATUSES),
        "queued": total_by_status.get("new", 0),
        "error": total_by_status.get("error", 0),
        "done": total_by_status.get("ready", 0),
    }

    running_query = (
        select(Episode).options(joinedload(Episode.podcast))
        .where(Episode.status.in_(RUNNING_STATUSES))
        .order_by(Episode.created_at.desc())
        .limit(50)
    )
    running_result = await db.execute(running_query)
    running = [_serialize(e) for e in running_result.scalars().all()]

    queued_ids = episode_queue.get_queued_ids()
    if queued_ids:
        queued_query = (
            select(Episode).options(joinedload(Episode.podcast))
            .where(Episode.id.in_(queued_ids))
            .order_by(Episode.created_at.asc())
            .limit(200)
        )
        queued_result = await db.execute(queued_query)
        queued = [_serialize(e) for e in queued_result.scalars().all()]
    else:
        queued = []

    error_query = (
        select(Episode).options(joinedload(Episode.podcast))
        .where(Episode.status == "error")
        .order_by(Episode.created_at.desc())
        .limit(20)
    )
    error_result = await db.execute(error_query)
    error = [_serialize(e) for e in error_result.scalars().all()]

    done_query = (
        select(Episode).options(joinedload(Episode.podcast))
        .where(Episode.status == "ready")
        .order_by(Episode.created_at.desc())
        .limit(50)
    )
    done_result = await db.execute(done_query)
    done = [_serialize(e) for e in done_result.scalars().all()]

    qm_status = episode_queue.status()

    return {
        "running": running,
        "queued": queued,
        "error": error,
        "done": done,
        "counts": {
            "running": qm_status["running_count"],
            "queued": len(queued_ids),
            "error": total_by_status.get("error", 0),
            "done": total_by_status.get("ready", 0),
            "new_total": total_by_status.get("new", 0),
        },
        "queue_manager": qm_status,
    }
