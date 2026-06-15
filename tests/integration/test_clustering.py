import uuid
from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy import delete, func, select

import app.services.clustering as clustering
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.setting import Setting
from app.models.topic import EpisodeTopic, TopicCluster
from app.models.transcript import Transcript, TranscriptChunk
from app.services.embedder import DEFAULT_EMBEDDING_MODEL


def test_compute_clusters_uses_brute_algorithm(monkeypatch):
    captured_kwargs = {}

    class FakeHDBSCAN:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

        def fit_predict(self, matrix):
            return np.full(matrix.shape[0], -1, dtype=np.int64)

    monkeypatch.setattr(clustering, "HDBSCAN", FakeHDBSCAN)

    matrix = np.array(
        [[0.1, 0.2], [0.2, 0.3], [0.9, 0.1]],
        dtype=np.float32,
    )

    labels = clustering.compute_clusters(matrix, min_size=3)

    assert captured_kwargs["algorithm"] == "brute"
    assert isinstance(labels, np.ndarray)
    assert labels.shape == (matrix.shape[0],)


@pytest.mark.asyncio
async def test_run_clustering_skips_when_already_running(monkeypatch):
    called = {"compute": False}

    def fake_compute(matrix, min_size):
        called["compute"] = True
        return np.full(matrix.shape[0], -1, dtype=np.int64)

    monkeypatch.setattr(clustering, "compute_clusters", fake_compute)

    await clustering._clustering_lock.acquire()
    try:
        assert clustering.is_clustering_running() is True
        await clustering.run_clustering()
        assert called["compute"] is False
    finally:
        clustering._clustering_lock.release()

    assert clustering.is_clustering_running() is False


@pytest.mark.asyncio
async def test_refresh_endpoint_is_fire_and_forget(client, monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import app.routers.api_insights as api_insights

    observed = {"inline_awaited": False}
    scheduled = {"count": 0, "coro": None}

    async def fake_run():
        observed["inline_awaited"] = True
        await asyncio.sleep(0)

    def fake_create_task(coro):
        scheduled["count"] += 1
        scheduled["coro"] = coro
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        return done

    monkeypatch.setattr(api_insights, "run_clustering", fake_run)
    monkeypatch.setattr(api_insights, "asyncio", SimpleNamespace(create_task=fake_create_task))

    response = await client.post("/api/insights/clusters/refresh")

    try:
        assert response.status_code == 200
        assert response.json() == {"status": "started"}
        assert scheduled["count"] == 1
        assert scheduled["coro"] is not None
        assert observed["inline_awaited"] is False
    finally:
        if scheduled["coro"] is not None:
            scheduled["coro"].close()


@pytest.mark.asyncio
async def test_refresh_endpoint_reports_already_running(client, monkeypatch):
    import app.routers.api_insights as api_insights

    monkeypatch.setattr(api_insights, "is_clustering_running", lambda: True)

    calls = {"n": 0}

    async def fake_run():
        calls["n"] += 1

    monkeypatch.setattr(api_insights, "run_clustering", fake_run)

    response = await client.post("/api/insights/clusters/refresh")

    assert response.status_code == 200
    assert response.json() == {"status": "already_running"}
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_run_clustering_persists_topics(db_session, monkeypatch):
    async def fake_generate_label(session, representatives):
        return "Test Topic"

    monkeypatch.setattr(clustering, "_generate_label", fake_generate_label)

    model_setting = await db_session.get(Setting, "embedding_model")
    setting_preexisted = model_setting is not None
    previous_setting_value = model_setting.value if model_setting else None
    if model_setting is None:
        db_session.add(Setting(key="embedding_model", value=DEFAULT_EMBEDDING_MODEL))
    else:
        model_setting.value = DEFAULT_EMBEDDING_MODEL

    podcast = Podcast(id=uuid.uuid4(), title="Cluster Podcast")
    db_session.add(podcast)
    await db_session.flush()

    episode = Episode(
        id=uuid.uuid4(),
        podcast_id=podcast.id,
        guid=f"cl-{uuid.uuid4()}",
        title="Cluster Episode",
        audio_url="https://example.com/cl.mp3",
        published_at=datetime(2024, 1, 1, tzinfo=UTC),
        status="done",
    )
    db_session.add(episode)
    await db_session.flush()

    transcript = Transcript(
        id=uuid.uuid4(),
        episode_id=episode.id,
        full_text="text",
        detected_language="en",
    )
    db_session.add(transcript)
    await db_session.flush()

    dim = 3072
    rng = np.random.default_rng(1)
    base_a = np.zeros(dim, dtype=np.float32)
    base_a[0] = 1.0
    base_b = np.zeros(dim, dtype=np.float32)
    base_b[1] = 1.0

    chunk_index = 0
    for base in (base_a, base_b):
        for _ in range(12):
            vec = base + rng.normal(0.0, 0.01, size=dim).astype(np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            db_session.add(
                TranscriptChunk(
                    id=uuid.uuid4(),
                    transcript_id=transcript.id,
                    chunk_index=chunk_index,
                    text=f"chunk {chunk_index}",
                    embedding=vec.tolist(),
                    embedding_model=DEFAULT_EMBEDDING_MODEL,
                    start_time=float(chunk_index),
                    end_time=float(chunk_index) + 1.0,
                )
            )
            chunk_index += 1

    await db_session.commit()

    baseline_auto_topic_count = await db_session.scalar(
        select(func.count()).select_from(TopicCluster).where(TopicCluster.source == "auto")
    )
    baseline_episode_topic_count = await db_session.scalar(
        select(func.count()).select_from(EpisodeTopic).where(EpisodeTopic.episode_id == episode.id)
    )
    baseline_auto_topic_count = baseline_auto_topic_count or 0
    baseline_episode_topic_count = baseline_episode_topic_count or 0

    created_topic_ids: list[uuid.UUID] = []
    try:
        await clustering.run_clustering()

        auto_topics = (
            await db_session.execute(select(TopicCluster).where(TopicCluster.source == "auto"))
        ).scalars().all()
        created_topic_ids = [topic.id for topic in auto_topics]

        auto_topic_count_after = len(auto_topics)
        episode_topic_count_after = await db_session.scalar(
            select(func.count()).select_from(EpisodeTopic).where(EpisodeTopic.episode_id == episode.id)
        )
        episode_topic_count_after = episode_topic_count_after or 0

        assert auto_topic_count_after > baseline_auto_topic_count
        assert episode_topic_count_after > baseline_episode_topic_count
    finally:
        await db_session.execute(delete(EpisodeTopic).where(EpisodeTopic.episode_id == episode.id))
        if created_topic_ids:
            await db_session.execute(delete(TopicCluster).where(TopicCluster.id.in_(created_topic_ids)))
        await db_session.execute(delete(TranscriptChunk).where(TranscriptChunk.transcript_id == transcript.id))
        await db_session.execute(delete(Transcript).where(Transcript.id == transcript.id))
        await db_session.execute(delete(Episode).where(Episode.id == episode.id))
        await db_session.execute(delete(Podcast).where(Podcast.id == podcast.id))
        if setting_preexisted:
            restored_setting = await db_session.get(Setting, "embedding_model")
            if restored_setting is not None:
                restored_setting.value = previous_setting_value
        else:
            await db_session.execute(delete(Setting).where(Setting.key == "embedding_model"))
        await db_session.commit()
