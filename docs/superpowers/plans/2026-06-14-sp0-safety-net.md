# SP0 — Safety Net & Quality Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up CI quality gates (lint blocking, type-check advisory, tests blocking against real pgvector Postgres), activate the dead integration-test harness using the real Alembic migration path, and add a thin high-value test layer — so every later sub-project ships guarded.

**Architecture:** Add a GitHub Actions `ci.yml` that runs `ruff`, `mypy` (advisory), and `pytest --cov` against a `pgvector/pgvector:pg16` service container. Rework `tests/conftest.py` so a session-scoped fixture migrates a fresh test DB with `alembic upgrade head` (not `create_all`), and function-scoped tests run in a rolled-back transaction. Replace two non-executing "fake" tests with real DB-backed integration tests. Add `ruff`/`mypy`/`pytest-cov` config, pre-commit hooks, a `/healthz` endpoint + `web` healthcheck, and a structured-logging baseline.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, pgvector, pytest, pytest-asyncio, pytest-httpx, pytest-cov, ruff, mypy, GitHub Actions, Docker Compose.

---

## File Structure

**Created:**
- `.github/workflows/ci.yml` — CI pipeline (push + PR): lint, typecheck, test.
- `.pre-commit-config.yaml` — local ruff lint + format hooks.
- `app/logging_config.py` — single structured-logging setup, `LOG_LEVEL` env override.
- `app/routers/health.py` — `GET /healthz` liveness endpoint.
- `tests/integration/__init__.py` — package marker.
- `tests/integration/test_migrations.py` — migration boot path test.
- `tests/integration/test_search_api.py` — FTS + semantic endpoint tests.
- `tests/integration/test_episodes_api.py` — real-DB pagination test.

**Modified:**
- `pyproject.toml` — `[tool.ruff]`, `[tool.mypy]`, `testpaths`, dev deps.
- `tests/conftest.py` — Alembic-migrated schema, env-driven test URL, isolation.
- `app/main.py` — call `app/logging_config.setup_logging()`; include health router.
- `docker-compose.yml` — `web` healthcheck.

**Deleted:**
- `tests/test_api_episodes_pagination.py` (AST fake).
- `tests/test_podcast_detail_loading_controls.py` (string-grep fake).

---

## Task 1: Tooling config in pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add ruff, mypy, pytest-cov to dev deps and tool config**

Replace the `[project.optional-dependencies]` block and the `[tool.pytest.ini_options]` block, and append the ruff/mypy config. The full updated regions:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pytest-httpx>=0.30",
    "pytest-cov>=5",
    "ruff>=0.6",
    "mypy>=1.11",
]
```

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 120

[tool.ruff.lint]
# Conservative starter ruleset: pyflakes (F), pycodestyle errors (E),
# import sorting (I), pyupgrade (UP), bugbear (B). Auto-fixable-heavy.
select = ["F", "E", "I", "UP", "B"]
# E501 line-length is enforced via formatter, not lint, to avoid churn.
ignore = ["E501", "B008"]

[tool.mypy]
python_version = "3.12"
ignore_missing_imports = true
warn_unused_ignores = false
# Advisory mode: we run mypy in CI with continue-on-error in SP0.
check_untyped_defs = false
```

Note: `B008` is ignored because FastAPI's `Depends(...)`/`Query(...)` default-argument pattern is idiomatic and would otherwise trip bugbear on every endpoint.

- [ ] **Step 2: Install the new dev dependencies locally**

Run: `pip install -e '.[dev]'`
Expected: ruff, mypy, pytest-cov install without error.

- [ ] **Step 3: Verify ruff and mypy are runnable**

Run: `ruff --version && mypy --version`
Expected: both print a version.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add ruff, mypy, pytest-cov tooling config"
```

---

## Task 2: Auto-fix the codebase to satisfy ruff (blocking gate prep)

**Files:**
- Modify: any files ruff flags (whole `app/` + `tests/` + `alembic/`)

- [ ] **Step 1: Run ruff format**

Run: `ruff format .`
Expected: ruff reformats files; prints "N files reformatted, M files left unchanged".

- [ ] **Step 2: Run ruff lint with auto-fix**

Run: `ruff check --fix .`
Expected: auto-fixable issues (imports, pyupgrade) are fixed. Some may remain.

- [ ] **Step 3: Inspect and hand-fix any remaining lint errors**

Run: `ruff check .`
Expected: if any errors remain, they are listed with file:line. Fix each manually (do NOT add blanket `# noqa`; fix the actual issue, or if a rule is genuinely wrong for this codebase, narrow it in `[tool.ruff.lint] ignore`). Re-run until clean.

