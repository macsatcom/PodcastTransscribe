import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.abs import ABSSourceAdapter
from app.config import settings
from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.models.setting import Setting
from app.services.queue_manager import episode_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/abs", tags=["abs"])

PROCESSING_STATUSES = frozenset({"downloading", "transcribing", "summarizing", "indexing"})


def normalize_status(status: str | None) -> str:
    if not status:
        return "none"
    if status in PROCESSING_STATUSES:
        return "processing"
    return status


async def get_adapter(db: AsyncSession | None = None) -> ABSSourceAdapter:
    if db is not None:
        abs_url_setting = await db.get(Setting, "abs_url")
        abs_key_setting = await db.get(Setting, "abs_api_key")
        db_url = (abs_url_setting.value if abs_url_setting else "").strip()
        db_key = (abs_key_setting.value if abs_key_setting else "").strip()
        if db_url and db_key:
            return ABSSourceAdapter(abs_url=db_url, api_key=db_key)
    return ABSSourceAdapter()


@router.get("/libraries")
async def list_abs_libraries(db: AsyncSession = Depends(get_db)):
    adapter = await get_adapter(db)
    try:
        libs = await adapter.get_libraries()
        return [
            {
                "id": lib["id"],
                "name": lib.get("name", ""),
                "mediaType": lib.get("mediaType", ""),
                "icon": lib.get("icon", "database"),
            }
            for lib in libs
        ]
    except Exception as e:
        logger.error("Failed to fetch ABS libraries: %s", e)
        return {"error": str(e)}


@router.get("/library/{library_id}/items")
async def browse_library_items(
    library_id: str,
    db: AsyncSession = Depends(get_db),
):
    adapter = await get_adapter(db)
    try:
        items = await adapter.get_library_items(library_id)
    except Exception as e:
        logger.error("Failed to fetch library items: %s", e)
        return {"error": str(e), "items": []}

    abs_ids = [item.get("id", "") for item in items if item.get("id")]
    result = await db.execute(
        select(Podcast).where(Podcast.abs_item_id.in_(abs_ids))
    )
    our_podcasts = {p.abs_item_id: p for p in result.scalars().all()}

    episode_data = {}
    if our_podcasts:
        pid_map = {str(p.id): p.abs_item_id for p in our_podcasts.values()}
        our_ids = list(pid_map.keys())
        rows = await db.execute(
            select(
                Episode.podcast_id,
                Episode.status,
                Episode.model_used,
                Episode.processing_seconds,
            ).where(Episode.podcast_id.in_(our_ids))
        )
        for row in rows:
            abs_id = pid_map.get(str(row.podcast_id))
            if not abs_id:
                continue
            if abs_id not in episode_data:
                episode_data[abs_id] = {"ready": 0, "processing": 0, "error": 0, "models": set(), "total_processing": 0}
            ns = normalize_status(row.status)
            if ns == "ready":
                episode_data[abs_id]["ready"] += 1
            elif ns == "processing":
                episode_data[abs_id]["processing"] += 1
            elif ns == "error":
                episode_data[abs_id]["error"] += 1
            if row.model_used:
                episode_data[abs_id]["models"].add(row.model_used)
            if row.processing_seconds:
                episode_data[abs_id]["total_processing"] += row.processing_seconds

    result_items = []
    for raw in items:
        abs_id = raw.get("id", "")
        podcast = our_podcasts.get(abs_id)
        media = raw.get("media", {})
        metadata = media.get("metadata", {})
        media_type = raw.get("mediaType", "book")

        if media_type == "podcast":
            num_total = media.get("numEpisodes", 0) or 0
        else:
            num_total = media.get("numChapters", 0) or 0

        if media_type == "book" and num_total == 0 and not media.get("duration"):
            media_type = "ebook"

        transcribe_status = "none"
        latest_model = None
        total_processing_seconds = None
        auto_process = False

        if podcast and abs_id in episode_data:
            d = episode_data[abs_id]
            if d["processing"] > 0:
                transcribe_status = "processing"
            if d["ready"] > 0:
                if d["ready"] >= num_total:
                    transcribe_status = "done"
                elif transcribe_status != "processing":
                    transcribe_status = "partial"
            if d["error"] > 0 and transcribe_status == "none":
                transcribe_status = "partial"
            auto_process = podcast.auto_process
            if d["models"]:
                latest_model = ", ".join(sorted(d["models"]))
            if d["total_processing"] > 0:
                total_processing_seconds = d["total_processing"]

        author = metadata.get("author") or metadata.get("authorName") or metadata.get("narratorName") or ""

        result_items.append({
            "id": abs_id,
            "title": metadata.get("title", abs_id),
            "author": author,
            "cover_url": f"/api/abs/items/{abs_id}/cover",
            "media_type": media_type,
            "duration": media.get("duration"),
            "num_episodes": num_total,
            "transcribe_status": transcribe_status,
            "auto_process": auto_process,
            "latest_model": latest_model,
            "total_processing_seconds": total_processing_seconds,
        })

    return {"items": result_items}


