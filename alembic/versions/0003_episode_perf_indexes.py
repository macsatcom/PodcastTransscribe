"""episode performance indexes for podcast detail pagination

Adds a composite index supporting:
WHERE episodes.podcast_id = :podcast_id
ORDER BY episodes.published_at DESC

Revision ID: 0003_episode_perf_indexes
Revises: 0002_search_insights_v2
Create Date: 2026-06-12
"""
from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_episode_perf_indexes"
down_revision = "0002_search_insights_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episodes_podcast_published "
        "ON episodes (podcast_id, published_at DESC NULLS LAST)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_episodes_podcast_published")
