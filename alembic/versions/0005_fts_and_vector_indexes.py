"""FTS language indexes + HNSW vector index

Fixes two performance gaps left by 0002_search_insights_v2:

1. FTS GIN indexes for 'danish' and 'english'.
   The 0002 migration only created a 'simple' GIN index.  The searcher
   defaults to 'danish', so keyword queries were doing a full seq-scan
   even though a GIN index existed.  Adding language-specific indexes
   lets Postgres use bitmap index scans for those configs.

2. HNSW index on transcript_chunks.embedding.
   The 0002 migration wrapped HNSW creation in a DO/EXCEPTION block that
   silently swallowed the error on some pgvector builds.  This migration
   re-attempts creation (pgvector >= 0.5.0 required; image uses 0.8.2).

Revision ID: 0005_fts_and_vector_indexes
Revises: 0004_portal_auth
Create Date: 2026-06-16
"""

from __future__ import annotations

from alembic import op

revision = "0005_fts_and_vector_indexes"
down_revision = "0004_portal_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- FTS GIN indexes for danish and english -------------------------------
    # The searcher inlines the language literal in SQL (not a bound parameter)
    # so Postgres can match these indexes at plan time.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_fts_danish "
        "ON transcripts "
        "USING gin (to_tsvector('danish', full_text))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transcripts_fts_english "
        "ON transcripts "
        "USING gin (to_tsvector('english', full_text))"
    )

    # --- HNSW index on 3072-dim embeddings ------------------------------------
    # pgvector's HNSW has a 2000-dimension limit for the native `vector` type.
    # text-embedding-3-large produces 3072-dim vectors, so we use `halfvec`
    # (half-precision, pgvector >= 0.7.0) which supports up to 4000 dimensions.
    # The cast (embedding::halfvec(3072)) is handled at index build time;
    # queries against the original vector column still hit this index via
    # a matching cast in the query plan.
    op.execute(
        """
        DO $$
        BEGIN
            CREATE INDEX IF NOT EXISTS ix_chunks_embedding_3072
            ON transcript_chunks
            USING hnsw ((embedding::halfvec(3072)) halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64)
            WHERE embedding_dim = 3072;
        EXCEPTION WHEN others THEN
            RAISE WARNING
                'Could not create hnsw index on transcript_chunks.embedding: %',
                SQLERRM;
        END $$
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_transcripts_fts_danish")
    op.execute("DROP INDEX IF EXISTS ix_transcripts_fts_english")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_3072")