@router.get("/items/{item_id}")
async def get_abs_item(item_id: str, db: AsyncSession = Depends(get_db)):
    adapter = await get_adapter(db)
    try:
        abs_item = await adapter.get_item(item_id, expanded=True)
    except Exception as e:
        return {"error": str(e)}

    media = abs_item.get("media", {})
    metadata = media.get("metadata", {})
    media_type = abs_item.get("mediaType", "book")

    podcast_query = select(Podcast).where(Podcast.abs_item_id == item_id)
    podcast = (await db.execute(podcast_query)).scalar_one_or_none()

    if podcast:
        real_title = metadata.get("title", "")
        if real_title and (podcast.title == podcast.abs_item_id or not podcast.author):
            podcast.title = real_title
            podcast.author = metadata.get("author") or metadata.get("authorName") or metadata.get("narratorName") or podcast.author or ""
            await db.commit()

    our_id = str(podcast.id) if podcast else None
    auto_process = podcast.auto_process if podcast else False

    raw_episodes = media.get("episodes", media.get("chapters", [])) or []
    if not raw_episodes and media_type == "podcast":
        try:
            await adapter.check_new_episodes(item_id)
            abs_item = await adapter.get_item(item_id, expanded=True)
            media = abs_item.get("media", {})
            raw_episodes = media.get("episodes", []) or []
        except Exception:
            pass

    our_episodes_map = {}
    if podcast:
        rows = await db.execute(
            select(Episode).where(Episode.podcast_id == podcast.id)
        )
        for ep in rows.scalars().all():
            key = ep.abs_episode_id or str(ep.chapter_index or 0)
            our_episodes_map[key] = ep

    if media_type == "podcast":
        raw_episodes.sort(key=lambda e: e.get("publishedAt") or 0, reverse=True)

    episode_list = []
    for i, ep in enumerate(raw_episodes):
        if media_type == "podcast":
            ep_id = ep.get("id", str(i))
            ep_title = ep.get("title", f"Episode {i + 1}")
            ep_duration = ep.get("duration")
        else:
            ep_id = str(i)
            ep_title = ep.get("title", f"Chapter {i + 1}")
            start = ep.get("start", ep.get("startOffset", 0))
            end = ep.get("end", ep.get("endOffset", 0))
            ep_duration = (end - start) if end > start else None

        our_ep = our_episodes_map.get(ep_id)
        published_at = ep.get("publishedAt") if media_type == "podcast" else None
        episode_list.append({
            "id": ep_id,
            "title": ep_title,
            "duration": ep_duration,
            "status": normalize_status(our_ep.status) if our_ep else "none",
            "our_episode_id": str(our_ep.id) if our_ep else None,
            "model_used": our_ep.model_used if our_ep else None,
            "processing_seconds": our_ep.processing_seconds if our_ep else None,
            "error_message": our_ep.error_message if our_ep and our_ep.status == "error" else None,
            "published_at": published_at,
        })

    return {
        "id": item_id,
        "our_id": our_id,
        "title": metadata.get("title", ""),
        "author": metadata.get("author") or metadata.get("authorName") or metadata.get("narratorName") or "",
        "narrator": metadata.get("narratorName", ""),
        "description": metadata.get("description", ""),
        "cover_url": f"/api/abs/items/{item_id}/cover",
        "media_type": media_type,
        "duration": media.get("duration"),
        "auto_process": auto_process,
        "episodes": episode_list,
    }


