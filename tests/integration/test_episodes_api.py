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


@pytest.mark.asyncio
async def test_episode_list_filters_by_podcast_ids_and_returns_title(client, db_session):
    p1 = Podcast(id=uuid.uuid4(), title="Portal A")
    p2 = Podcast(id=uuid.uuid4(), title="Portal B")
    db_session.add_all([p1, p2])
    await db_session.flush()

    e1 = Episode(
        id=uuid.uuid4(),
        podcast_id=p1.id,
        guid="p1-1",
        title="A-1",
        audio_url="https://example.com/a1.mp3",
        published_at=datetime(2024, 3, 2, tzinfo=UTC),
        status="done",
    )
    e2 = Episode(
        id=uuid.uuid4(),
        podcast_id=p2.id,
        guid="p2-1",
        title="B-1",
        audio_url="https://example.com/b1.mp3",
        published_at=datetime(2024, 3, 1, tzinfo=UTC),
        status="done",
    )
    db_session.add_all([e1, e2])
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_ids={p1.id}&status=done")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["id"] for e in data] == [str(e1.id)]
    assert data[0]["podcast_title"] == "Portal A"


@pytest.mark.asyncio
async def test_episode_list_filters_done_status_with_podcast_ids(client, db_session):
    p1 = Podcast(id=uuid.uuid4(), title="Status Portal A")
    p2 = Podcast(id=uuid.uuid4(), title="Status Portal B")
    p3 = Podcast(id=uuid.uuid4(), title="Status Portal C")
    db_session.add_all([p1, p2, p3])
    await db_session.flush()

    done_1 = Episode(
        id=uuid.uuid4(),
        podcast_id=p1.id,
        guid="status-a-done",
        title="A done",
        audio_url="https://example.com/a-done.mp3",
        published_at=datetime(2024, 4, 3, tzinfo=UTC),
        status="done",
    )
    db_session.add(done_1)
    db_session.add(
        Episode(
            id=uuid.uuid4(),
            podcast_id=p1.id,
            guid="status-a-new",
            title="A new",
            audio_url="https://example.com/a-new.mp3",
            published_at=datetime(2024, 4, 2, tzinfo=UTC),
            status="new",
        )
    )
    done_2 = Episode(
        id=uuid.uuid4(),
        podcast_id=p2.id,
        guid="status-b-done",
        title="B done",
        audio_url="https://example.com/b-done.mp3",
        published_at=datetime(2024, 4, 1, tzinfo=UTC),
        status="done",
    )
    db_session.add(done_2)
    db_session.add(
        Episode(
            id=uuid.uuid4(),
            podcast_id=p3.id,
            guid="status-c-done",
            title="C done",
            audio_url="https://example.com/c-done.mp3",
            published_at=datetime(2024, 3, 31, tzinfo=UTC),
            status="done",
        )
    )
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_ids={p1.id},{p2.id}&status=done")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["id"] for e in data] == [str(done_1.id), str(done_2.id)]
    assert [e["podcast_title"] for e in data] == ["Status Portal A", "Status Portal B"]


@pytest.mark.asyncio
async def test_episode_list_singular_podcast_id_keeps_backward_compat_response(client, db_session):
    podcast = Podcast(id=uuid.uuid4(), title="Legacy Podcast")
    db_session.add(podcast)
    await db_session.flush()

    done_episode = Episode(
        id=uuid.uuid4(),
        podcast_id=podcast.id,
        guid="legacy-done",
        title="Legacy done",
        audio_url="https://example.com/legacy-done.mp3",
        published_at=datetime(2024, 5, 2, tzinfo=UTC),
        status="done",
    )
    db_session.add(done_episode)
    db_session.add(
        Episode(
            id=uuid.uuid4(),
            podcast_id=podcast.id,
            guid="legacy-new",
            title="Legacy new",
            audio_url="https://example.com/legacy-new.mp3",
            published_at=datetime(2024, 5, 1, tzinfo=UTC),
            status="new",
        )
    )
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_id={podcast.id}&status=done")
    assert resp.status_code == 200
    data = resp.json()
    assert [e["id"] for e in data] == [str(done_episode.id)]
    assert data[0]["podcast_title"] == "Legacy Podcast"


@pytest.mark.asyncio
async def test_episode_list_rejects_invalid_podcast_ids(client):
    resp = await client.get("/api/episodes?podcast_ids=not-a-uuid")
    assert resp.status_code == 422
    assert "Invalid UUID in podcast_ids" in resp.json().get("detail", "")
