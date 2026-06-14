"""initial baseline (legacy create_all schema)

This migration creates the baseline tables from SQLAlchemy metadata for fresh
databases. It also remains compatible with legacy databases that were created
via the pre-Alembic ``Base.metadata.create_all()`` path and then stamped.

For an existing deployment, run once:
    alembic stamp 0001_initial

For fresh deployments, ``app/main.py`` lifespan calls ``create_all`` followed
by ``alembic upgrade head``; the idempotent guards in 0002 make that safe.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-29
"""

from __future__ import annotations

from alembic import op

from app.database import Base

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the baseline schema for fresh databases.

    This preserves compatibility with legacy deployments that were stamped to
    ``0001_initial`` after ``create_all`` while allowing a clean
    ``alembic upgrade head`` to work on an empty database.
    """
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """No-op: cannot downgrade past the baseline."""
    pass
