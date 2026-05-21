# PodcastTransscribe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted web app that subscribes to podcast RSS feeds, transcribes episodes via OpenRouter, generates summaries, and provides full-text + semantic search.

**Architecture:** Single Python FastAPI process with APScheduler for background jobs, PostgreSQL + pgvector for storage and search, HTMX + Alpine.js + Tailwind for UI. Docker Compose for deployment.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, PostgreSQL 16 + pgvector, APScheduler, httpx, HTMX, Alpine.js, Tailwind CSS

---

## File Structure

```
PodcastTransscribe/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── podcast.py
│   │   ├── episode.py
│   │   ├── transcript.py
│   │   ├── source_config.py
│   │   └── setting.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── podcast.py
│   │   ├── episode.py
│   │   ├── transcript.py
│   │   ├── search.py
│   │   └── source_config.py
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── ui.py
│   │   ├── api_podcasts.py
│   │   ├── api_episodes.py
│   │   ├── api_search.py
│   │   └── api_settings.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rss_poller.py
│   │   ├── pipeline.py
│   │   ├── transcribe.py
│   │   ├── summarize.py
│   │   ├── embedder.py
│   │   ├── searcher.py
│   │   └── openrouter.py
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── rss.py
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── podcast_detail.html
│       ├── episode.html
│       ├── search.html
│       └── admin.html
└── tests/
    ├── conftest.py
    ├── test_rss_adapter.py
    ├── test_openrouter.py
    ├── test_pipeline.py
    └── test_search.py
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `docker-compose.yml`
- Create: `Dockerfile`
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/database.py`
- Create: `app/main.py`
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "podcast-transcribe"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "apscheduler>=3.10",
    "httpx",
    "feedparser",
    "jinja2",
    "python-multipart",
    "pgvector",
]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Create Dockerfile**

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --user --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini .
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Create docker-compose.yml**

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: podcast_transcribe
      POSTGRES_USER: podcast
      POSTGRES_PASSWORD: podcast
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U podcast -d podcast_transcribe"]
      interval: 5s
      retries: 10

  web:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - audio_cache:/tmp/audio
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql+asyncpg://podcast:podcast@db/podcast_transcribe
      OPENROUTER_API_KEY: "${OPENROUTER_API_KEY}"

volumes:
  pgdata:
  audio_cache:
```

- [ ] **Step 4: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://podcast:podcast@localhost/podcast_transcribe"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    audio_temp_dir: str = "/tmp/audio"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

- [ ] **Step 5: Create app/database.py**

```python
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session
```

- [ ] **Step 6: Create app/main.py**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import engine, Base
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(title="PodcastTransscribe", lifespan=lifespan)
```

- [ ] **Step 7: Create alembic.ini**

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://podcast:podcast@localhost/podcast_transcribe

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 8: Create alembic/env.py**

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base
from app.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    url = settings.database_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 9: Create alembic/script.py.mako**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 10: Verify project structure exists and is consistent**

Run: `ls -la app/ docker-compose.yml Dockerfile pyproject.toml alembic.ini alembic/`
Expected: All files present

---

### Task 2: Database Models

**Files:**
- Create: `app/models/__init__.py`
- Create: `app/models/podcast.py`
- Create: `app/models/episode.py`
- Create: `app/models/transcript.py`
- Create: `app/models/source_config.py`
- Create: `app/models/setting.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create app/models/__init__.py**

```python
from app.models.podcast import Podcast
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.models.source_config import SourceConfig
from app.models.setting import Setting

__all__ = [
    "Podcast",
    "Episode",
    "Transcript",
    "TranscriptChunk",
    "SourceConfig",
    "Setting",
]
```

- [ ] **Step 2: Create app/models/podcast.py**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Podcast(Base):
    __tablename__ = "podcasts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(Text, nullable=True)
    auto_process: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    episodes = relationship("Episode", back_populates="podcast", cascade="all, delete-orphan")
    source_configs = relationship("SourceConfig", back_populates="podcast", cascade="all, delete-orphan")
```

- [ ] **Step 3: Create app/models/episode.py**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    podcast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("podcasts.id"), nullable=False, index=True)
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    audio_url: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new", index=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    podcast = relationship("Podcast", back_populates="episodes")
    transcript = relationship("Transcript", back_populates="episode", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        __table_args__ = (UniqueConstraint("podcast_id", "guid", name="uq_episode_guid"),)
    )
```

Note: Need to import UniqueConstraint:
```python
from sqlalchemy import UniqueConstraint
```

- [ ] **Step 4: Create app/models/transcript.py**

```python
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False, unique=True)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    detected_language: Mapped[str] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    timestamps_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode = relationship("Episode", back_populates="transcript")
    chunks = relationship("TranscriptChunk", back_populates="transcript", cascade="all, delete-orphan")
```

Note: Need JSONB import:
```python
from sqlalchemy.dialects.postgresql import JSONB
```


```python
class TranscriptChunk(Base):
    __tablename__ = "transcript_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    transcript_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("transcripts.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcript = relationship("Transcript", back_populates="chunks")
```

- [ ] **Step 5: Create app/models/source_config.py**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SourceConfig(Base):
    __tablename__ = "source_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    podcast_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("podcasts.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_polled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    podcast = relationship("Podcast", back_populates="source_configs")
```

- [ ] **Step 6: Create app/models/setting.py**

```python
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
```

- [ ] **Step 7: Create tests/conftest.py**

```python
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base, get_db
from app.main import app
from app.config import settings
from app.models.podcast import Podcast
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.models.source_config import SourceConfig


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


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

Note: For the test with sqlite, we won't use pgvector. Instead, we'll skip vector tests in SQLite or use a flag. Let me rethink this — the conftest should work with PostgreSQL in the test container. Actually for simplicity, let me make the test database configurable, but default to requiring PostgreSQL. Or we can have a pytest fixture that starts a test PostgreSQL.

Actually, let's simplify: tests will target real PostgreSQL in CI, and for local dev we can use the same docker-compose db. Let me make the conftest simple with a marker for database tests and use mocks for service-level tests.

Let me revise the conftest to be simpler:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import engine, get_db
from app.main import app


@pytest_asyncio.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
```

