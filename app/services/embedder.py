"""Chunking + embedding for transcripts.

Chunks are aligned to whisper segment timestamps when available so the search
UI can deep-link into the audio at the moment a hit appears. When segments
are missing (legacy transcripts, transcription provider that didn't return
them), we fall back to word-based chunking with `start_time` / `end_time`
left as `None`.

Targets:
- ~250 words per chunk (down from 500). Smaller chunks give the embedding
  model less surface area to dilute, which materially improves cosine
  similarity for narrow factual queries.
- ~40-word overlap (down from 50, scaled to the smaller chunk size). Keeps
  context across chunk boundaries without too much duplication.
"""

import logging
from dataclasses import dataclass

from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-large"

CHUNK_SIZE = 250
CHUNK_OVERLAP = 40


@dataclass
class TextChunk:
    """One indexable chunk with optional audio-time alignment."""

    text: str
    start_time: float | None = None
    end_time: float | None = None


def _segment_words(seg: dict) -> list[str]:
    return seg.get("text", "").strip().split()


def chunk_segments(
    segments: list[dict] | None,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Build word-aligned chunks from whisper segments.

    Each chunk is a contiguous run of segments accumulating to ~chunk_size
    words. The next chunk starts `overlap` words back from the end of the
    previous one (rounded to segment boundaries — we never split a segment).
    """
    if not segments:
        return []

    seg_words = [_segment_words(seg) for seg in segments]
    n = len(segments)

    chunks: list[TextChunk] = []
    i = 0
    while i < n:
        word_count = 0
        j = i
        while j < n and word_count < chunk_size:
            word_count += len(seg_words[j])
            j += 1

        chunk_segs = segments[i:j]
        text = " ".join(seg.get("text", "").strip() for seg in chunk_segs).strip()
        if text:
            start_time = chunk_segs[0].get("start")
            end_time = chunk_segs[-1].get("end")
            chunks.append(
                TextChunk(
                    text=text,
                    start_time=float(start_time) if start_time is not None else None,
                    end_time=float(end_time) if end_time is not None else None,
                )
            )

        if j >= n:
            break

        # Walk back from j until we've covered `overlap` words. Always step
        # forward at least one segment from `i` to guarantee progress.
        overlap_words = 0
        k = j
        while k > i + 1 and overlap_words < overlap:
            k -= 1
            overlap_words += len(seg_words[k])
        i = k

    return chunks


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    """Word-based fallback chunker (no timestamps).

    Used when whisper segments aren't available — produces TextChunk objects
    with start_time / end_time set to None so the rest of the pipeline can
    handle aligned and unaligned chunks uniformly.
    """
    words = text.split()
    if not words:
        return []

    chunks: list[TextChunk] = []
    start = 0
    n = len(words)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(TextChunk(text=" ".join(words[start:end])))
        if end >= n:
            break
        start = end - overlap

    return chunks


def chunk_transcript(
    full_text: str,
    segments: list[dict] | None,
) -> list[TextChunk]:
    """Pick the best chunker for what's available.

    Prefer segment-aligned chunks (with timestamps); fall back to word-based
    chunking on the joined full_text when segments are missing or empty.
    """
    aligned = chunk_segments(segments)
    if aligned:
        return aligned
    return chunk_text(full_text)


async def _resolve_model(session, override: str | None = None) -> str:
    if override:
        return override
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    return setting.value if setting and setting.value else DEFAULT_EMBEDDING_MODEL


async def embed_chunks(
    session,
    chunks: list[str],
    model: str | None = None,
) -> tuple[str, list[list[float]]]:
    """Embed a list of chunk texts.

    Returns ``(model_used, embeddings)``. The model is read from the
    `embedding_model` Setting unless overridden, and is returned alongside
    the vectors so the caller can persist it on each chunk row — searcher
    filters by `embedding_model` to avoid cross-model space drift.
    """
    resolved_model = await _resolve_model(session, model)
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        embeddings: list[list[float]] = []
        for chunk in chunks:
            embedding = await client.embed(resolved_model, chunk)
            embeddings.append(embedding)
    return resolved_model, embeddings