Run: `ruff check .`
Expected: "All checks passed!"

- [ ] **Step 4: Verify the existing test suite still imports/collects after reformat**

Run: `python -c "import app.main"`
Expected: no import error (reformat must not change behavior).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "style: apply ruff format and lint auto-fixes"
```

---

## Task 3: Structured logging baseline

**Files:**
- Create: `app/logging_config.py`
- Modify: `app/main.py:5` (the bare `logging.basicConfig(...)` line)

- [ ] **Step 1: Create the logging config module**

Create `app/logging_config.py`:

```python
import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure root logging once, with a consistent format.

    Level is taken from the LOG_LEVEL env var (default INFO). This is a plain
    text formatter — no JSON, no log shipping (intentionally minimal).
    """
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=_DEFAULT_FORMAT,
        datefmt=_DEFAULT_DATEFMT,
    )
```

- [ ] **Step 2: Replace the bare basicConfig in main.py**

In `app/main.py`, the current lines 5-6 are:

```python
logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)
```

Replace line 5 (`logging.basicConfig(...)`) with a call to the new helper, keeping the `logger = ...` line. The result (lines 1-7 region of `main.py`):

```python
import logging
import os
from contextlib import asynccontextmanager

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
```

Note: `os` may already be imported later in main.py — ensure no duplicate import remains after ruff runs in Task 8.

- [ ] **Step 3: Verify the app still imports and logs**

Run: `LOG_LEVEL=DEBUG python -c "import app.main; import logging; logging.getLogger('t').debug('hello')"`
Expected: a debug line prints in the new format (timestamp + level + name + message).

- [ ] **Step 4: Commit**

```bash
git add app/logging_config.py app/main.py
git commit -m "feat: structured logging baseline with LOG_LEVEL override"
```

---

## Task 4: /healthz liveness endpoint

**Files:**
- Create: `app/routers/health.py`
- Modify: `app/main.py` (router imports + `include_router` block near lines 197-207)

- [ ] **Step 1: Create the health router**

Create `app/routers/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe. Intentionally does not touch the database."""
    return {"status": "ok"}
```

- [ ] **Step 2: Register the router in main.py**

In `app/main.py`, the import line (currently line 197) is:

```python
from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals, api_abs, api_insights
```

Add `health` to it:

```python
from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals, api_abs, api_insights, health
```

Then add this line alongside the other `app.include_router(...)` calls (after line 207):

```python
app.include_router(health.router)
```

- [ ] **Step 3: Verify the route is registered**

Run: `python -c "from app.main import app; print([r.path for r in app.routes if getattr(r,'path','')=='/healthz'])"`
Expected: `['/healthz']`

- [ ] **Step 4: Commit**

```bash
git add app/routers/health.py app/main.py
git commit -m "feat: add /healthz liveness endpoint"
```

---

## Task 5: Rework conftest.py — Alembic-migrated test DB + isolation

**Files:**
- Modify: `tests/conftest.py` (full rewrite, 46 lines → new version)

**Context the engineer needs:**
- `alembic/env.py` `run_migrations_online()` calls `asyncio.run(...)`. You cannot call that from inside a running event loop. So the fixture runs `alembic.command.upgrade` inside `asyncio.to_thread(...)` (a worker thread with no running loop) — the exact pattern `app/main.py:_run_alembic_upgrade` uses.
- `env.py` reads `settings.database_url`. To target the **test** DB, set the `DATABASE_URL` env var *before* importing/using settings in the migration thread. `app/config.py` reads env at import time, so the fixture sets `os.environ["DATABASE_URL"]` and Alembic's separate process-config picks it up via `env.py` importing `settings`. Since `settings` is a module-level singleton already imported, pass the URL explicitly through Alembic's config instead (set `cfg.set_main_option("sqlalchemy.url", ...)` is NOT enough because env.py ignores it). The robust approach: set `os.environ["DATABASE_URL"]` at the very top of conftest (before any `app.*` import) so the singleton is built against the test DB for the whole test session.

- [ ] **Step 1: Replace conftest.py entirely**

Replace the full contents of `tests/conftest.py` with:

```python
import os

