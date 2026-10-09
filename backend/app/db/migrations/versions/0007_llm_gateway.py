"""llm gateway

Adds cached token and failover tracking to llm_usage, and the provider limits and failover
threshold as editable settings. The provider order setting seeded earlier is removed so that
LLM_PRIMARY from the environment is the default; an administrator can still override it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Published free tier limits for the Groq model, checked in the Groq documentation. They can
# change at any time and apply per organization, so they live in settings. Gemini limits depend
# on the model and the account and are read from Google AI Studio, so they start unset (JSON
# null) and are entered by an administrator.
GROQ_LIMITS = {"groq_rpm": 30, "groq_rpd": 1000, "groq_tpm": 8000, "groq_tpd": 200000}
GEMINI_LIMIT_KEYS = ("gemini_rpm", "gemini_rpd", "gemini_tpm", "gemini_tpd")


def upgrade() -> None:
    op.add_column(
        "llm_usage",
        sa.Column("cached_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("llm_usage", sa.Column("fallback_from", sa.String(length=30), nullable=True))
    op.create_index("ix_llm_usage_provider_created_at", "llm_usage", ["provider", "created_at"])

    op.execute("DELETE FROM app_settings WHERE key = 'llm_primary'")
    for key, value in GROQ_LIMITS.items():
        op.execute(
            sa.text("INSERT INTO app_settings (key, value) VALUES (:k, CAST(:v AS jsonb)) ON CONFLICT DO NOTHING").bindparams(
                k=key, v=str(value)
            )
        )
    for key in GEMINI_LIMIT_KEYS:
        op.execute(
            sa.text("INSERT INTO app_settings (key, value) VALUES (:k, 'null'::jsonb) ON CONFLICT DO NOTHING").bindparams(k=key)
        )


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in (*GROQ_LIMITS, *GEMINI_LIMIT_KEYS))
    op.execute(f"DELETE FROM app_settings WHERE key IN ({keys})")
    op.execute("INSERT INTO app_settings (key, value) VALUES ('llm_primary', '\"groq\"'::jsonb) ON CONFLICT DO NOTHING")
    op.drop_index("ix_llm_usage_provider_created_at", table_name="llm_usage")
    op.drop_column("llm_usage", "fallback_from")
    op.drop_column("llm_usage", "cached_tokens")
