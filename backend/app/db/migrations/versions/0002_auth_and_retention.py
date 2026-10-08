"""authentication tables and retention support

Adds email verification and password change timestamps to users, one time auth
tokens, MFA recovery codes, the patient anonymization marker and retention settings.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = ("email_verification", "password_reset")

RETENTION_SETTINGS: dict[str, object] = {
    "chat_retention_days": 90,
    "guest_anonymize_months": 12,
}


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "patients", sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True)
    )

    labels = ", ".join(f"'{p}'" for p in PURPOSES)
    op.execute(f"CREATE TYPE auth_token_purpose AS ENUM ({labels})")

    op.create_table(
        "auth_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            postgresql.ENUM(*PURPOSES, name="auth_token_purpose", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index("ix_auth_tokens_user_id_purpose", "auth_tokens", ["user_id", "purpose"])

    op.create_table(
        "mfa_recovery_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_mfa_recovery_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mfa_recovery_codes")),
    )
    op.create_index("ix_mfa_recovery_codes_user_id", "mfa_recovery_codes", ["user_id"])

    settings = sa.table(
        "app_settings", sa.column("key", sa.String), sa.column("value", postgresql.JSONB)
    )
    op.bulk_insert(settings, [{"key": k, "value": v} for k, v in RETENTION_SETTINGS.items()])


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in RETENTION_SETTINGS)
    op.execute(f"DELETE FROM app_settings WHERE key IN ({keys})")
    op.drop_index("ix_mfa_recovery_codes_user_id", table_name="mfa_recovery_codes")
    op.drop_table("mfa_recovery_codes")
    op.drop_index("ix_auth_tokens_user_id_purpose", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.execute("DROP TYPE IF EXISTS auth_token_purpose")
    op.drop_column("patients", "anonymized_at")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "email_verified_at")
