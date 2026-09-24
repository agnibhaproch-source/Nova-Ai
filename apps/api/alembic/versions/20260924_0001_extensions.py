"""extensions

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    for ext in ("pgcrypto", "citext", "pg_trgm", "vector"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {ext}")


def downgrade() -> None:
    pass  # extensions are left in place (shared, harmless)
