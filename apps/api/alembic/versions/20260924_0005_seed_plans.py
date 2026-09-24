"""seed plans (docs/35_USAGE_TRACKING.md §5)

Revision ID: 0005
Revises: 0004
"""

import json

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

TOOLS = ["calculator", "file_search", "web_search", "code_execution"]
PLANS = [
    (
        "free",
        "Free",
        "Get started with Nova.",
        0,
        0,
        {
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
            "models": ["primary", "fast"],
            "tools": TOOLS,
            "memory": True,
            "api_access": False,
        },
    ),
    (
        "plus",
        "Plus",
        "More messages, larger files, API access.",
        49900,
        1,
        {
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
    ),
    (
        "pro",
        "Pro",
        "Highest limits for power users.",
        149900,
        2,
        {
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
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    for key, name, desc, price, order, limits in PLANS:
        conn.execute(
            sa.text(
                "INSERT INTO plans (key, name, description, price_paise, sort_order, limits) "
                "VALUES (:k, :n, :d, :p, :o, CAST(:l AS jsonb)) ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "n": name, "d": desc, "p": price, "o": order, "l": json.dumps(limits)},
        )


def downgrade() -> None:
    op.execute("DELETE FROM plans WHERE key IN ('free','plus','pro')")
