"""Search engine: keyword (FTS) and semantic (pgvector cosine).

Semantic search:
- Filters by `embedding_model` so query/doc vectors are always in the same
  space (no cross-model drift after a re-embed migration).
- Filters by configurable cosine-distance threshold (default 0.40) so
  irrelevant chunks below the relevance bar never appear.
- Aggregates chunk hits at the episode level: each result represents one
  episode with up to 3 evidence chunks (best chunk + up to 2 supporting
  chunks with non-trivial diversity from the best).
- Episode aggregation provides cross-episode diversity; we deliberately
  skip explicit MMR over the chunk candidate set and revisit only if
  near-duplicate chunks within a single episode become a quality issue.
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-large"

THRESHOLD_KEY = "semantic_distance_threshold"
DEFAULT_DISTANCE_THRESHOLD = 0.65  # calibrated for text-embedding-3-large query→chunk distances

# Diversity floor: a supporting chunk in the same episode must be at least
# this much further from the query than the episode's best chunk to be kept.
# Cheap proxy for MMR within the episode-grouping step.
SUPPORTING_CHUNK_DIVERSITY = 0.03

# Max chunks shown per episode in the results payload.
MAX_CHUNKS_PER_EPISODE = 3

# Top-K candidate chunks pulled from Postgres before episode aggregation.
SEMANTIC_CANDIDATE_POOL = 200

# Whitelist of Postgres text-search configurations we accept. Anything outside
# this set is coerced to 'simple' so the regconfig name is never user-controlled.
_FTS_LANG_WHITELIST = frozenset(
    {
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
    }
)


def _safe_lang(language: str) -> str:
    return language if language in _FTS_LANG_WHITELIST else "simple"


def _vector_literal(values: list[float]) -> str:
    # pgvector accepts text input of the form '[v1,v2,...]' which we cast with
    # ::vector inside the SQL. Bound as a normal text parameter — never
    # interpolated into the SQL string.
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


async def _get_distance_threshold(session: AsyncSession) -> float:
    setting = await session.get(Setting, THRESHOLD_KEY)
    if not setting or not setting.value:
        return DEFAULT_DISTANCE_THRESHOLD
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        logger.warning(
            "Invalid semantic_distance_threshold %r, falling back to %.2f",
            setting.value,
            DEFAULT_DISTANCE_THRESHOLD,
        )
        return DEFAULT_DISTANCE_THRESHOLD


async def _get_embedding_model(session: AsyncSession) -> str:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    return setting.value if setting and setting.value else DEFAULT_EMBEDDING_MODEL


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

    conditions = [
        "to_tsvector(CAST(:lang AS regconfig), ft.full_text) @@ phraseto_tsquery(CAST(:lang AS regconfig), :query)"
    ]
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
               ts_headline(CAST(:lang AS regconfig), ft.full_text,
                           phraseto_tsquery(CAST(:lang AS regconfig), :query),
                           'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20') AS snippet
        FROM transcripts ft
        JOIN episodes e ON e.id = ft.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY ts_rank(to_tsvector(CAST(:lang AS regconfig), ft.full_text),
                         phraseto_tsquery(CAST(:lang AS regconfig), :query)) DESC
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
) -> dict:
    """Semantic episode search.

    Returns a dict (not a list) so the caller can surface the threshold and
    model used for the query — useful for empty-state UX ('no results above
    threshold X') and for debugging cross-model drift.

    Shape::

        {
            "results": [
                {
                    "episode_id": "...",
                    "episode_title": "...",
                    ...,
                    "score": 0.78,                   # 1 - best_distance
                    "snippet": "best chunk text",    # legacy/back-compat
                    "chunk_index": 12,                # legacy/back-compat
                    "chunks": [
                        {"text": "...", "chunk_index": 12,
                         "distance": 0.22, "score": 0.78,
                         "start_time": 145.3, "end_time": 192.7},
                        ...
                    ],
                    "type": "semantic",
                },
                ...
            ],
            "threshold": 0.40,
            "model": "openai/text-embedding-3-large",
            "candidate_count": 187,
        }
    """
    threshold = await _get_distance_threshold(session)
    model = await _get_embedding_model(session)
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        query_embedding = await client.embed(model, query)

    qvec = _vector_literal(query_embedding)

    conditions = [
        "chunk.embedding <=> (:qvec)::vector <= :threshold",
        "chunk.embedding_model = :model",
    ]
    params: dict = {
        "qvec": qvec,
        "threshold": threshold,
        "model": model,
        "candidate_pool": SEMANTIC_CANDIDATE_POOL,
    }
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
        SELECT chunk.text, chunk.chunk_index, chunk.start_time, chunk.end_time,
               chunk.embedding <=> (:qvec)::vector AS distance,
               e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url, e.media_type
        FROM transcript_chunks chunk
        JOIN transcripts t ON t.id = chunk.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT :candidate_pool
    """)

    result = await session.execute(sql, params)
    rows = result.fetchall()

    # Episode aggregation: best chunk + up to MAX_CHUNKS_PER_EPISODE-1
    # supporting chunks with diversity floor.
    by_episode: dict[str, dict] = {}
    for r in rows:
        eid = str(r.episode_id)
        chunk_payload = {
            "text": r.text,
            "chunk_index": r.chunk_index,
            "distance": float(r.distance),
            "score": float(1.0 - r.distance),
            "start_time": float(r.start_time) if r.start_time is not None else None,
            "end_time": float(r.end_time) if r.end_time is not None else None,
        }
        agg = by_episode.get(eid)
        if agg is None:
            by_episode[eid] = {
                "episode_id": eid,
                "episode_title": r.episode_title,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "podcast_title": r.podcast_title,
                "cover_url": r.cover_url,
                "media_type": r.media_type,
                "best_distance": chunk_payload["distance"],
                "chunks": [chunk_payload],
            }
            continue

        if len(agg["chunks"]) >= MAX_CHUNKS_PER_EPISODE:
            continue

        if chunk_payload["distance"] - agg["best_distance"] >= SUPPORTING_CHUNK_DIVERSITY:
            agg["chunks"].append(chunk_payload)

    aggregated = sorted(by_episode.values(), key=lambda e: e["best_distance"])
    aggregated = aggregated[:limit]

    results: list[dict] = []
    for agg in aggregated:
        best = agg["chunks"][0]
        results.append(
            {
                "episode_id": agg["episode_id"],
                "episode_title": agg["episode_title"],
                "published_at": agg["published_at"],
                "podcast_title": agg["podcast_title"],
                "cover_url": agg["cover_url"],
                "media_type": agg["media_type"],
                "snippet": best["text"],
                "score": best["score"],
                "chunk_index": best["chunk_index"],
                "chunks": agg["chunks"],
                "type": "semantic",
            }
        )

    return {
        "results": results,
        "threshold": threshold,
        "model": model,
        "candidate_count": len(rows),
    }
