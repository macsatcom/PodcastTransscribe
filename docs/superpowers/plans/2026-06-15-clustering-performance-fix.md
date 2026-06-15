# Clustering Performance & Safety Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gør topic-clustering hurtig (sekunder, ikke timer) og ufarlig for web-appen ved at sætte `algorithm="brute"`, flytte CPU-arbejdet til en baggrundstråd, tilføje en concurrency-guard, og gøre refresh-endpointet fire-and-forget.

**Architecture:** `run_clustering()` splittes så den rene CPU-del (`np.stack` + `HDBSCAN.fit_predict` + centroid/representative-udregning) lever i en synkron, testbar funktion `compute_clusters()` der køres via `asyncio.to_thread`. En modul-`asyncio.Lock` forhindrer samtidige kørsler. Endpointet starter en baggrundstask og returnerer straks.

**Tech Stack:** Python, asyncio, scikit-learn HDBSCAN, numpy, FastAPI, SQLAlchemy async, pytest

---

## File Structure and Responsibilities

- **Modify:** `app/services/clustering.py`
  - Ny synkron `compute_clusters(matrix, min_size)` → returnerer `labels` (np.ndarray) ved brug af `HDBSCAN(algorithm="brute", ...)`.
  - `run_clustering()` kalder `await asyncio.to_thread(compute_clusters, ...)`.
  - Modul-`asyncio.Lock` + `is_clustering_running()` + guard i `run_clustering()`.
- **Modify:** `app/routers/api_insights.py`
  - `refresh_clusters()` bliver fire-and-forget med `already_running`-svar.
- **Create:** `tests/integration/test_clustering.py`
  - Tests for brute-algoritme, guard, endpoint-kontrakt, output-smoke.

---

### Task 1: Extract pure-sync `compute_clusters` with `algorithm="brute"`

**Files:**
- Modify: `app/services/clustering.py`
- Test: `tests/integration/test_clustering.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_clustering.py`:

```python
"""Tests for topic clustering performance/safety fix."""

import numpy as np
import pytest

from app.services import clustering


def test_compute_clusters_uses_brute_algorithm(monkeypatch):
    """compute_clusters must construct HDBSCAN with algorithm='brute'.

    Regression guard: algorithm='auto' on high-dim vectors is pathologically
    slow (KD/ball-tree collapse). brute keeps it BLAS-vectorized.
    """
    captured = {}

    real_hdbscan = clustering.HDBSCAN

    class SpyHDBSCAN(real_hdbscan):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(clustering, "HDBSCAN", SpyHDBSCAN)

    rng = np.random.default_rng(0)
    matrix = rng.standard_normal((30, 16)).astype(np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)

    labels = clustering.compute_clusters(matrix, min_size=3)

    assert captured.get("algorithm") == "brute"
    assert isinstance(labels, np.ndarray)
    assert labels.shape == (30,)
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py::test_compute_clusters_uses_brute_algorithm -v
```
Expected: FAIL with `AttributeError: module 'app.services.clustering' has no attribute 'compute_clusters'`.

- [ ] **Step 3: Add `compute_clusters` and switch to brute**

In `app/services/clustering.py`, add this function directly after the constants block (after `LABEL_CONTEXT_CHARS = 2400`):

```python
def compute_clusters(matrix: np.ndarray, min_size: int) -> np.ndarray:
    """Pure-CPU clustering step. Runs HDBSCAN with the brute-force algorithm.

    Isolated as a synchronous function so it can be executed off the asyncio
    event loop via asyncio.to_thread. algorithm='brute' is REQUIRED: 'auto'
    builds a KD/ball-tree that collapses on high-dimensional embeddings
    (3072-dim) and becomes pathologically slow.
    """
    hdbscan = HDBSCAN(min_cluster_size=min_size, metric="euclidean", algorithm="brute", copy=True)
    return hdbscan.fit_predict(matrix)
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py::test_compute_clusters_uses_brute_algorithm -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/clustering.py tests/integration/test_clustering.py
git commit -m "feat(clustering): add brute-force compute_clusters helper"
```

---

### Task 2: Call `compute_clusters` off the event loop in `run_clustering`

**Files:**
- Modify: `app/services/clustering.py`

- [ ] **Step 1: Add asyncio import**

At the top of `app/services/clustering.py`, change:

```python
import logging
import math
import uuid
from collections import defaultdict
```

to:

```python
import asyncio
import logging
import math
import uuid
from collections import defaultdict
```

- [ ] **Step 2: Replace the inline HDBSCAN call with a threaded call**

In `run_clustering()`, find this block:

```python
        matrix = np.stack(vectors)

        # Adaptive min_cluster_size — sqrt(N)/4 floored at ABSOLUTE_MIN.
        min_size = max(ABSOLUTE_MIN, int(math.sqrt(len(matrix)) / 4))
        hdbscan = HDBSCAN(min_cluster_size=min_size, metric="euclidean")
        labels = hdbscan.fit_predict(matrix)
```

