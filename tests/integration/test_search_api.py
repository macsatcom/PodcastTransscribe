"""Integration tests for GET /api/search (FTS + semantic).

The database, pgvector, and the real searcher logic all execute for real;
only the OpenRouter embed() HTTP boundary is mocked.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.setting import Setting
from app.models.transcript import Transcript, TranscriptChunk

EMBED_DIM = 3072


async def _seed_ready_episode(db_session, *, text_body: str, embedding=None):
    podcast = Podcast(id=uuid.uuid4(), title="Seed Podcast")
    db_session.add(podcast)
    await db_session.flush()

    episode = Episode(
        id=uuid.uuid4(),
        podcast_id=podcast.id,
        guid=f"seed-{uuid.uuid4()}",
        title="Seed Episode",
        audio_url="https://example.com/seed.mp3",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        status="ready",
        media_type="podcast",
    )
    db_session.add(episode)
    await db_session.flush()

    transcript = Transcript(
        id=uuid.uuid4(),
        episode_id=episode.id,
        full_text=text_body,
        detected_language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    if embedding is not None:
        db_session.add(
            TranscriptChunk(
                id=uuid.uuid4(),
                transcript_id=transcript.id,
                chunk_index=0,
                text=text_body,
                embedding=embedding,
                embedding_model="openai/text-embedding-3-large",
                embedding_dim=EMBED_DIM,
            )
        )
        await db_session.flush()

    return episode


@pytest.mark.asyncio
async def test_fts_search_finds_seeded_transcript(client, db_session):
    await _seed_ready_episode(db_session, text_body="the quick brown fox jumps over the lazy dog")

    resp = await client.get("/api/search?q=brown&mode=fts&language=simple")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any("Seed Episode" == r.get("episode_title") or "title" in r for r in data["results"]) or data["results"]


@pytest.mark.asyncio
async def test_semantic_search_finds_seeded_chunk(client, db_session):
    vector = [0.1] * EMBED_DIM
    db_session.add(Setting(key="openrouter_api_key", value="test-key"))
    await db_session.flush()
    await _seed_ready_episode(db_session, text_body="a discussion about coffee", embedding=vector)

    with patch("app.services.searcher.OpenRouterClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        instance.embed = AsyncMock(return_value=vector)

        resp = await client.get("/api/search?q=coffee&mode=semantic")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
