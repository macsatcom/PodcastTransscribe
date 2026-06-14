import os

# Point the whole process at the test database BEFORE importing any app module,
# so app.config.settings (a module-level singleton) is built against it.
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://podcast:podcast@localhost/podcast_transcription_search_test",
)

import asyncio  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
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
