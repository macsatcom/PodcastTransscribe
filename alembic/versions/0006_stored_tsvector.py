"""Stored tsvector column for fast FTS ranking

Problem: the GIN expression index on to_tsvector('danish', full_text) is used
for filtering (WHERE clause) but ts_rank must *re-evaluate* the expression from
the raw full_text for every matched row. With large transcript columns and many
matches (e.g. 920 rows for 'war'), this takes several seconds.

Fix: add a GENERATED ALWAYS AS STORED tsvector column so ts_rank reads the
precomputed value from the heap instead of computing it on the fly.

  ts_danish  TSVECTOR GENERATED ALWAYS AS (to_tsvector('danish', full_text)) STORED
  ts_english TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED

GIN indexes on the stored columns replace the expression indexes from 0005.
The old expression indexes are dropped to avoid duplicate index maintenance.

Revision ID: 0006_stored_tsvector
Revises: 0005_fts_and_vector_indexes
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op

revision = "0006_stored_tsvector"
down_revision = "0005_fts_and_vector_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add stored generated tsvector columns (PG12+)
    op.execute(
        "ALTER TABLE transcripts "
        "ADD COLUMN IF NOT EXISTS ts_danish TSVECTOR "
        "GENERATED ALWAYS AS (to_tsvector('danish', full_text)) STORED"
    )
    op.execute(
        "ALTER TABLE transcripts "
        "ADD COLUMN IF NOT EXISTS ts_english TSVECTOR "
        "GENERATED ALWAYS AS (to_tsvector('english', full_text)) STORED"
    )

    # GIN indexes on the stored columns
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_ts_danish "
        "ON transcripts USING gin (ts_danish)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_ts_english "
        "ON transcripts USING gin (ts_english)"
    )

    # Drop the expression indexes — superseded by the stored-column indexes
    op.execute("DROP INDEX IF EXISTS ix_transcripts_fts_danish")
    op.execute("DROP INDEX IF EXISTS ix_transcripts_fts_english")


def downgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_fts_danish "
        "ON transcripts USING gin (to_tsvector('danish', full_text))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_fts_english "
        "ON transcripts USING gin (to_tsvector('english', full_text))"
    )
    op.execute("DROP INDEX IF EXISTS ix_transcripts_ts_danish")
    op.execute("DROP INDEX IF EXISTS ix_transcripts_ts_english")
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS ts_danish")
    op.execute("ALTER TABLE transcripts DROP COLUMN IF EXISTS ts_english")