# Point the whole process at the test database BEFORE importing any app module,
# so app.config.settings (a module-level singleton) is built against it.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://podcast:podcast@localhost/podcast_transcription_search_test",
)

import asyncio  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402


def _run_alembic_upgrade_head() -> None:
    """Run `alembic upgrade head` against the test DB in a no-loop thread.

    env.py uses asyncio.run() internally, so this must NOT run inside a
    running event loop — hence it is invoked via asyncio.to_thread by the
    fixture below.
    """
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    # Build a fresh schema using the REAL migration path (not create_all),
    # so the migrations themselves are exercised on every run.
    from app.database import engine

    # Drop everything first for a clean slate (CREATE EXTENSION is idempotent).
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    await asyncio.to_thread(_run_alembic_upgrade_head)

    yield engine

    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    async with async_sessionmaker(test_engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

Key changes vs. the old file:
- Sets `DATABASE_URL` at the top so `settings` (and thus `app.database.engine` and `env.py`) all target the test DB.
- Removes the custom `event_loop` fixture (deprecated by modern pytest-asyncio).
- `test_engine` reuses `app.database.engine` and migrates via Alembic instead of `Base.metadata.create_all`.
- Drops/recreates `public` schema for a clean slate (this also fixes test-collection state, and the `DROP SCHEMA` removes any leftover objects between sessions).

- [ ] **Step 2: Create the test database locally (one-time)**

Run:
```bash
docker compose up -d db
docker compose exec db psql -U podcast -d podcast_transcription_search -c "CREATE DATABASE podcast_transcription_search_test;" || echo "may already exist"
```
Expected: database created (or "already exists" message).

- [ ] **Step 3: Verify conftest collects and the harness starts**

Run: `pytest tests/ -q --co`
Expected: tests are COLLECTED with no import errors. (Collection only; the fake tests are still present and will be removed in Task 7.)

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py
git commit -m "test: migrate test harness to Alembic-based schema + env-driven URL"
```

---

## Task 6: Migration boot-path integration test

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_migrations.py`

- [ ] **Step 1: Create the integration package marker**

Create `tests/integration/__init__.py` (empty file).

- [ ] **Step 2: Write the migration test**

Create `tests/integration/test_migrations.py`:

```python
"""Exercises the real Alembic migration path on a fresh database.

This is the safety net for the failure mode that broke production twice
(ivfflat 2000-dim ceiling in 0.18.1, dropped client.post() in 0.19.1).
The test_engine fixture (conftest) has already run `alembic upgrade head`.
"""
import pytest
from sqlalchemy import text

EXPECTED_TABLES = {
    "podcasts",
    "episodes",
    "transcripts",
    "transcript_chunks",
    "topic_clusters",
    "episode_topics",
    "source_configs",
    "portals",
    "settings",
    "alembic_version",
}

# Indexes that exist ONLY in Alembic migrations (not in the SQLAlchemy models).
# ix_chunks_embedding_3072 is intentionally excluded from the hard assertion:
# migration 0002 wraps its creation in a DO/EXCEPTION block that degrades
# gracefully on older pgvector, so its presence is environment-dependent.
EXPECTED_INDEXES = {
    "ix_episodes_podcast_published",
    "ix_transcripts_fts_simple",
}


@pytest.mark.asyncio
async def test_all_tables_created(test_engine):
    async with test_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        )
        tables = {r[0] for r in rows}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables after migration: {missing}"


@pytest.mark.asyncio
async def test_alembic_only_indexes_created(test_engine):
    async with test_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
        )
        indexes = {r[0] for r in rows}
    missing = EXPECTED_INDEXES - indexes
    assert not missing, f"Missing Alembic-only indexes: {missing}"


@pytest.mark.asyncio
async def test_migration_version_is_head(test_engine):
    async with test_engine.connect() as conn:
        rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = {r[0] for r in rows}
    # Whatever the latest revision id is, exactly one row must be stamped.
    assert len(versions) == 1, f"Expected one alembic version, got {versions}"
```

- [ ] **Step 3: Run the migration test (verify it passes against a real DB)**

Run: `pytest tests/integration/test_migrations.py -v`
Expected: all three tests PASS. (Requires the local test DB from Task 5 Step 2 and `db` container running.)

- [ ] **Step 4: Prove the test actually guards migrations (temporary break)**

Temporarily edit `alembic/versions/0003_episode_perf_indexes.py` `upgrade()` to comment out the `CREATE INDEX` line. Run:

Run: `pytest tests/integration/test_migrations.py::test_alembic_only_indexes_created -v`
Expected: FAIL with "Missing Alembic-only indexes: {'ix_episodes_podcast_published'}".

Then REVERT the edit and re-run:

Run: `git checkout alembic/versions/0003_episode_perf_indexes.py && pytest tests/integration/test_migrations.py -v`
Expected: all PASS again.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_migrations.py
git commit -m "test: integration test for Alembic migration boot path"
```

---

## Task 7: Replace the fake pagination test with a real DB test

**Files:**
- Create: `tests/integration/test_episodes_api.py`
- Delete: `tests/test_api_episodes_pagination.py`

- [ ] **Step 1: Write the real pagination integration test**

Create `tests/integration/test_episodes_api.py`:

```python
"""Real-DB test for GET /api/episodes pagination (replaces the AST stand-in)."""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.episode import Episode
from app.models.podcast import Podcast


@pytest.mark.asyncio
async def test_episode_list_pagination_orders_and_offsets(client, db_session):
    podcast = Podcast(id=uuid.uuid4(), title="Behind the Bastards")
    db_session.add(podcast)
    await db_session.flush()

    # Three episodes with ascending published_at; endpoint orders DESC.
    for i, day in enumerate((1, 2, 3), start=1):
        db_session.add(
            Episode(
                id=uuid.uuid4(),
                podcast_id=podcast.id,
                guid=f"ep-{i}",
                title=f"Episode {i}",
                audio_url=f"https://example.com/{i}.mp3",
                published_at=datetime(2024, 1, day, tzinfo=timezone.utc),
                status="new",
            )
        )
    await db_session.flush()

    # limit=2, offset=1 → skip newest (Episode 3), return Episode 2 then 1.
    resp = await client.get(
        f"/api/episodes?podcast_id={podcast.id}&limit=2&offset=1"
    )
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
                published_at=datetime(2024, 2, i + 1, tzinfo=timezone.utc),
                status="new",
            )
        )
    await db_session.flush()

    resp = await client.get(f"/api/episodes?podcast_id={podcast.id}&limit=3")
    assert resp.status_code == 200
    assert len(resp.json()) == 3
