"""initial baseline (legacy create_all schema)

This migration is intentionally a no-op. It exists so that databases produced
by the pre-Alembic ``Base.metadata.create_all()`` lifespan hook can be stamped
to a known revision and then participate in normal Alembic upgrades.

For an existing deployment, run once:
    alembic stamp 0001_initial

For fresh deployments, ``app/main.py`` lifespan calls ``create_all`` followed
by ``alembic upgrade head``; the idempotent guards in 0002 make that safe.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-29
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op: represents the legacy create_all schema."""
    pass


def downgrade() -> None:
    """No-op: cannot downgrade past the baseline."""
    pass
