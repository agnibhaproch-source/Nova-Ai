"""free plan: allow the vision model (BYOK users pay their own Groq usage; ADR 0001)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-24 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """UPDATE plans SET limits = jsonb_set(limits, '{models}', (limits->'models') || '["vision"]')
           WHERE key = 'free' AND NOT (limits->'models') ? 'vision'"""
    )


def downgrade() -> None:
    op.execute(
        """UPDATE plans SET limits = jsonb_set(limits, '{models}', (limits->'models') - 'vision')
           WHERE key = 'free'"""
    )
