import logging
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.openrouter import OpenRouterClient, get_api_key
from app.models.setting import Setting

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-large"

# Whitelist of Postgres text-search configurations we accept. Anything outside
# this set is coerced to 'simple' so the regconfig name is never user-controlled.
_FTS_LANG_WHITELIST = frozenset({
    "simple",
    "danish",
    "english",
    "german",
    "swedish",
    "norwegian",
    "french",
    "spanish",
    "italian",
    "dutch",
    "portuguese",
    "finnish",
    "russian",
})


def _safe_lang(language: str) -> str:
    return language if language in _FTS_LANG_WHITELIST else "simple"


def _vector_literal(values: list[float]) -> str:
    # pgvector accepts text input of the form '[v1,v2,...]' which we cast with
    # ::vector inside the SQL. Bound as a normal text parameter — never
    # interpolated into the SQL string.
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def search_fts(
    session: AsyncSession,
    query: str,
    language: str = "danish",
    podcast_ids: list[str] | None = None,
    episode_ids: list[str] | None = None,
    media_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    lang = _safe_lang(language)

    conditions = ["to_tsvector(:lang::regconfig, ft.full_text) @@ phraseto_tsquery(:lang::regconfig, :query)"]
    params: dict = {"lang": lang, "query": query, "limit": limit}

    if podcast_ids:
        conditions.append("e.podcast_id = ANY(:podcast_ids)")
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append("e.id = ANY(:episode_ids)")
        params["episode_ids"] = episode_ids
    if media_type:
        conditions.append("e.media_type = :media_type")
        params["media_type"] = media_type

    conditions.append("e.media_type != 'ebook'")

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url, e.media_type,
               ts_headline(:lang::regconfig, ft.full_text,
                           phraseto_tsquery(:lang::regconfig, :query),
                           'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20') AS snippet
        FROM transcripts ft
        JOIN episodes e ON e.id = ft.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY ts_rank(to_tsvector(:lang::regconfig, ft.full_text),
                         phraseto_tsquery(:lang::regconfig, :query)) DESC
        LIMIT :limit
    """)

    result = await session.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "media_type": r.media_type,
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
    media_type: str | None = None,
    limit: int = 20,
) -> list[dict]:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    model = setting.value if setting else DEFAULT_EMBEDDING_MODEL
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        query_embedding = await client.embed(model, query)

    qvec = _vector_literal(query_embedding)

    conditions = ["chunk.embedding <=> (:qvec)::vector < 0.5"]
    params: dict = {"qvec": qvec, "limit": limit}
    if podcast_ids:
        conditions.append("e.podcast_id = ANY(:podcast_ids)")
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append("e.id = ANY(:episode_ids)")
        params["episode_ids"] = episode_ids
    if media_type:
        conditions.append("e.media_type = :media_type")
        params["media_type"] = media_type

    conditions.append("e.media_type != 'ebook'")

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT chunk.text, chunk.chunk_index,
               chunk.embedding <=> (:qvec)::vector AS distance,
               e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url, e.media_type
        FROM transcript_chunks chunk
        JOIN transcripts t ON t.id = chunk.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT :limit
    """)

    result = await session.execute(sql, params)
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "media_type": r.media_type,
            "snippet": r.text,
            "score": float(1.0 - r.distance),
            "chunk_index": r.chunk_index,
            "type": "semantic",
        }
        for r in rows
    ]