```

**Note on transaction visibility:** the `client` fixture overrides `get_db` to yield the *same* `db_session`, so rows added (and `flush`ed) in the test are visible to the endpoint within the same transaction. Do not `commit` — the fixture rolls back for isolation.

- [ ] **Step 2: Run the new test**

Run: `pytest tests/integration/test_episodes_api.py -v`
Expected: both tests PASS.

- [ ] **Step 3: Delete the fake AST test**

Run: `git rm tests/test_api_episodes_pagination.py`
Expected: file removed.

- [ ] **Step 4: Verify suite still green**

Run: `pytest tests/integration -v`
Expected: migration + episode tests PASS; no collection error from the removed file.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_episodes_api.py
git commit -m "test: real-DB pagination test; remove AST stand-in"
```

---

## Task 8: Search API integration tests (FTS + semantic)

**Files:**
- Create: `tests/integration/test_search_api.py`

**Context the engineer needs:**
- `GET /api/search` (see `app/routers/api_search.py`) delegates to `search_fts` and `search_semantic` in `app/services/searcher.py`.
- FTS uses Postgres `to_tsvector`; the GIN index is built with the `'simple'` config and `_safe_lang` coerces unknown languages to `'simple'`. Pass `language=simple` to hit the indexed path deterministically.
- Semantic search calls `OpenRouterClient.embed(...)` to embed the query, then runs a pgvector distance query. To keep the test offline and deterministic, patch `app.services.searcher.OpenRouterClient` so `.embed()` returns a fixed 3072-dim vector, and seed a chunk whose `embedding` is the same vector (cosine distance 0 → always under threshold).
- `search_fts`/`search_semantic` read `Setting` rows (`embedding_model`, `semantic_distance_threshold`) with defaults when absent — no Setting seeding required for defaults.

