"""RAG (retrieval-augmented generation) over podcast transcripts.

Quality controls
----------------
- Chunk-level retrieval (no episode aggregation): RAG needs the raw evidence,
  not best-of-episode summaries.
- Cosine-distance threshold (semantic_distance_threshold setting, default 0.40):
  guarantees retrieved chunks are at least loosely on-topic.
- MMR (Maximal Marginal Relevance, λ=0.7) reduces near-duplicates and forces
  cross-episode diversity.
- Per-episode cap (max 2 chunks/episode) prevents one verbose episode from
  drowning out the rest of the corpus.
- Citation format ``[PodcastName — Episode title, MM:SS]`` includes a
  per-chunk timestamp so the user can verify directly in the player.
- Low-confidence fallback: fewer than ``MIN_CHUNKS_FOR_ANSWER`` chunks above
  threshold → short "not enough evidence" reply with the few snippets we did
  find, rather than hallucinating an answer from thin context.
"""
from __future__ import annotations

import logging
import math

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key
from app.services.searcher import (
    DEFAULT_DISTANCE_THRESHOLD,
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_MODEL_KEY,
    THRESHOLD_KEY,
    _vector_literal,
)

logger = logging.getLogger(__name__)

# Top-K chunks pulled from Postgres before MMR re-ranking.
RAG_CANDIDATE_POOL = 60

# Number of chunks fed to the LLM after MMR.
RAG_FINAL_CHUNKS = 12

# Per-episode cap so one episode can't dominate the context window.
RAG_MAX_CHUNKS_PER_EPISODE = 2

# MMR λ: 1.0 = pure relevance, 0.0 = pure diversity.
RAG_MMR_LAMBDA = 0.7

# If fewer than this many chunks pass the threshold, return the
# low-confidence fallback instead of asking the LLM to fabricate.
MIN_CHUNKS_FOR_ANSWER = 4

RAG_SYSTEM_PROMPT = (
    "You are answering questions about podcast and ebook transcripts. "
    "Answer using ONLY the excerpts below. "
    "Each excerpt has a citation tag like [Podcast — Episode, MM:SS]; "
    "include the relevant tag(s) inline after each claim. "
    "If the excerpts do not contain enough information to answer, say so explicitly. "
    "Do not invent facts, sources, or quotations."
)


def _format_timestamp(seconds: float | None) -> str:
    if seconds is None or (isinstance(seconds, float) and math.isnan(seconds)):
        return ""
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


def _citation(chunk: dict) -> str:
    ts = _format_timestamp(chunk.get("start_time"))
    podcast = chunk.get("podcast_title") or "Unknown podcast"
    episode = chunk.get("episode_title") or "Unknown episode"
    if ts:
        return f"[{podcast} — {episode}, {ts}]"
    return f"[{podcast} — {episode}]"


async def _get_threshold(session: AsyncSession) -> float:
    setting = await session.get(Setting, THRESHOLD_KEY)
    if not setting or not setting.value:
        return DEFAULT_DISTANCE_THRESHOLD
    try:
        return float(setting.value)
    except (TypeError, ValueError):
        return DEFAULT_DISTANCE_THRESHOLD


async def _get_model(session: AsyncSession) -> str:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    return setting.value if setting and setting.value else DEFAULT_EMBEDDING_MODEL


