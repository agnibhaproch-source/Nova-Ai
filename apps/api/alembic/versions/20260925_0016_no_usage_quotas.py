"""no usage quotas: every plan gets the same, most generous limits (ADR 0004)

Nova no longer caps messages, tokens, tool calls, voice minutes or uploads; the Groq API key's
own rate limits are the only ceiling. The count-based quota keys are dropped from
`plans.limits`, and the remaining capability settings are set to the former `pro` values for
every plan.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-25 12:00:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TOOLS = ["calculator", "file_search", "web_search", "code_execution"]
LIMITS = {
    # Replies are further bounded by each model's own output limit (config/models.yaml).
    "max_output_tokens": 65536,
    "max_message_chars": 100_000,
    "max_document_mb": 50,
    "max_image_mb": 10,
    "storage_mb": 10240,
    "max_pages_per_file": 1000,
    "max_extracted_tokens_per_file": 2_000_000,
    "code_timeout_seconds": 20,
    "models": ["primary", "fast", "vision"],
    "tools": TOOLS,
    "memory": True,
    "api_access": True,
}

# 0005 seed values (with 0015's vision on free), restored on downgrade.
_OLD = {
    "free": {
        "messages_per_day": 50,
        "monthly_token_quota": 500_000,
        "max_output_tokens": 2048,
        "max_message_chars": 8000,
        "max_document_mb": 10,
        "max_image_mb": 5,
        "uploads_per_day": 10,
        "storage_mb": 100,
        "max_pages_per_file": 100,
        "max_extracted_tokens_per_file": 200_000,
        "web_search_per_day": 10,
        "code_executions_per_day": 10,
        "code_timeout_seconds": 10,
        "voice_minutes_per_day": 5,
        "models": ["primary", "fast", "vision"],
        "tools": TOOLS,
        "memory": True,
        "api_access": False,
    },
    "plus": {
        "messages_per_day": 500,
        "monthly_token_quota": 5_000_000,
        "max_output_tokens": 4096,
        "max_message_chars": 32000,
        "max_document_mb": 25,
        "max_image_mb": 10,
        "uploads_per_day": 100,
        "storage_mb": 2048,
        "max_pages_per_file": 500,
        "max_extracted_tokens_per_file": 1_000_000,
        "web_search_per_day": 100,
        "code_executions_per_day": 100,
        "code_timeout_seconds": 10,
        "voice_minutes_per_day": 60,
        "models": ["primary", "fast", "vision"],
        "tools": TOOLS,
        "memory": True,
        "api_access": True,
    },
    "pro": {
        "messages_per_day": 2000,
        "monthly_token_quota": 20_000_000,
        "max_output_tokens": 8192,
        "max_message_chars": 32000,
        "max_document_mb": 50,
        "max_image_mb": 10,
        "uploads_per_day": 500,
        "storage_mb": 10240,
        "max_pages_per_file": 1000,
        "max_extracted_tokens_per_file": 2_000_000,
        "web_search_per_day": 500,
        "code_executions_per_day": 500,
        "code_timeout_seconds": 20,
        "voice_minutes_per_day": 180,
        "models": ["primary", "fast", "vision"],
        "tools": TOOLS,
        "memory": True,
        "api_access": True,
    },
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("UPDATE plans SET limits = CAST(:l AS jsonb)"), {"l": json.dumps(LIMITS)}
    )


def downgrade() -> None:
    conn = op.get_bind()
    for key, limits in _OLD.items():
        conn.execute(
            sa.text("UPDATE plans SET limits = CAST(:l AS jsonb) WHERE key = :k"),
            {"k": key, "l": json.dumps(limits)},
        )