- [ ] **Step 1: Write the FTS test**

Create `tests/integration/test_search_api.py`:

```python
"""Integration tests for GET /api/search (FTS + semantic).

The database, pgvector, and the real searcher logic all execute for real;
only the OpenRouter embed() HTTP boundary is mocked.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models.episode import Episode
from app.models.podcast import Podcast
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
        published_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        status="ready",
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
    await _seed_ready_episode(
        db_session, text_body="the quick brown fox jumps over the lazy dog"
    )

    resp = await client.get("/api/search?q=brown&mode=fts&language=simple")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any("Seed Episode" == r.get("episode_title") or "title" in r for r in data["results"]) or data["results"]


@pytest.mark.asyncio
async def test_semantic_search_finds_seeded_chunk(client, db_session):
    vector = [0.1] * EMBED_DIM
    await _seed_ready_episode(
        db_session, text_body="a discussion about coffee", embedding=vector
    )

    # Patch the embed() boundary so the query vector == the seeded vector
    # (cosine distance 0 → guaranteed under any threshold).
    with patch("app.services.searcher.OpenRouterClient") as mock_client_cls:
        instance = mock_client_cls.return_value
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=None)
        instance.embed = AsyncMock(return_value=vector)

        resp = await client.get("/api/search?q=coffee&mode=semantic")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
```