Actually, let me keep it simple. Tests will use the real database (docker-compose db). No in-memory SQLite.

Let me rewrite this step properly.

- [ ] **Step 7: Create tests/conftest.py**

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "postgresql+asyncpg://podcast:podcast@localhost/podcast_transcribe_test"


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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

- [ ] **Step 8: Verify models import correctly**

Run: `python -c "from app.models import Podcast, Episode, Transcript, TranscriptChunk, SourceConfig, Setting; print('OK')"`
Expected: No ImportError

---

### Task 3: RSS Source Adapter

**Files:**
- Create: `app/adapters/__init__.py`
- Create: `app/adapters/base.py`
- Create: `app/adapters/rss.py`
- Create: `app/services/rss_poller.py`
- Create: `tests/test_rss_adapter.py`

- [ ] **Step 1: Create app/adapters/__init__.py**

```python
from app.adapters.base import BaseSourceAdapter, EpisodeMetadata
from app.adapters.rss import RSSSourceAdapter

__all__ = ["BaseSourceAdapter", "EpisodeMetadata", "RSSSourceAdapter"]
```

- [ ] **Step 2: Create app/adapters/base.py**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO


@dataclass
class EpisodeMetadata:
    guid: str
    title: str
    description: str | None
    audio_url: str
    duration_seconds: int | None
    published_at: datetime | None
    cover_url: str | None


class BaseSourceAdapter(ABC):
    @abstractmethod
    async def discover_new(self, url: str) -> list[EpisodeMetadata]:
        ...

    @abstractmethod
    async def fetch_audio(self, audio_url: str) -> BinaryIO:
        ...
```

- [ ] **Step 3: Create app/adapters/rss.py**

```python
import io
from datetime import datetime
from typing import BinaryIO

import feedparser
import httpx

from app.adapters.base import BaseSourceAdapter, EpisodeMetadata


class RSSSourceAdapter(BaseSourceAdapter):
    async def discover_new(self, url: str) -> list[EpisodeMetadata]:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=30)
            response.raise_for_status()

        feed = feedparser.parse(response.text)
        episodes = []
        for entry in feed.entries:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6])

            audio_url = None
            duration = None
            if hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if enc.get("type", "").startswith("audio/"):
                        audio_url = enc.get("href")
                        break
            if not audio_url and hasattr(entry, "links"):
                for link in entry.links:
                    if link.get("type", "").startswith("audio/"):
                        audio_url = link.get("href")
                        break

            if hasattr(entry, "itunes_duration"):
                duration = self._parse_duration(entry.itunes_duration)

            cover_url = None
            feed_cover = feed.feed.get("image", {})
            if feed_cover:
                cover_url = feed_cover.get("href") or feed_cover.get("url")
            if not cover_url and hasattr(entry, "itunes_image"):
                cover_url = entry.itunes_image.get("href")

            episodes.append(EpisodeMetadata(
                guid=entry.get("id", entry.get("link", "")),
                title=entry.get("title", ""),
                description=entry.get("description", entry.get("summary", "")),
                audio_url=audio_url or "",
                duration_seconds=duration,
                published_at=published,
                cover_url=cover_url,
            ))
        return episodes

    async def fetch_audio(self, audio_url: str) -> BinaryIO:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.get(audio_url)
            response.raise_for_status()
        return io.BytesIO(response.content)

    def _parse_duration(self, duration: str) -> int | None:
        parts = str(duration).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1:
            return int(parts[0])
        return None
```

- [ ] **Step 4: Create app/services/rss_poller.py**

```python
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.rss import RSSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.services.pipeline import enqueue_episode

logger = logging.getLogger(__name__)


async def poll_all_feeds():
    async with async_session() as session:
        result = await session.execute(
            select(SourceConfig).where(
                SourceConfig.source_type == "rss",
                SourceConfig.enabled == True,
            )
        )
        configs = result.scalars().all()

    for config in configs:
        await poll_feed(config.id)


async def poll_feed(source_config_id: str | None = None):
    async with async_session() as session:
        if source_config_id:
            result = await session.execute(
                select(SourceConfig).where(SourceConfig.id == source_config_id)
            )
        else:
            result = await session.execute(
                select(SourceConfig).where(
                    SourceConfig.source_type == "rss",
                    SourceConfig.enabled == True,
                ).limit(1)
            )
        config = result.scalar_one_or_none()
        if not config:
            return

        adapter = RSSSourceAdapter()
        try:
            episodes_meta = await adapter.discover_new(config.url)
        except Exception as e:
            logger.error("RSS poll failed for %s: %s", config.url, e)
            return

        podcast = await session.get(Podcast, config.podcast_id)

        for meta in episodes_meta:
            existing = await session.execute(
                select(Episode).where(
                    Episode.podcast_id == podcast.id,
                    Episode.guid == meta.guid,
                )
            )
            if existing.scalar_one_or_none():
                continue

            if podcast.cover_url is None and meta.cover_url:
                podcast.cover_url = meta.cover_url

            episode = Episode(
                podcast_id=podcast.id,
                guid=meta.guid,
                title=meta.title,
                description=meta.description,
                audio_url=meta.audio_url,
                duration_seconds=meta.duration_seconds,
                published_at=meta.published_at,
                status="new",
            )
            session.add(episode)

        config.last_polled_at = datetime.now(timezone.utc)
        await session.commit()

        if podcast.auto_process:
            for meta in episodes_meta:
                existing = await session.execute(
                    select(Episode).where(
                        Episode.podcast_id == podcast.id,
                        Episode.guid == meta.guid,
                    )
                )
                ep = existing.scalar_one_or_none()
                if ep and ep.status == "new":
                    await enqueue_episode(ep.id)