Replace with:

```python
        matrix = np.stack(vectors)

        # Adaptive min_cluster_size — sqrt(N)/4 floored at ABSOLUTE_MIN.
        min_size = max(ABSOLUTE_MIN, int(math.sqrt(len(matrix)) / 4))
        # Heavy CPU work runs off the event loop so the web app stays responsive.
        labels = await asyncio.to_thread(compute_clusters, matrix, min_size)
```

- [ ] **Step 3: Verify import + module load**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" uv run python -c "import app.services.clustering"
```
Expected: succeeds (only the OPENROUTER_API_KEY warning).

- [ ] **Step 4: Run the brute test again to confirm no regression**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/clustering.py
git commit -m "perf(clustering): run HDBSCAN off the event loop via to_thread"
```

---

### Task 3: Add concurrency guard to `run_clustering`

**Files:**
- Modify: `app/services/clustering.py`
- Test: `tests/integration/test_clustering.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_clustering.py`:

```python
@pytest.mark.asyncio
async def test_run_clustering_skips_when_already_running(monkeypatch):
    """A second run_clustering() while the lock is held must skip immediately
    without touching the database / compute."""
    called = {"compute": False}

    def fake_compute(matrix, min_size):
        called["compute"] = True
        import numpy as np
        return np.full(len(matrix), -1)

    monkeypatch.setattr(clustering, "compute_clusters", fake_compute)

    # Hold the lock to simulate an in-progress run.
    await clustering._clustering_lock.acquire()
    try:
        assert clustering.is_clustering_running() is True
        # Should return promptly without running compute or DB work.
        await clustering.run_clustering()
        assert called["compute"] is False
    finally:
        clustering._clustering_lock.release()

    assert clustering.is_clustering_running() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py::test_run_clustering_skips_when_already_running -v
```
Expected: FAIL with `AttributeError: module 'app.services.clustering' has no attribute '_clustering_lock'`.

- [ ] **Step 3: Add the lock, accessor, and guard**

In `app/services/clustering.py`, add after the constants (after `LABEL_CONTEXT_CHARS = 2400`, before `compute_clusters`):

```python
_clustering_lock = asyncio.Lock()


def is_clustering_running() -> bool:
    """True if a clustering run currently holds the lock."""
    return _clustering_lock.locked()
```

Then wrap the body of `run_clustering()`. Change the function header from:

```python
async def run_clustering():
    async with async_session() as session:
```

to:

```python
async def run_clustering():
    if _clustering_lock.locked():
        logger.info("Clustering: skipped, a run is already in progress")
        return
    async with _clustering_lock:
        await _run_clustering_locked()


async def _run_clustering_locked():
    async with async_session() as session:
```

Note: the existing body (everything currently under `async with async_session() as session:`) now lives under `_run_clustering_locked()`. Its indentation is unchanged — only the wrapper above is new.

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py -v
```
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/clustering.py tests/integration/test_clustering.py
git commit -m "fix(clustering): guard against concurrent clustering runs"
```

---

### Task 4: Make the refresh endpoint fire-and-forget

**Files:**
- Modify: `app/routers/api_insights.py`
- Test: `tests/integration/test_clustering.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/integration/test_clustering.py`:

```python
@pytest.mark.asyncio
async def test_refresh_endpoint_is_fire_and_forget(client, monkeypatch):
    """POST /clusters/refresh returns immediately with 'started' and does NOT
    block on the clustering run."""
    import app.routers.api_insights as api_insights

    started = {"ran": False}

    async def fake_run():
        started["ran"] = True

    monkeypatch.setattr(api_insights, "run_clustering", fake_run)

    resp = await client.post("/api/insights/clusters/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}


@pytest.mark.asyncio
async def test_refresh_endpoint_reports_already_running(client, monkeypatch):
    """If a run is in progress, the endpoint returns 'already_running' and does
    not start another."""
    import app.routers.api_insights as api_insights

    monkeypatch.setattr(api_insights, "is_clustering_running", lambda: True)

    calls = {"n": 0}

    async def fake_run():
        calls["n"] += 1

    monkeypatch.setattr(api_insights, "run_clustering", fake_run)

    resp = await client.post("/api/insights/clusters/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"status": "already_running"}
    assert calls["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py::test_refresh_endpoint_is_fire_and_forget tests/integration/test_clustering.py::test_refresh_endpoint_reports_already_running -v
```
Expected: FAIL — current endpoint returns `{"status": "clustering started"}` and `is_clustering_running` is not imported in the router.

- [ ] **Step 3: Update the import and endpoint**

In `app/routers/api_insights.py`, change the import line:

```python
from app.services.clustering import run_clustering
```

to:

