from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.searcher import search_fts, search_semantic

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query("", description="Keyword search (FTS)"),
    nq: str = Query("", description="Natural language search (semantic)"),
    mode: str = Query("auto", description="Search mode: fts, semantic, or auto"),
    language: str = Query("danish", description="Language for FTS"),
    podcast_ids: str | None = Query(None, description="Comma-separated podcast IDs"),
    episode_ids: str | None = Query(None, description="Comma-separated episode IDs"),
    media_type: str | None = Query(None, description="Filter by media type (podcast, book)"),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    pid_list = podcast_ids.split(",") if podcast_ids else None
    eid_list = episode_ids.split(",") if episode_ids else None

    if q and nq:
        fts_results = await search_fts(db, q, language, pid_list, eid_list, media_type, limit)
        semantic_results = await search_semantic(db, nq, pid_list, eid_list, media_type, limit)
    elif mode == "fts":
        fts_results = await search_fts(db, q, language, pid_list, eid_list, media_type, limit)
        semantic_results = []
    elif mode == "semantic":
        fts_results = []
        semantic_results = await search_semantic(db, q, pid_list, eid_list, media_type, limit)
    else:
        fts_results = await search_fts(db, q, language, pid_list, eid_list, media_type, limit)
        semantic_results = await search_semantic(db, q, pid_list, eid_list, media_type, limit)

    seen = set()
    results = []
    for r in fts_results + semantic_results:
        if r["episode_id"] not in seen:
            seen.add(r["episode_id"])
            results.append(r)

    return {"results": results, "total": len(results)}