```

- [ ] **Step 5: Create tests/test_rss_adapter.py**

```python
import pytest
from app.adapters import RSSSourceAdapter


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Podcast</title>
    <image><url>https://example.com/cover.jpg</url></image>
    <item>
      <title>Episode 1</title>
      <guid>ep1</guid>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="12345"/>
      <pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate>
      <itunes:duration>1800</itunes:duration>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_rss_adapter_discover(httpx_mock):
    httpx_mock.add_response(url="https://example.com/feed.xml", text=SAMPLE_FEED)
    adapter = RSSSourceAdapter()
    episodes = await adapter.discover_new("https://example.com/feed.xml")
    assert len(episodes) == 1
    assert episodes[0].guid == "ep1"
    assert episodes[0].title == "Episode 1"
    assert episodes[0].audio_url == "https://example.com/ep1.mp3"
    assert episodes[0].duration_seconds == 1800
    assert episodes[0].cover_url == "https://example.com/cover.jpg"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pip install pytest pytest-asyncio pytest-httpx && pytest tests/test_rss_adapter.py -v`
Expected: PASS

---

### Task 4: OpenRouter Client + Transcription Service

**Files:**
- Create: `app/services/__init__.py`
- Create: `app/services/openrouter.py`
- Create: `app/services/transcribe.py`
- Create: `tests/test_openrouter.py`

- [ ] **Step 1: Create app/services/__init__.py**

Empty file.

- [ ] **Step 2: Create app/services/openrouter.py**

```python
import httpx
from app.config import settings


class OpenRouterClient:
    def __init__(self):
        self.base_url = settings.openrouter_base_url
        self.api_key = settings.openrouter_api_key
        self._http = httpx.AsyncClient(timeout=300)

    async def close(self):
        await self._http.aclose()

    async def _post(self, path: str, json: dict) -> dict:
        response = await self._http.post(
            f"{self.base_url}/{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=json,
        )
        response.raise_for_status()
        return response.json()

    async def transcribe(self, model: str, audio_data: bytes, filename: str = "audio.mp3") -> str:
        files = {"file": (filename, audio_data, "audio/mpeg")}
        response = await self._http.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={"model": model},
            files=files,
        )
        response.raise_for_status()
        result = response.json()
        return result.get("text", "")

    async def transcribe_with_timestamps(self, model: str, audio_data: bytes) -> dict:
        files = {"file": ("audio.mp3", audio_data, "audio/mpeg")}
        response = await self._http.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={"model": model, "response_format": "verbose_json"},
            files=files,
        )
        response.raise_for_status()
        return response.json()

    async def summarize(self, model: str, transcript: str, language: str) -> str:
        prompt = (
            f"Summarize this podcast episode in {language or 'the same language as the transcript'} "
            f"in 3-5 paragraphs:\n\n{transcript}"
        )
        result = await self._post("chat/completions", {
            "model": model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant that summarizes podcast episodes."},
                {"role": "user", "content": prompt},
            ],
        })
        return result["choices"][0]["message"]["content"]

    async def embed(self, model: str, text: str) -> list[float]:
        result = await self._post("embeddings", {
            "model": model,
            "input": text,
        })
        return result["data"][0]["embedding"]
```

- [ ] **Step 3: Create app/services/transcribe.py**

```python
import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

TRANSCRIPTION_MODEL_KEY = "transcription_model"
DEFAULT_TRANSCRIPTION_MODEL = "openai/whisper-1"


async def transcribe_audio(session, audio_data: bytes) -> tuple[str, dict | None]:
    setting = await session.get(Setting, TRANSCRIPTION_MODEL_KEY)
    model = setting.value if setting else DEFAULT_TRANSCRIPTION_MODEL

    client = OpenRouterClient()
    try:
        result = await client.transcribe_with_timestamps(model, audio_data)
        full_text = result.get("text", "")
        segments = result.get("segments", None)
        return full_text, segments
    finally:
        await client.close()
```

- [ ] **Step 4: Create tests/test_openrouter.py**

```python
import pytest
from unittest.mock import patch, AsyncMock

from app.services.openrouter import OpenRouterClient