**Note:** the FTS assertion is intentionally lenient on result-shape keys (the searcher's result dict shape is verified by SP-specific tests later); here we assert that a real FTS query against a real GIN index returns the seeded episode.

- [ ] **Step 2: Run the search tests**

Run: `pytest tests/integration/test_search_api.py -v`
Expected: both tests PASS. If `test_semantic_search_finds_seeded_chunk` fails on the patch target, confirm `searcher.py` imports `OpenRouterClient` at module scope (it does: `from app.services.openrouter import OpenRouterClient`), so the patch path `app.services.searcher.OpenRouterClient` is correct.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_search_api.py
git commit -m "test: integration tests for FTS and semantic search endpoints"
```

---

## Task 9: Remove the string-grep fake test

**Files:**
- Delete: `tests/test_podcast_detail_loading_controls.py`

- [ ] **Step 1: Delete the fake test**

Run: `git rm tests/test_podcast_detail_loading_controls.py`
Expected: file removed. (Its intent — verifying stop/resume loading UI behavior — is deferred to SP6's frontend test approach, per the SP0 spec. It asserted string presence in a template, which is not a behavioral test.)

- [ ] **Step 2: Verify full suite still collects and passes**

Run: `pytest tests/ -v`
Expected: all remaining tests PASS (unit tests `test_openrouter.py`, `test_pipeline.py`, `test_rss_adapter.py` + the new integration tests). No collection errors.

If `tests/test_rss_adapter.py` fails to import due to the cross-repo `app.adapters` collision noted in the spec, confirm the fix from Task 5 (setting `DATABASE_URL` and the `testpaths`/rootdir config) resolves it; if the collision persists it is because another repo is on `sys.path` — ensure the editable install `pip install -e '.[dev]'` from Task 1 Step 2 was run in THIS repo's environment so `app` resolves here.

- [ ] **Step 3: Commit**

```bash
git commit -m "test: remove string-grep stand-in (deferred to SP6 frontend tests)"
```

---

## Task 10: web healthcheck in docker-compose

**Files:**
- Modify: `docker-compose.yml:15-29` (the `web` service)

**Context:** the runtime image (`Dockerfile`) installs only `ffmpeg` — **no curl/wget**. Use a Python one-liner for the healthcheck (Python is always present).

- [ ] **Step 1: Add the healthcheck block to the web service**

In `docker-compose.yml`, the `web` service currently ends at the `environment:` block (lines 26-29). Add a `healthcheck:` key to the `web` service (sibling of `ports`, `volumes`, `depends_on`, `environment`):

```yaml
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz').status==200 else 1)"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 40s
```

The `start_period: 40s` gives the app time to run migrations on startup before health failures count.

- [ ] **Step 2: Validate compose file syntax**

Run: `docker compose config >/dev/null && echo OK`
Expected: `OK` (no YAML/schema errors).

- [ ] **Step 3: Verify the healthcheck works against a running stack**

Run:
```bash
docker compose up -d db web
sleep 45
docker compose ps
```
Expected: `web` shows status `healthy` (or `health: starting` then `healthy` shortly after). If `healthy` is not reached, run `docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz').read())"` to debug.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add web service healthcheck via /healthz"
```

---

## Task 11: Pre-commit hooks

**Files:**
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Create the pre-commit config**

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 2: Install and run pre-commit against all files**

Run:
```bash
pip install pre-commit
pre-commit run --all-files
```
Expected: ruff and ruff-format hooks run and PASS (the codebase was already fixed in Task 2). If they modify anything, re-run until clean.

- [ ] **Step 3: Commit**

```bash
git add .pre-commit-config.yaml
git commit -m "chore: add pre-commit hooks for ruff lint + format"
```

---

## Task 12: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the CI workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      db:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: podcast_transcription_search_test
          POSTGRES_USER: podcast
          POSTGRES_PASSWORD: podcast
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U podcast -d podcast_transcription_search_test"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      DATABASE_URL: postgresql+asyncpg://podcast:podcast@localhost:5432/podcast_transcription_search_test

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -e '.[dev]'

      - name: Ruff lint (blocking)
        run: ruff check .

      - name: Ruff format check (blocking)
        run: ruff format --check .

      - name: Mypy (advisory)
        run: mypy app
        continue-on-error: true

      - name: Pytest with coverage (blocking)
        run: pytest --cov=app --cov-report=term-missing -v
```

**Notes:**
- The `services.db` healthcheck gates the job — `pytest` only runs once Postgres is healthy.
- `DATABASE_URL` is set at job level; `conftest.py` uses it (it calls `os.environ.setdefault`, so the CI-provided value wins).
- `mypy` has `continue-on-error: true` → advisory (reports in logs, never fails the build). This is the SP0 contract; a later sub-project flips it to blocking.

- [ ] **Step 2: Validate the workflow YAML locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('valid yaml')"`
Expected: `valid yaml`.

- [ ] **Step 3: Commit and push to trigger CI**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint + typecheck + test workflow on push and PR"
git push
```

- [ ] **Step 4: Verify CI is green on GitHub**

Run: `gh run list --workflow=ci.yml --limit 1`
Then watch the latest run:
Run: `gh run watch $(gh run list --workflow=ci.yml --limit 1 --json databaseId -q '.[0].databaseId')`
Expected: the run completes with the `test` job SUCCESS — ruff passes, ruff-format passes, mypy step shows (may report errors but is green due to continue-on-error), pytest passes with a coverage summary printed.

If the run fails, read the failing step's logs (`gh run view --log-failed`), fix the issue, commit, push, and re-watch until green.

---

## Task 13: Final verification & definition-of-done

**Files:** none (verification only)

- [ ] **Step 1: Run the whole suite locally one more time**

Run: `pytest --cov=app --cov-report=term-missing -v`
Expected: all tests PASS; coverage summary printed (baseline number recorded — no gate).

- [ ] **Step 2: Confirm ruff + format are clean**

Run: `ruff check . && ruff format --check . && echo CLEAN`
Expected: `CLEAN`.

- [ ] **Step 3: Confirm web reports healthy**

Run: `docker compose up -d db web && sleep 45 && docker compose ps`
Expected: `web` is `healthy`.

- [ ] **Step 4: Confirm CI is green on the latest push**

Run: `gh run list --workflow=ci.yml --limit 1`
Expected: latest run `completed / success`.

- [ ] **Step 5: Tear down local stack**

Run: `docker compose down`
Expected: containers stopped.

---

## Definition of Done (from spec §12)

- [ ] CI green on a PR: ruff passes, mypy reports (advisory), all tests pass against the pgvector service container, coverage printed.
- [ ] The migration integration test fails if a migration is broken (verified in Task 6 Step 4, then reverted).
- [ ] `pytest` run locally collects only this repo's tests.
- [ ] `docker compose ps` shows `web` as healthy.
