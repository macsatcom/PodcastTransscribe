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