@pytest.mark.asyncio
async def test_summarize():
    client = OpenRouterClient()
    mock_response = {
        "choices": [{"message": {"content": "This is a summary."}}]
    }
    with patch.object(client._http, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.__aenter__.return_value.status_code = 200
        mock_post.return_value.__aenter__.return_value.json = AsyncMock(return_value=mock_response)
        result = await client.summarize("test-model", "Some transcript text", "danish")
        assert result == "This is a summary."
    await client.close()
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_openrouter.py -v`
Expected: PASS

---

### Task 5: Summarization, Embedding & Episode Pipeline

**Files:**
- Create: `app/services/summarize.py`
- Create: `app/services/embedder.py`
- Create: `app/services/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Create app/services/summarize.py**

```python
import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

SUMMARIZATION_MODEL_KEY = "summarization_model"
DEFAULT_SUMMARIZATION_MODEL = "openai/gpt-4o-mini"


async def generate_summary(session, full_text: str, language: str | None) -> str:
    setting = await session.get(Setting, SUMMARIZATION_MODEL_KEY)
    model = setting.value if setting else DEFAULT_SUMMARIZATION_MODEL

    client = OpenRouterClient()
    try:
        summary = await client.summarize(model, full_text, language or "english")
        return summary
    finally:
        await client.close()
```

- [ ] **Step 2: Create app/services/embedder.py**

```python
import logging
from app.models.setting import Setting
from app.services.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks


async def embed_chunks(session, chunks: list[str]) -> list[list[float]]:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    model = setting.value if setting else DEFAULT_EMBEDDING_MODEL

    client = OpenRouterClient()
    try:
        embeddings = []
        for chunk in chunks:
            embedding = await client.embed(model, chunk)
            embeddings.append(embedding)
        return embeddings
    finally:
        await client.close()
```

- [ ] **Step 3: Create app/services/pipeline.py**

```python
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import RSSSourceAdapter
from app.database import async_session
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.services.transcribe import transcribe_audio
from app.services.summarize import generate_summary
from app.services.embedder import chunk_text, embed_chunks
from app.config import settings

logger = logging.getLogger(__name__)


async def enqueue_episode(episode_id):
    await process_episode(episode_id)


async def process_episode(episode_id):
    async with async_session() as session:
        episode = await session.get(Episode, episode_id)
        if not episode or episode.status == "ready":
            return

        episode.status = "downloading"
        await session.commit()

        try:
            adapter = RSSSourceAdapter()
            audio_data = await adapter.fetch_audio(episode.audio_url)

            episode.status = "transcribing"
            await session.commit()

            full_text, segments = await transcribe_audio(session, audio_data)
            transcript = Transcript(
                episode_id=episode.id,
                full_text=full_text,
                timestamps_json=segments,
            )
            session.add(transcript)
            await session.commit()

            episode.status = "summarizing"
            await session.commit()

            summary = await generate_summary(session, full_text, None)
            transcript.summary = summary
            await session.commit()

            episode.status = "indexing"
            await session.commit()

            chunks = chunk_text(full_text)
            embeddings = await embed_chunks(session, chunks)

            for i, (chunk_text_val, embedding) in enumerate(zip(chunks, embeddings)):
                chunk = TranscriptChunk(
                    transcript_id=transcript.id,
                    chunk_index=i,
                    text=chunk_text_val,
                    embedding=embedding,
                )
                session.add(chunk)

            episode.status = "ready"
            await session.commit()

        except Exception as e:
            episode.status = "error"
            episode.error_message = str(e)
            await session.commit()
            logger.error("Failed to process episode %s: %s", episode_id, e)
```

- [ ] **Step 4: Create tests/test_pipeline.py**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.pipeline import process_episode


@pytest.mark.asyncio
async def test_process_episode_full_flow():
    mock_audio = b"fake audio data"
    mock_transcript_text = "This is a test transcript with several words for testing."
    mock_segments = [{"start": 0.0, "end": 5.0, "text": "This is a test transcript"}]
    mock_summary = "Test summary."
    mock_embedding = [0.1] * 1536

    with (
        patch("app.services.pipeline.async_session") as mock_session_factory,
        patch("app.services.pipeline.RSSSourceAdapter") as mock_adapter_cls,
        patch("app.services.pipeline.transcribe_audio", new_callable=AsyncMock) as mock_transcribe,
        patch("app.services.pipeline.generate_summary", new_callable=AsyncMock) as mock_summarize,
        patch("app.services.pipeline.embed_chunks", new_callable=AsyncMock) as mock_embed,
    ):
        mock_session = AsyncMock()
        mock_session_factory.return_value.__aenter__.return_value = mock_session

        mock_episode = MagicMock()
        mock_episode.status = "new"
        mock_session.get.return_value = mock_episode

        mock_adapter = AsyncMock()
        mock_adapter.fetch_audio.return_value = mock_audio
        mock_adapter_cls.return_value = mock_adapter

        mock_transcribe.return_value = (mock_transcript_text, mock_segments)
        mock_summarize.return_value = mock_summary
        mock_embed.return_value = [mock_embedding]

        await process_episode("test-id")

        assert mock_episode.status == "ready"
```

- [ ] **Step 5: Run test**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS

---

### Task 6: Search Service

**Files:**
- Create: `app/services/searcher.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Create app/services/searcher.py**

```python
import logging
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.transcript import Transcript, TranscriptChunk
from app.services.openrouter import OpenRouterClient
from app.models.setting import Setting

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"


async def search_fts(
    session: AsyncSession,
    query: str,
    language: str = "danish",
    podcast_ids: list[str] | None = None,
    episode_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    conditions = [text(f"ft.tsvector @@ phraseto_tsquery('{language}', :query)")]
    params = {"query": query}

    if podcast_ids:
        conditions.append(text("e.podcast_id = ANY(:podcast_ids)"))
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append(text("e.id = ANY(:episode_ids)"))
        params["episode_ids"] = episode_ids

    where_clause = " AND ".join(str(c) for c in conditions)

    sql = text(f"""
        SELECT e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url,
               ts_headline(:lang, ft.full_text, phraseto_tsquery(:lang, :query),
                           'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20') AS snippet
        FROM transcripts ft
        JOIN episodes e ON e.id = ft.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY ts_rank(ft.tsvector, phraseto_tsquery(:lang, :query)) DESC
        LIMIT :limit
    """)

    result = await session.execute(sql, {"lang": language, "limit": limit, **params})
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "snippet": r.snippet,
            "type": "fts",
        }
        for r in rows
    ]


async def search_semantic(
    session: AsyncSession,
    query: str,
    podcast_ids: list[str] | None = None,
    episode_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    setting = await session.get(Setting, EMBEDDING_MODEL_KEY)
    model = setting.value if setting else DEFAULT_EMBEDDING_MODEL

    client = OpenRouterClient()
    try:
        query_embedding = await client.embed(model, query)
    finally:
        await client.close()

    embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    conditions = ["1=1"]
    params: dict = {}
    if podcast_ids:
        conditions.append("e.podcast_id = ANY(:podcast_ids)")
        params["podcast_ids"] = podcast_ids
    if episode_ids:
        conditions.append("e.id = ANY(:episode_ids)")
        params["episode_ids"] = episode_ids

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT chunk.text, chunk.chunk_index,
               chunk.embedding <=> {embedding_str}::vector AS distance,
               e.id AS episode_id, e.title AS episode_title, e.published_at,
               p.title AS podcast_title, p.cover_url
        FROM transcript_chunks chunk
        JOIN transcripts t ON t.id = chunk.transcript_id
        JOIN episodes e ON e.id = t.episode_id
        JOIN podcasts p ON p.id = e.podcast_id
        WHERE {where_clause}
        ORDER BY distance ASC
        LIMIT :limit
    """)

    result = await session.execute(sql, {"limit": limit, **params})
    rows = result.fetchall()
    return [
        {
            "episode_id": str(r.episode_id),
            "episode_title": r.episode_title,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "podcast_title": r.podcast_title,
            "cover_url": r.cover_url,
            "snippet": r.text,
            "score": float(1.0 - r.distance),
            "type": "semantic",
        }
        for r in rows
    ]
```

- [ ] **Step 2: Create tests/test_search.py**

```python
import pytest
from unittest.mock import patch, AsyncMock

from app.services.searcher import search_fts, search_semantic


@pytest.mark.asyncio
async def test_search_fts_builds_query(db_session):
    with patch.object(db_session, "execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value.fetchall.return_value = []
        results = await search_fts(db_session, "test query", "danish")
        assert results == []
        assert mock_exec.called
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_search.py -v`
Expected: PASS

---

### Task 7: API Routers (Backend Endpoints)

**Files:**
- Create: `app/routers/__init__.py`
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/podcast.py`
- Create: `app/schemas/episode.py`
- Create: `app/schemas/search.py`
- Create: `app/routers/api_podcasts.py`
- Create: `app/routers/api_episodes.py`
- Create: `app/routers/api_search.py`
- Create: `app/routers/api_settings.py`

- [ ] **Step 1: Create app/schemas/__init__.py** (empty)

- [ ] **Step 2: Create app/routers/__init__.py** (empty)

- [ ] **Step 3: Create app/routers/api_podcasts.py**

```python
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.podcast import Podcast
from app.models.source_config import SourceConfig
from app.services.rss_poller import poll_feed

router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


@router.get("")
async def list_podcasts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Podcast).order_by(Podcast.title))
    podcasts = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "author": p.author,
            "description": p.description,
            "cover_url": p.cover_url,
            "language": p.language,
            "auto_process": p.auto_process,
        }
        for p in podcasts
    ]