async def _retrieve_candidates(
    session: AsyncSession,
    query_embedding: list[float],
    model: str,
    threshold: float,
    podcast_ids: list[str] | None,
) -> list[dict]:
    qvec = _vector_literal(query_embedding)
    conditions = [
        "chunk.embedding <=> (:qvec)::vector <= :threshold",
        "chunk.embedding_model = :model",
        "e.media_type != 'ebook' OR e.media_type IS NULL",  # include ebooks too if media_type null; primary use is podcasts
    ]
    params: dict = {
        "qvec": qvec,
        "threshold": threshold,
        "model": model,
        "limit": RAG_CANDIDATE_POOL,
    }
    if podcast_ids:
        conditions.append("e.podcast_id = ANY(:podcast_ids)")
        params["podcast_ids"] = podcast_ids

    where_clause = " AND ".join(conditions)
    sql = text(f"""
        SELECT
            chunk.text,
            chunk.chunk_index,
            chunk.start_time,
            chunk.end_time,
            chunk.embedding::text AS embedding_text,
            chunk.embedding <=> (:qvec)::vector AS distance,
            e.id   AS episode_id,
            e.title AS episode_title,
            e.published_at,
            p.id   AS podcast_id,
            p.title AS podcast_title
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

    chunks: list[dict] = []
    for r in rows:
        # embedding text is "[v1,v2,...]"; parse to ndarray
        emb_str = r.embedding_text
        try:
            vec = np.fromstring(emb_str.strip()[1:-1], sep=",", dtype=np.float32)
        except Exception:
            logger.warning("Failed to parse embedding for chunk %s", r.chunk_index)
            continue
        chunks.append({
            "text": r.text,
            "chunk_index": int(r.chunk_index),
            "start_time": float(r.start_time) if r.start_time is not None else None,
            "end_time": float(r.end_time) if r.end_time is not None else None,
            "distance": float(r.distance),
            "embedding": vec,
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_id": str(r.podcast_id),
            "podcast_title": r.podcast_title,
        })
    return chunks


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v


def _mmr_select(
    query_vec: np.ndarray,
    candidates: list[dict],
    k: int,
    lambda_: float,
    per_episode_cap: int,
) -> list[dict]:
    """Greedy MMR re-ranking.

    Maximizes ``λ·rel(d, q) − (1−λ)·max sim(d, d')`` among already-picked.
    Episode cap is enforced by skipping candidates whose episode_id has
    already been picked ``per_episode_cap`` times.
    """
    if not candidates:
        return []

    q = _normalize(query_vec)
    docs = np.stack([_normalize(c["embedding"]) for c in candidates])
    rel = docs @ q  # cosine similarity to query

    selected: list[int] = []
    selected_set: set[int] = set()
    episode_counts: dict[str, int] = {}

    while len(selected) < k and len(selected) < len(candidates):
        best_idx = -1
        best_score = -np.inf
        for i in range(len(candidates)):
            if i in selected_set:
                continue
            ep_id = candidates[i]["episode_id"]
            if episode_counts.get(ep_id, 0) >= per_episode_cap:
                continue
            if not selected:
                redundancy = 0.0
            else:
                sims = docs[selected] @ docs[i]
                redundancy = float(np.max(sims))
            score = lambda_ * float(rel[i]) - (1 - lambda_) * redundancy
            if score > best_score:
                best_score = score
                best_idx = i
        if best_idx < 0:
            break
        selected.append(best_idx)
        selected_set.add(best_idx)
        episode_counts[candidates[best_idx]["episode_id"]] = (
            episode_counts.get(candidates[best_idx]["episode_id"], 0) + 1
        )

    return [candidates[i] for i in selected]


def _build_user_message(question: str, chunks: list[dict]) -> str:
    lines = []
    for chunk in chunks:
        cit = _citation(chunk)
        lines.append(f"{cit}\n{chunk['text']}")
    excerpts = "\n\n---\n\n".join(lines)
    return f"Excerpts:\n\n{excerpts}\n\n---\n\nQuestion: {question}"


def _sources_payload(chunks: list[dict]) -> list[dict]:
    """One source entry per chunk so the UI can render each citation
    individually with a deep-link to the timestamp."""
    return [
        {
            "episode_id": c["episode_id"],
            "episode_title": c["episode_title"],
            "podcast_id": c["podcast_id"],
            "podcast_title": c["podcast_title"],
            "published_at": c["published_at"],
            "start_time": c["start_time"],
            "end_time": c["end_time"],
            "chunk_index": c["chunk_index"],
            "snippet": c["text"],
            "citation": _citation(c),
            "score": float(1.0 - c["distance"]),
        }
        for c in chunks
    ]


async def ask_question(
    session: AsyncSession,
    question: str,
    podcast_ids: list[str] | None = None,
) -> dict:
    threshold = await _get_threshold(session)
    model = await _get_model(session)
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        query_embedding = await client.embed(model, question)

    candidates = await _retrieve_candidates(
        session, query_embedding, model, threshold, podcast_ids,
    )

    if len(candidates) < MIN_CHUNKS_FOR_ANSWER:
        if not candidates:
            return {
                "answer": (
                    "No transcript excerpts cleared the relevance threshold "
                    f"({threshold:.2f}). Try rephrasing the question, broadening "
                    "the podcast scope, or lowering the threshold in Settings."
                ),
                "sources": [],
                "low_confidence": True,
                "threshold": threshold,
                "model": model,
                "candidate_count": 0,
            }
        # We have 1–3 chunks: surface them but don't ask the LLM to invent.
        return {
            "answer": (
                f"Only {len(candidates)} loosely related excerpt(s) "
                "passed the relevance threshold — not enough to answer "
                "confidently. Snippets shown below."
            ),
            "sources": _sources_payload(candidates),
            "low_confidence": True,
            "threshold": threshold,
            "model": model,
            "candidate_count": len(candidates),
        }

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    selected = _mmr_select(
        query_vec=query_vec,
        candidates=candidates,
        k=RAG_FINAL_CHUNKS,
        lambda_=RAG_MMR_LAMBDA,
        per_episode_cap=RAG_MAX_CHUNKS_PER_EPISODE,
    )

    user_message = _build_user_message(question, selected)

    summarization_setting = await session.get(Setting, "summarization_model")
    chat_model = (
        summarization_setting.value if summarization_setting else "openai/gpt-4o-mini"
    )

    async with OpenRouterClient(api_key=api_key) as client:
        result = await client._post("chat/completions", {
            "model": chat_model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        })

    choices = result.get("choices", [])
    answer = (
        choices[0].get("message", {}).get("content", "")
        if choices else "Unable to generate an answer."
    )

    return {
        "answer": answer,
        "sources": _sources_payload(selected),
        "low_confidence": False,
        "threshold": threshold,
        "model": model,
        "candidate_count": len(candidates),
    }
