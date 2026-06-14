import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update

from app.config import settings
from app.database import async_session
from app.models.episode import Episode
from app.services.pipeline import process_episode

logger = logging.getLogger(__name__)

RUNNING_STATUSES = {"downloading", "transcribing", "summarizing", "indexing"}
STALE_TIMEOUT_MINUTES = 30


class EpisodeQueue:
    def __init__(self):
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_count = settings.max_concurrent_processing
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._currently_processing: dict[str, str] = {}
        self._enqueued_ids: set[str] = set()

    def _enqueue(self, episode_id: str):
        eid = str(episode_id)
        if eid not in self._enqueued_ids:
            self._enqueued_ids.add(eid)
            self._queue.put_nowait(eid)

    async def enqueue_episodes(self, episode_ids: list):
        added = 0
        for eid in episode_ids:
            eid_str = str(eid)
            if eid_str not in self._enqueued_ids:
                self._enqueued_ids.add(eid_str)
                await self._queue.put(eid_str)
                added += 1
        if added:
            logger.info("Enqueued %d episodes for processing", added)

    def enqueue_episode(self, episode_id):
        self._enqueue(str(episode_id))

    async def enqueue_all_pending(self, limit: int = 500) -> int:
        async with async_session() as session:
            result = await session.execute(
                select(Episode.id)
                .where(Episode.status.in_(["new", "error"]))
                .order_by(Episode.created_at.asc())
                .limit(limit)
            )
            ids = [str(row[0]) for row in result.all()]
        if ids:
            await self.enqueue_episodes(ids)
        return len(ids)

    async def _worker(self, worker_id: int):
        logger.info("Queue worker %d started", worker_id)
        while self._running:
            try:
                episode_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue

            self._enqueued_ids.discard(episode_id)

            try:
                async with async_session() as session:
                    episode = await session.get(Episode, episode_id)
                    if not episode:
                        continue
                    if episode.status not in ("new", "error"):
                        continue
                    _ = episode.title
                    self._currently_processing[episode_id] = episode.title

                await process_episode(episode_id)

            except Exception as e:
                logger.error("Worker %d: unhandled error for %s: %s", worker_id, episode_id, e)
            finally:
                self._currently_processing.pop(episode_id, None)

        logger.info("Queue worker %d stopped", worker_id)

    async def start(self):
        if self._running:
            return
        self._running = True

        async with async_session() as session:
            result = await session.execute(
                update(Episode).where(Episode.status.in_(RUNNING_STATUSES)).values(status="new", error_message=None)
            )
            if result.rowcount:
                logger.info("Reset %d stale episodes to queued", result.rowcount)
                await session.commit()

        self._workers = [asyncio.create_task(self._worker(i)) for i in range(self._worker_count)]
        logger.info("EpisodeQueue started with %d workers", self._worker_count)

    async def stop(self):
        self._running = False
        for w in self._workers:
            w.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []
        logger.info("EpisodeQueue stopped")

    async def stale_check(self):
        cutoff = datetime.now(UTC) - timedelta(minutes=STALE_TIMEOUT_MINUTES)
        async with async_session() as session:
            result = await session.execute(
                select(Episode).where(
                    Episode.status.in_(RUNNING_STATUSES),
                    func.coalesce(Episode.updated_at, Episode.created_at) < cutoff,
                )
            )
            stale = result.scalars().all()
            stale = [ep for ep in stale if str(ep.id) not in self._currently_processing]
            if stale:
                for ep in stale:
                    ep.status = "new"
                    ep.error_message = None
                await session.commit()
                logger.info("Stale check: reset %d episodes stuck > %d min", len(stale), STALE_TIMEOUT_MINUTES)

    def get_queued_ids(self) -> list[str]:
        return list(self._enqueued_ids)

    def clear(self):
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._enqueued_ids.clear()
        logger.info("Queue cleared — all items removed")

    def status(self) -> dict:
        return {
            "running_count": len(self._currently_processing),
            "queue_size": self._queue.qsize(),
            "workers": self._worker_count,
            "currently_processing": [
                {"episode_id": eid, "title": title} for eid, title in self._currently_processing.items()
            ],
        }


episode_queue = EpisodeQueue()
