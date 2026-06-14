"""Real-DB test for GET /api/episodes pagination (replaces the AST stand-in)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.models.episode import Episode
from app.models.podcast import Podcast


@pytest.mark.asyncio
async def test_episode_list_pagination_orders_and_offsets(client, db_session):
    podcast = Podcast(id=uuid.uuid4(), title="Behind the Bastards")
    db_session.add(podcast)
    await db_session.flush()

    for i, day in enumerate((1, 2, 3), start=1):
        db_session.add(
            Episode(
                id=uuid.uuid4(),
                podcast_id=podcast.id,
                guid=f"ep-{i}",
                title=f"Episode {i}",
                audio_url=f"https://example.com/{i}.mp3",
                published_at=datetime(2024, 1, day, tzinfo=UTC),
                status="new",
            )
        )
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_id={podcast.id}&limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["title"] for e in data] == ["Episode 2", "Episode 1"]


@pytest.mark.asyncio
async def test_episode_list_limit_caps_results(client, db_session):
    podcast = Podcast(id=uuid.uuid4(), title="Capped Podcast")
    db_session.add(podcast)
    await db_session.flush()
    for i in range(5):
        db_session.add(
            Episode(
                id=uuid.uuid4(),
                podcast_id=podcast.id,
                guid=f"cap-{i}",
                title=f"Cap {i}",
                audio_url=f"https://example.com/cap-{i}.mp3",
                published_at=datetime(2024, 2, i + 1, tzinfo=UTC),
                status="new",
            )
        )
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_id={podcast.id}&limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