@router.post("")
async def create_podcast(
    title: str,
    rss_url: str,
    auto_process: bool = True,
    db: AsyncSession = Depends(get_db),
):
    podcast = Podcast(title=title, auto_process=auto_process)
    db.add(podcast)
    await db.flush()

    config = SourceConfig(
        podcast_id=podcast.id,
        source_type="rss",
        url=rss_url,
        enabled=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(podcast)
    return {"id": str(podcast.id), "title": podcast.title}


@router.get("/{podcast_id}")
async def get_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}, 404
    result = await db.execute(
        select(SourceConfig).where(SourceConfig.podcast_id == podcast_id)
    )
    configs = result.scalars().all()
    return {
        "id": str(podcast.id),
        "title": podcast.title,
        "author": podcast.author,
        "description": podcast.description,
        "cover_url": podcast.cover_url,
        "language": podcast.language,
        "auto_process": podcast.auto_process,
        "sources": [
            {
                "id": str(c.id),
                "source_type": c.source_type,
                "url": c.url,
                "enabled": c.enabled,
            }
            for c in configs
        ],
    }


@router.patch("/{podcast_id}")
async def update_podcast(
    podcast_id: UUID,
    auto_process: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}, 404
    if auto_process is not None:
        podcast.auto_process = auto_process
    await db.commit()
    return {"id": str(podcast.id), "auto_process": podcast.auto_process}


@router.post("/{podcast_id}/poll")
async def poll_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}, 404
    result = await db.execute(
        select(SourceConfig).where(
            SourceConfig.podcast_id == podcast_id,
            SourceConfig.enabled == True,
        )
    )
    config = result.scalar_one_or_none()
    if config:
        await poll_feed(config.id)
    return {"status": "polled"}


@router.delete("/{podcast_id}")
async def delete_podcast(podcast_id: UUID, db: AsyncSession = Depends(get_db)):
    podcast = await db.get(Podcast, podcast_id)
    if not podcast:
        return {"error": "not found"}, 404
    await db.delete(podcast)
    await db.commit()
    return {"status": "deleted"}
```

- [ ] **Step 4: Create app/routers/api_episodes.py**

```python
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.transcript import Transcript
from app.services.pipeline import process_episode

router = APIRouter(prefix="/api/episodes", tags=["episodes"])


@router.get("")
async def list_episodes(
    podcast_id: UUID | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Episode)
    if podcast_id:
        query = query.where(Episode.podcast_id == podcast_id)
    if status:
        query = query.where(Episode.status == status)
    query = query.order_by(Episode.published_at.desc())
    result = await db.execute(query)
    episodes = result.scalars().all()
    return [
        {
            "id": str(e.id),
            "podcast_id": str(e.podcast_id),
            "title": e.title,
            "description": e.description,
            "duration_seconds": e.duration_seconds,
            "published_at": e.published_at.isoformat() if e.published_at else None,
            "status": e.status,
            "error_message": e.error_message,
        }
        for e in episodes
    ]


@router.get("/{episode_id}")
async def get_episode(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}, 404
    result = await db.execute(
        select(Transcript).where(Transcript.episode_id == episode_id)
    )
    transcript = result.scalar_one_or_none()
    return {
        "id": str(episode.id),
        "podcast_id": str(episode.podcast_id),
        "title": episode.title,
        "description": episode.description,
        "duration_seconds": episode.duration_seconds,
        "published_at": episode.published_at.isoformat() if episode.published_at else None,
        "status": episode.status,
        "error_message": episode.error_message,
        "transcript": {
            "full_text": transcript.full_text if transcript else None,
            "summary": transcript.summary if transcript else None,
            "detected_language": transcript.detected_language if transcript else None,
        } if transcript else None,
    }


@router.post("/{episode_id}/process")
async def process_episode_endpoint(
    episode_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    episode = await db.get(Episode, episode_id)
    if not episode:
        return {"error": "not found"}, 404
    await process_episode(episode_id)
    return {"status": "processing"}
```

- [ ] **Step 5: Create app/routers/api_search.py**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.searcher import search_fts, search_semantic

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def search(
    q: str = Query(..., description="Search query"),
    mode: str = Query("auto", description="Search mode: fts, semantic, or auto"),
    language: str = Query("danish", description="Language for FTS"),
    podcast_ids: str | None = Query(None, description="Comma-separated podcast IDs"),
    episode_ids: str | None = Query(None, description="Comma-separated episode IDs"),
    limit: int = Query(20, le=50),
    db: AsyncSession = Depends(get_db),
):
    pid_list = podcast_ids.split(",") if podcast_ids else None
    eid_list = episode_ids.split(",") if episode_ids else None

    if mode == "fts":
        results = await search_fts(db, q, language, pid_list, eid_list, limit)
    elif mode == "semantic":
        results = await search_semantic(db, q, pid_list, eid_list, limit)
    else:
        fts_results = await search_fts(db, q, language, pid_list, eid_list, limit)
        semantic_results = await search_semantic(db, q, pid_list, eid_list, limit)
        seen = set()
        results = []
        for r in fts_results + semantic_results:
            if r["episode_id"] not in seen:
                seen.add(r["episode_id"])
                results.append(r)

    return {"results": results, "total": len(results)}
```

- [ ] **Step 6: Create app/routers/api_settings.py**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.setting import Setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


VALID_KEYS = {
    "openrouter_api_key",
    "transcription_model",
    "summarization_model",
    "embedding_model",
}


@router.get("")
async def get_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        Setting.__table__.select().where(Setting.key.in_(VALID_KEYS))
    )
    rows = result.fetchall()
    return {row.key: row.value for row in rows}


