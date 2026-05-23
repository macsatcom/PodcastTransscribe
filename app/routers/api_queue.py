from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.episode import Episode

router = APIRouter(prefix="/api", tags=["queue"])

RUNNING_STATUSES = {"downloading", "transcribing", "summarizing", "indexing"}


def _serialize(episode: Episode) -> dict:
    return {
        "id": str(episode.id),
        "podcast_id": str(episode.podcast_id),
        "podcast_title": episode.podcast.title if episode.podcast else None,
        "title": episode.title,
        "status": episode.status,
        "error_message": episode.error_message,
        "processing_seconds": episode.processing_seconds,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
    }


@router.get("/queue")
async def get_queue(db: AsyncSession = Depends(get_db)):
    query = (
        select(Episode)
        .options(joinedload(Episode.podcast))
        .order_by(Episode.created_at.desc())
        .limit(500)
    )
    result = await db.execute(query)
    episodes = result.scalars().all()

    items = [_serialize(e) for e in episodes]

    running = [e for e in items if e["status"] in RUNNING_STATUSES]
    queued = [e for e in items if e["status"] == "new"]
    error = [e for e in items if e["status"] == "error"]
    done = [e for e in items if e["status"] == "ready"]

    running.sort(key=lambda e: e["created_at"], reverse=True)
    queued.sort(key=lambda e: e["created_at"])
    error.sort(key=lambda e: e["created_at"], reverse=True)
    done.sort(key=lambda e: e["created_at"], reverse=True)
    done = done[:50]

    return {
        "running": running,
        "queued": queued,
        "error": error,
        "done": done,
        "counts": {
            "running": len(running),
            "queued": len(queued),
            "error": len(error),
            "done": len(done),
        },
    }
