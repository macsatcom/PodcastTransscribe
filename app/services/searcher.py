import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.transcript import Transcript, TranscriptChunk
from app.services.openrouter import OpenRouterClient, get_api_key
from app.models.setting import Setting

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"


async def search_fts(
    session: AsyncSession,
    query: str,
    language: str = "danish",
    podcast_ids: list[str] | None = None,
    episode_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    conditions = [text(f"to_tsvector('{language}', ft.full_text) @@ phraseto_tsquery('{language}', :query)")]
    params = {"query": query}

    if podcast_ids:
        conditions.append(text("e.podcast_id = ANY(:podcast_ids)"))
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append(text("e.id = ANY(:episode_ids)"))
        params["episode_ids"] = episode_ids

    where_clause = " AND ".join(str(c) for c in conditions)

    sql = text(f"""
        SELECT e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url,
               ts_headline(:lang, ft.full_text, phraseto_tsquery(:lang, :query),
                           'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20') AS snippet
        FROM transcripts ft
        JOIN episodes e ON e.id = ft.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY ts_rank(to_tsvector(:lang, ft.full_text), phraseto_tsquery(:lang, :query)) DESC
        LIMIT :limit
    """)

    result = await session.execute(sql, {"lang": language, "limit": limit, **params})
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "snippet": r.snippet,
            "type": "fts",
        }
        for r in rows
    ]


async def search_semantic(
    session: AsyncSession,
    query: str,
    podcast_ids: list[str] | None = None,
    episode_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    model = setting.value if setting else DEFAULT_EMBEDDING_MODEL
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        query_embedding = await client.embed(model, query)

    embedding_str = "'[" + ",".join(str(v) for v in query_embedding) + "]'::vector"

    conditions = ["1=1"]
    params: dict = {}
    if podcast_ids:
        conditions.append("e.podcast_id = ANY(:podcast_ids)")
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append("e.id = ANY(:episode_ids)")
        params["episode_ids"] = episode_ids

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT chunk.text, chunk.chunk_index,
               chunk.embedding <=> {embedding_str} AS distance,
               e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url
        FROM transcript_chunks chunk
        JOIN transcripts t ON t.id = chunk.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT :limit
    """)

    result = await session.execute(sql, {"limit": limit, **params})
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "snippet": r.text,
            "score": float(1.0 - r.distance),
            "chunk_index": r.chunk_index,
            "type": "semantic",
        }
        for r in rows
    ]
