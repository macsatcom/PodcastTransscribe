import numpy as np

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