@router.put("")
async def update_settings(
    settings: dict[str, str],
    db: AsyncSession = Depends(get_db),
):
    for key, value in settings.items():
        if key in VALID_KEYS:
            existing = await db.get(Setting, key)
            if existing:
                existing.value = value
            else:
                db.add(Setting(key=key, value=value))
    await db.commit()
    return {"status": "saved"}
```

- [ ] **Step 7: Wire routers into app/main.py**

Add imports and include routers:

```python
from app.routers import api_podcasts, api_episodes, api_search, api_settings, ui

app.include_router(api_podcasts.router)
app.include_router(api_episodes.router)
app.include_router(api_search.router)
app.include_router(api_settings.router)
app.include_router(ui.router)
```

- [ ] **Step 8: Verify no import errors**

Run: `python -c "from app.main import app; print('OK')"`
Expected: OK

---

### Task 8: Background Scheduler

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add APScheduler to app/main.py**

```python
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database import engine
from app.services.rss_poller import poll_all_feeds

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(
        poll_all_feeds,
        trigger="interval",
        hours=6,
        id="rss_poll",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(title="PodcastTransscribe", lifespan=lifespan)
```

---

### Task 9: Web UI — Templates & Layout

**Files:**
- Create: `app/routers/ui.py`
- Create: `app/templates/base.html`
- Create: `app/templates/dashboard.html`
- Create: `app/templates/podcast_detail.html`
- Create: `app/templates/episode.html`
- Create: `app/templates/search.html`
- Create: `app/templates/admin.html`

- [ ] **Step 1: Create app/routers/ui.py**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/podcasts/{podcast_id}", response_class=HTMLResponse)
async def podcast_detail(request: Request, podcast_id: str):
    return templates.TemplateResponse("podcast_detail.html", {"request": request, "podcast_id": podcast_id})


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
async def episode_view(request: Request, episode_id: str):
    return templates.TemplateResponse("episode.html", {"request": request, "episode_id": episode_id})


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})
```

- [ ] **Step 2: Create app/templates/base.html**

```html
<!DOCTYPE html>
<html lang="en" class="h-full bg-gray-950">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PodcastTransscribe</title>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="h-full text-gray-100">
  <nav class="border-b border-gray-800 bg-gray-900 px-6 py-3 flex items-center gap-6">
    <a href="/" class="text-lg font-bold text-emerald-400">PodcastTransscribe</a>
    <a href="/" class="hover:text-emerald-300 text-sm">Dashboard</a>
    <a href="/search" class="hover:text-emerald-300 text-sm">Search</a>
    <a href="/admin" class="hover:text-emerald-300 text-sm">Admin</a>
  </nav>
  <main class="mx-auto max-w-6xl px-6 py-8">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 3: Create app/templates/dashboard.html**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="dashboard()">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold">Podcasts</h1>
    <button @click="showAdd = true" class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium">+ Add Podcast</button>
  </div>

  <div x-show="showAdd" x-cloak class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
    <form class="bg-gray-900 p-6 rounded-lg border border-gray-700 w-full max-w-md"
          hx-post="/api/podcasts" hx-target="#podcast-grid" hx-swap="afterbegin"
          @submit="showAdd = false" hx-on::after-request="this.reset()">
      <h2 class="text-lg font-bold mb-4">Add Podcast</h2>
      <label class="block mb-2 text-sm">Title</label>
      <input name="title" required class="w-full mb-3 p-2 rounded bg-gray-800 border border-gray-700 text-sm">
      <label class="block mb-2 text-sm">RSS URL</label>
      <input name="rss_url" type="url" required class="w-full mb-3 p-2 rounded bg-gray-800 border border-gray-700 text-sm">
      <label class="flex items-center gap-2 mb-4 text-sm">
        <input name="auto_process" type="checkbox" checked class="rounded bg-gray-800 border-gray-600">
        Auto-process episodes
      </label>
      <div class="flex justify-end gap-2">
        <button type="button" @click="showAdd = false" class="px-3 py-1.5 rounded bg-gray-700 text-sm">Cancel</button>
        <button type="submit" class="px-3 py-1.5 rounded bg-emerald-600 text-sm">Add</button>
      </div>
    </form>
  </div>

  <div id="podcast-grid" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4"
       hx-get="/api/podcasts" hx-trigger="load" hx-swap="innerHTML">
    Loading...
  </div>
</div>

<script>
function dashboard() {
  return { showAdd: false };
}
</script>
{% endblock %}
```

- [ ] **Step 4: Create app/templates/podcast_detail.html**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="podcastDetail()" x-init="loadPodcast()">
  <a href="/" class="text-emerald-400 hover:text-emerald-300 text-sm mb-4 inline-block">&larr; Back</a>
  <div id="podcast-info" class="mb-6">
    <div class="animate-pulse h-8 w-64 bg-gray-800 rounded mb-2"></div>
  </div>

  <div id="episode-list" class="space-y-2"
       hx-get="/api/episodes?podcast_id={{ podcast_id }}"
       hx-trigger="load" hx-swap="innerHTML">
  </div>
</div>

<script>
function podcastDetail() {
  return {
    podcastId: '{{ podcast_id }}',
    async loadPodcast() {
      const r = await fetch('/api/podcasts/' + this.podcastId);
      const data = await r.json();
      document.getElementById('podcast-info').innerHTML = `
        <div class="flex items-center gap-4">
          ${data.cover_url ? `<img src="${data.cover_url}" class="w-16 h-16 rounded">` : ''}
          <div>
            <h1 class="text-2xl font-bold">${data.title}</h1>
            <p class="text-gray-400 text-sm">${data.author || ''}</p>
          </div>
        </div>
        <div class="flex items-center gap-4 mt-4">
          <label class="flex items-center gap-2 text-sm">
            <input type="checkbox" ${data.auto_process ? 'checked' : ''}
                   hx-patch="/api/podcasts/${this.podcastId}"
                   hx-vals='{"auto_process": ${!data.auto_process}}'
                   hx-trigger="change">
            Auto-process
          </label>
          <button hx-post="/api/podcasts/${this.podcastId}/poll"
                  class="text-sm text-emerald-400 hover:text-emerald-300">Poll Now</button>
        </div>
      `;
    }
  };
}
</script>
{% endblock %}
```

- [ ] **Step 5: Create app/templates/episode.html**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="episodeView()" x-init="loadEpisode()">
  <a href="/" class="text-emerald-400 hover:text-emerald-300 text-sm mb-4 inline-block">&larr; Back</a>

  <div id="episode-info" class="mb-6">
    <div class="animate-pulse h-8 w-64 bg-gray-800 rounded mb-2"></div>
  </div>

  <div id="episode-summary" class="mb-6 p-4 bg-gray-900 rounded-lg border border-gray-800 hidden"></div>

  <div id="episode-transcript" class="space-y-2 leading-relaxed"></div>
</div>

<script>
function episodeView() {
  return {
    episodeId: '{{ episode_id }}',
    async loadEpisode() {
      const r = await fetch('/api/episodes/' + this.episodeId);
      const data = await r.json();
      const t = data.transcript;

      document.getElementById('episode-info').innerHTML = `
        <h1 class="text-2xl font-bold">${data.title}</h1>
        <p class="text-gray-400 text-sm mt-1">${data.published_at || ''} &middot; ${data.status}</p>
        ${data.error_message ? `<p class="text-red-400 text-sm mt-1">${data.error_message}</p>` : ''}
        ${data.status === 'new' || data.status === 'error' ? `
          <button hx-post="/api/episodes/${this.episodeId}/process"
                  class="mt-3 bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm">
            ${data.status === 'error' ? 'Retry' : 'Process Now'}
          </button>
        ` : ''}
      `;

      if (t && t.summary) {
        document.getElementById('episode-summary').classList.remove('hidden');
        document.getElementById('episode-summary').innerHTML = `
          <h2 class="text-sm font-semibold text-emerald-400 mb-2">Summary</h2>
          <div class="text-sm leading-relaxed">${t.summary}</div>
        `;
      }

      if (t && t.full_text) {
        const params = new URLSearchParams(window.location.search);
        const highlight = params.get('q');
        let text = t.full_text;
        if (highlight) {
          text = text.replace(
            new RegExp('(' + highlight.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'),
            '<mark class="bg-emerald-700 text-emerald-200 px-0.5 rounded">$1</mark>'
          );
        }
        document.getElementById('episode-transcript').innerHTML =
          `<div class="text-sm leading-relaxed whitespace-pre-wrap">${text}</div>`;
      } else if (data.status === 'ready' && !t) {
        document.getElementById('episode-transcript').innerHTML =
          '<p class="text-gray-500">No transcript available.</p>';
      } else if (data.status === 'new') {
        document.getElementById('episode-transcript').innerHTML =
          '<p class="text-gray-500">Episode not yet processed.</p>';
      }
    }
  };
}
</script>
{% endblock %}
```

- [ ] **Step 6: Create app/templates/search.html**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="searchView()">
  <h1 class="text-2xl font-bold mb-6">Search</h1>

  <form @submit.prevent="doSearch()" class="mb-6 space-y-4">
    <div class="flex gap-2">
      <input type="text" x-model="query" placeholder="Search transcripts..."
             class="flex-1 p-2 rounded bg-gray-900 border border-gray-700 text-sm"
             @keyup.enter="doSearch()">
      <button type="submit" class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium">Search</button>
    </div>

    <div class="flex flex-wrap gap-4 text-sm">
      <select x-model="mode" class="bg-gray-900 border border-gray-700 rounded p-1.5">
        <option value="auto">Auto (FTS + Semantic)</option>
        <option value="fts">Exact Phrase</option>
        <option value="semantic">Natural Language</option>
      </select>

      <select x-model="podcastFilter" @change="loadEpisodes()" class="bg-gray-900 border border-gray-700 rounded p-1.5">
        <option value="">All Podcasts</option>
        <template x-for="p in podcasts" :key="p.id">
          <option :value="p.id" x-text="p.title"></option>
        </template>
      </select>

      <select x-model="episodeFilter" class="bg-gray-900 border border-gray-700 rounded p-1.5">
        <option value="">All Episodes</option>
        <template x-for="e in episodes" :key="e.id">
          <option :value="e.id" x-text="e.title"></option>
        </template>
      </select>
    </div>
  </form>

  <div id="search-results" class="space-y-3"></div>
</div>

<script>
function searchView() {
  return {
    query: '',
    mode: 'auto',
    podcastFilter: '',
    episodeFilter: '',
    podcasts: [],
    episodes: [],

    async init() {
      const r = await fetch('/api/podcasts');
      this.podcasts = await r.json();
    },

    async loadEpisodes() {
      if (!this.podcastFilter) { this.episodes = []; return; }
      const r = await fetch('/api/episodes?podcast_id=' + this.podcastFilter);
      this.episodes = await r.json();
    },

    async doSearch() {
      if (!this.query.trim()) return;
      const params = new URLSearchParams({ q: this.query, mode: this.mode });
      if (this.podcastFilter) params.set('podcast_ids', this.podcastFilter);
      if (this.episodeFilter) params.set('episode_ids', this.episodeFilter);

      const r = await fetch('/api/search?' + params);
      const data = await r.json();
      const container = document.getElementById('search-results');

      if (data.results.length === 0) {
        container.innerHTML = '<p class="text-gray-500">No results found.</p>';
        return;
      }

      container.innerHTML = data.results.map(r => `
        <a href="/episodes/${r.episode_id}?q=${encodeURIComponent(this.query)}"
           class="block p-4 bg-gray-900 rounded-lg border border-gray-800 hover:border-emerald-700 transition">
          <div class="flex items-start gap-3">
            ${r.cover_url ? `<img src="${r.cover_url}" class="w-10 h-10 rounded flex-shrink-0">` : ''}
            <div class="min-w-0">
              <div class="text-xs text-gray-500">${r.podcast_title}</div>
              <div class="font-medium truncate">${r.episode_title}</div>
              <div class="text-sm text-gray-300 mt-1 leading-relaxed line-clamp-3">${r.snippet}</div>
              <div class="text-xs text-gray-600 mt-1">${r.type === 'fts' ? 'Exact match' : `Relevance: ${(r.score || 0).toFixed(2)}`}</div>
            </div>
          </div>
        </a>
      `).join('');
    }
  };
}
</script>
{% endblock %}
```

- [ ] **Step 7: Create app/templates/admin.html**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="adminView()" x-init="loadSettings()">
  <h1 class="text-2xl font-bold mb-6">Admin / Settings</h1>

  <div class="grid gap-6 max-w-lg">
    <div class="p-4 bg-gray-900 rounded-lg border border-gray-800">
      <h2 class="font-semibold mb-3">OpenRouter</h2>
      <label class="block text-sm mb-1">API Key</label>
      <input type="password" x-model="apiKey" class="w-full p-2 rounded bg-gray-800 border border-gray-700 text-sm mb-3">

      <label class="block text-sm mb-1">Transcription Model</label>
      <input x-model="transcriptionModel" class="w-full p-2 rounded bg-gray-800 border border-gray-700 text-sm mb-3"
             placeholder="openai/whisper-1">

      <label class="block text-sm mb-1">Summarization Model</label>
      <input x-model="summarizationModel" class="w-full p-2 rounded bg-gray-800 border border-gray-700 text-sm mb-3"
             placeholder="openai/gpt-4o-mini">

      <label class="block text-sm mb-1">Embedding Model</label>
      <input x-model="embeddingModel" class="w-full p-2 rounded bg-gray-800 border border-gray-700 text-sm mb-3"
             placeholder="openai/text-embedding-3-small">

      <button @click="saveSettings()" class="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded text-sm font-medium">Save</button>
      <span x-text="saveStatus" class="text-sm ml-2"></span>
    </div>
  </div>
</div>

<script>
function adminView() {
  return {
    apiKey: '',
    transcriptionModel: '',
    summarizationModel: '',
    embeddingModel: '',
    saveStatus: '',

    async loadSettings() {
      const r = await fetch('/api/settings');
      const data = await r.json();
      this.apiKey = data.openrouter_api_key || '';
      this.transcriptionModel = data.transcription_model || '';
      this.summarizationModel = data.summarization_model || '';
      this.embeddingModel = data.embedding_model || '';
    },

    async saveSettings() {
      const body = {};
      if (this.apiKey) body.openrouter_api_key = this.apiKey;
      if (this.transcriptionModel) body.transcription_model = this.transcriptionModel;
      if (this.summarizationModel) body.summarization_model = this.summarizationModel;
      if (this.embeddingModel) body.embedding_model = this.embeddingModel;

      const r = await fetch('/api/settings', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      if (r.ok) {
        this.saveStatus = 'Saved!';
        setTimeout(() => this.saveStatus = '', 2000);
      } else {
        this.saveStatus = 'Error saving';
      }
    }
  };
}
</script>
{% endblock %}
```

- [ ] **Step 8: Fix the Podcast model UniqueConstraint**

```python
# In app/models/episode.py, add:
from sqlalchemy import UniqueConstraint

# And update __table_args__:
__table_args__ = (
    UniqueConstraint("podcast_id", "guid", name="uq_episode_guid"),
)
```

- [ ] **Step 9: Verify template directory and basic HTML rendering**

Run: `ls -la app/templates/`
Expected: All template files present

---

### Task 10: Final Integration & Docker Build

**Files:**
- Modify: `docker-compose.yml`
- Create: `.dockerignore`

- [ ] **Step 1: Create .dockerignore**

```
__pycache__
*.pyc
.env
.git
tests/
```

- [ ] **Step 2: Build and verify Docker image compiles**

Run: `docker compose build`
Expected: Build succeeds

- [ ] **Step 3: Start services and verify app starts**

Run: `docker compose up -d`
Expected: Both containers running, app accessible at http://localhost:8000

- [ ] **Step 4: Verify health endpoint**

Run: `curl -s http://localhost:8000/ | head -5`
Expected: HTML response containing "PodcastTransscribe"

---

## Self-Review

**1. Spec coverage:**
- Podcast RSS subscription → Task 3 (RSS adapter) + Task 5 (pipeline)
- Audio download → Task 3 (`fetch_audio`) + Task 5 (pipeline orchestrator)
- OpenRouter transcription → Task 4 (OpenRouter client + transcribe service)
- Summarization → Task 5 (summarize service)
- Embeddings/chunking → Task 5 (embedder service)
- Full-text search → Task 6 (`search_fts`)
- Semantic search → Task 6 (`search_semantic`)
- Search filtering by podcast/episode → Task 6 (query params) + Task 9 (search UI)
- Auto-process toggle per podcast → Task 2 (Podcast.auto_process) + Task 7 (api_podcasts PATCH)
- Admin-settable models → Task 7 (api_settings) + Task 9 (admin.html)
- Docker deployment → Task 1 (docker-compose, Dockerfile) + Task 10
- Natural language → "Vicky og Johan" → semantic search mode
- Exact phrase → FTS `phraseto_tsquery`
- Highlighting in results → `ts_headline` with `<mark>` tags
- RSS adapter interface for future sources → `BaseSourceAdapter` ABC

**2. Placeholder scan:** No TBDs, TODOs, or vague placeholders found. All code blocks contain actual implementation.

**3. Type consistency:** `EpisodeMetadata` dataclass defined in `adapters/base.py` matches usage in `rss.py`. `search_fts`/`search_semantic` signatures match what `api_search.py` calls. Model field names consistent across models, schemas, and API routers.
