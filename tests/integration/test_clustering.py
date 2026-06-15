import numpy as np
import pytest

import app.services.clustering as clustering


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
