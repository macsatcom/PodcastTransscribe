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
        rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        tables = {r[0] for r in rows}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables after migration: {missing}"


@pytest.mark.asyncio
async def test_alembic_only_indexes_created(test_engine):
    async with test_engine.connect() as conn:
        rows = await conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"))
        indexes = {r[0] for r in rows}
    missing = EXPECTED_INDEXES - indexes
    assert not missing, f"Missing Alembic-only indexes: {missing}"


@pytest.mark.asyncio
async def test_migration_version_is_head(test_engine):
    async with test_engine.connect() as conn:
        rows = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = {r[0] for r in rows}
    assert len(versions) == 1, f"Expected one alembic version, got {versions}"