```python
from app.services.clustering import is_clustering_running, run_clustering
```

Then replace the endpoint:

```python
@router.post("/clusters/refresh")
async def refresh_clusters():
    await run_clustering()
    return {"status": "clustering started"}
```

with:

```python
@router.post("/clusters/refresh")
async def refresh_clusters():
    if is_clustering_running():
        return {"status": "already_running"}
    asyncio.create_task(run_clustering())
    return {"status": "started"}
```

And add the asyncio import at the top of `app/routers/api_insights.py`. Change:

```python
from uuid import UUID
```

to:

```python
import asyncio
from uuid import UUID
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py -v
```
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add app/routers/api_insights.py tests/integration/test_clustering.py
git commit -m "fix(insights): make clusters/refresh fire-and-forget"
```

---

### Task 5: Output smoke test (refactor safety)

**Files:**
- Test: `tests/integration/test_clustering.py`

- [ ] **Step 1: Write the test**

Append to `tests/integration/test_clustering.py`:

```python
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.setting import Setting
from app.models.topic import EpisodeTopic, TopicCluster
from app.models.transcript import Transcript, TranscriptChunk
from app.services.embedder import DEFAULT_EMBEDDING_MODEL


@pytest.mark.asyncio
async def test_run_clustering_persists_topics(db_session, monkeypatch):
    """End-to-end smoke: run_clustering on a small synthetic dataset produces
    at least one TopicCluster and EpisodeTopic rows. Guards the refactor's
    persistence path."""

    # Avoid external OpenRouter call for labels.
    async def fake_label(session, representatives):
        return "Test Topic"

    monkeypatch.setattr(clustering, "_generate_label", fake_label)

    # Ensure embedding_model setting matches the chunks we insert.
    db_session.add(Setting(key="embedding_model", value=DEFAULT_EMBEDDING_MODEL))

    podcast = Podcast(id=uuid.uuid4(), title="Cluster Podcast")
    db_session.add(podcast)
    await db_session.flush()

    episode = Episode(
        id=uuid.uuid4(),
        podcast_id=podcast.id,
        guid="cl-1",
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

    # Two tight clusters in 3072-dim space (column is Vector(3072)) so HDBSCAN
    # finds >=1 cluster. Each cluster sits on a distinct one-hot axis + noise.
    import numpy as np

    DIM = 3072
    rng = np.random.default_rng(1)
    base_a = np.zeros(DIM, dtype=np.float32)
    base_a[0] = 1.0
    base_b = np.zeros(DIM, dtype=np.float32)
    base_b[1] = 1.0
    chunk_index = 0
    for base in (base_a, base_b):
        for _ in range(8):
            vec = base + rng.normal(0, 0.01, size=DIM).astype(np.float32)
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

    await clustering.run_clustering()

    topics = (await db_session.execute(select(TopicCluster).where(TopicCluster.source == "auto"))).scalars().all()
    assert len(topics) >= 1
    ep_topics = (await db_session.execute(select(EpisodeTopic))).scalars().all()
    assert len(ep_topics) >= 1
```

- [ ] **Step 2: Run test**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_clustering.py::test_run_clustering_persists_topics -v
```
Expected: PASS. The synthetic vectors are 3072-dim to satisfy the `Vector(3072)` column.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_clustering.py
git commit -m "test(clustering): smoke test that run_clustering persists topics"
```

---

### Task 6: Full verification and push

**Files:**
- Verify only

- [ ] **Step 1: Run full suite**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest -q
```
Expected: all tests pass.

- [ ] **Step 2: Lint the changed Python files**

Run:
```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" uv run ruff check app/services/clustering.py app/routers/api_insights.py tests/integration/test_clustering.py
```
Expected: no errors.

- [ ] **Step 3: Push**

```bash
git push origin master
```

---

## Self-Review Checklist

- **Spec coverage:**
  - `algorithm="brute"` → Task 1
  - Off-loop compute → Task 2
  - Concurrency guard → Task 3
  - Fire-and-forget endpoint + `already_running` → Task 4
  - Output unchanged (smoke) → Task 5
  - Nightly job untouched → no change to `main.py`; `daily_clustering` calls the same guarded `run_clustering()`
- **Placeholder scan:** none.
- **Type consistency:** `compute_clusters(matrix, min_size)` defined in Task 1, called identically in Task 2; `is_clustering_running()` defined in Task 3, imported/used in Task 4; `_clustering_lock` defined in Task 3, referenced in Task 3 test.

## Pgvector dimension note

`TranscriptChunk.embedding` is `Vector(3072)`. The unit tests in Tasks 1 and 3 call `compute_clusters` with small in-memory matrices (not persisted), so dimension is irrelevant there. Only Task 5 persists chunks; if the column enforces 3072 dims at insert, use 3072-dim synthetic vectors as noted in Task 5 Step 2.
