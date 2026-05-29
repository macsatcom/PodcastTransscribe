"""search & insights v2: chunk metadata, partial ivfflat, FTS GIN, topic chunks

Adds the columns and indexes that back the 0.18.0 search/insights rewrite.
All operations are idempotent (``ADD COLUMN IF NOT EXISTS`` /
``CREATE INDEX IF NOT EXISTS``) so this migration is safe to run on:

  * legacy databases that were stamped to 0001_initial after pre-Alembic
    create_all + inline ALTER lifespan, and
  * fresh databases where ``Base.metadata.create_all()`` already produced
    the new columns from the updated SQLAlchemy models.

Schema changes
--------------
* ``transcript_chunks.embedding_model TEXT NOT NULL`` (default
  ``'openai/text-embedding-3-large'``) -- model name for the embedding stored
  in the row, so the searcher can refuse to compare across model spaces.
* ``transcript_chunks.embedding_dim INT NOT NULL`` (default ``3072``) -- the
  vector dimensionality, so a partial ivfflat index can target only the rows
  that match the active embedding model.
* ``transcript_chunks.start_time DOUBLE PRECISION`` and ``end_time
  DOUBLE PRECISION`` -- per-chunk audio offsets aligned from
  ``Transcript.timestamps_json`` so search results can deep-link to the audio.
* ``topic_clusters.representative_chunks JSONB`` -- representative chunk ids
  + quote text per cluster so the Insights UI can show evidence.

Index changes
-------------
* Drop legacy full-table ivfflat / cosine index on ``transcript_chunks`` if
  present (named guesses; tolerant of absence).
* ``ix_chunks_embedding_3072`` -- partial ivfflat on
  ``embedding vector_cosine_ops`` filtered to ``embedding_dim = 3072``.
  Lists tuned for tens-of-thousands-of-rows scale.
* ``ix_transcripts_fts_simple`` -- GIN expression index on
  ``to_tsvector('simple', full_text)``. The searcher's ``_safe_lang`` coerces
  unknown FTS configs to ``'simple'``, so this index covers the safe-fallback
  query path. Add ``english`` / ``danish`` variants as content-language data
  warrants.

Revision ID: 0002_search_insights_v2
Revises: 0001_initial
Create Date: 2026-05-29
"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_search_insights_v2"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- transcript_chunks ----------------------------------------------------
    op.execute(
        "ALTER TABLE transcript_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_model TEXT "
        "NOT NULL DEFAULT 'openai/text-embedding-3-large'"
    )
    op.execute(
        "ALTER TABLE transcript_chunks "
        "ADD COLUMN IF NOT EXISTS embedding_dim INTEGER "
        "NOT NULL DEFAULT 3072"
    )
    op.execute(
        "ALTER TABLE transcript_chunks "
        "ADD COLUMN IF NOT EXISTS start_time DOUBLE PRECISION"
    )
    op.execute(
        "ALTER TABLE transcript_chunks "
        "ADD COLUMN IF NOT EXISTS end_time DOUBLE PRECISION"
    )

    # --- topic_clusters -------------------------------------------------------
    op.execute(
        "ALTER TABLE topic_clusters "
        "ADD COLUMN IF NOT EXISTS representative_chunks JSONB"
    )

    # --- drop legacy full-table embedding index if present --------------------
    # We don't know its exact historical name; cover the common candidates.
    for legacy in (
        "ix_transcript_chunks_embedding",
        "transcript_chunks_embedding_idx",
        "idx_transcript_chunks_embedding",
    ):
        op.execute(f"DROP INDEX IF EXISTS {legacy}")

    # --- partial ivfflat on 3072-dim rows -------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_3072 "
        "ON transcript_chunks "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100) "
        "WHERE embedding_dim = 3072"
    )

    # --- FTS expression GIN index on transcripts.full_text --------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_fts_simple "
        "ON transcripts "
        "USING gin (to_tsvector('simple', full_text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcripts_fts_simple")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_3072")
    op.execute("ALTER TABLE topic_clusters DROP COLUMN IF EXISTS representative_chunks")
    op.execute("ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS end_time")
    op.execute("ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS start_time")
    op.execute("ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS embedding_dim")
    op.execute("ALTER TABLE transcript_chunks DROP COLUMN IF EXISTS embedding_model")
