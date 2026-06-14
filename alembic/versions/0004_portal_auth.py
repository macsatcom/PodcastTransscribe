"""portal auth: per-portal optional username/password

Adds auth_enabled / auth_username / auth_password_hash to the portals table.
Idempotent (ADD COLUMN IF NOT EXISTS) so it is safe on fresh databases where
create_all already produced the columns and on legacy databases alike.

Revision ID: 0004_portal_auth
Revises: 0003_episode_perf_indexes
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0004_portal_auth"
down_revision = "0003_episode_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portals "
        "ADD COLUMN IF NOT EXISTS auth_enabled BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE portals ADD COLUMN IF NOT EXISTS auth_username TEXT")
    op.execute("ALTER TABLE portals ADD COLUMN IF NOT EXISTS auth_password_hash TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_password_hash")
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_username")
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_enabled")