@router.get("/items/{item_id}/cover")
async def get_abs_cover(item_id: str, db: AsyncSession = Depends(get_db)):
    adapter = await get_adapter(db)
    try:
        client = adapter._get_client()
        resp = await client.get(f"/api/items/{item_id}/cover")
        return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except Exception as e:
        logger.error("Failed to fetch cover for %s: %s", item_id, e)
        return Response(status_code=404)


@router.post("/items/{item_id}/auto-process")
async def toggle_auto_process(item_id: str, body: dict, db: AsyncSession = Depends(get_db)):
    auto_process = body.get("auto_process", False)
    podcast = (await db.execute(
        select(Podcast).where(Podcast.abs_item_id == item_id)
    )).scalar_one_or_none()

    if not podcast:
        adapter = await get_adapter(db)
        try:
            abs_item = await adapter.get_item(item_id)
            media = abs_item.get("media", {})
            metadata = media.get("metadata", {})
            title = metadata.get("title", item_id)
            author = metadata.get("author") or metadata.get("authorName") or metadata.get("narratorName") or ""
            media_type = abs_item.get("mediaType", "podcast")
        except Exception:
            title = item_id
            author = ""
            media_type = "podcast"

        podcast = Podcast(
            title=title,
            author=author,
            abs_item_id=item_id,
            media_type=media_type,
            auto_process=auto_process,
        )
        db.add(podcast)
        await db.flush()

        config = SourceConfig(
            podcast_id=podcast.id,
            source_type="abs",
            url=item_id,
            enabled=True,
        )
        db.add(config)

    podcast.auto_process = auto_process
    await db.commit()
    return {"auto_process": podcast.auto_process}


@router.post("/items/{item_id}/enqueue-pending")
async def enqueue_pending(item_id: str, db: AsyncSession = Depends(get_db)):
    podcast = (await db.execute(
        select(Podcast).where(Podcast.abs_item_id == item_id)
    )).scalar_one_or_none()

    if not podcast:
        return {"status": "no podcast found", "count": 0}

    rows = await db.execute(
        select(Episode.id).where(
            Episode.podcast_id == podcast.id,
            Episode.status.in_(["new", "error"]),
        )
    )
    ids = [str(r[0]) for r in rows.all()]
    if ids:
        await episode_queue.enqueue_episodes(ids)
    return {"status": "enqueued", "count": len(ids)}


@router.post("/items/enqueue-pending-batch")
async def enqueue_pending_batch(body: dict, db: AsyncSession = Depends(get_db)):
    abs_item_ids = body.get("abs_item_ids", [])
    total = 0
    for abs_id in abs_item_ids:
        podcast = (await db.execute(
            select(Podcast).where(Podcast.abs_item_id == abs_id)
        )).scalar_one_or_none()
        if not podcast:
            continue
        rows = await db.execute(
            select(Episode.id).where(
                Episode.podcast_id == podcast.id,
                Episode.status.in_(["new", "error"]),
            )
        )
        ids = [str(r[0]) for r in rows.all()]
        if ids:
            await episode_queue.enqueue_episodes(ids)
            total += len(ids)
    return {"status": "enqueued", "count": total}
