"""notifications and background jobs

Adds delivery tracking to reminders, the one time appointment action links used by reminder
emails, and the follow up and recall timing settings.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIONS = ("confirm", "cancel")
SETTINGS: dict[str, object] = {"reminder_followup_days": 2, "reminder_recall_months": 6}


def upgrade() -> None:
    op.add_column(
        "reminders",
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "reminders", sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True)
    )

    labels = ", ".join(f"'{a}'" for a in ACTIONS)
    op.execute(f"CREATE TYPE appointment_action AS ENUM ({labels})")
    op.create_table(
        "appointment_action_tokens",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("appointment_id", sa.UUID(), nullable=False),
        sa.Column("reminder_id", sa.UUID(), nullable=True),
        sa.Column(
            "action",
            postgresql.ENUM(*ACTIONS, name="appointment_action", create_type=False),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["appointment_id"],
            ["appointments.id"],
            name=op.f("fk_appointment_action_tokens_appointment_id_appointments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reminder_id"],
            ["reminders.id"],
            name=op.f("fk_appointment_action_tokens_reminder_id_reminders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_appointment_action_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_appointment_action_tokens_token_hash")),
    )
    op.create_index(
        "ix_appointment_action_tokens_appointment_id",
        "appointment_action_tokens",
        ["appointment_id"],
    )

    settings = sa.table(
        "app_settings", sa.column("key", sa.String), sa.column("value", postgresql.JSONB)
    )
    op.bulk_insert(settings, [{"key": k, "value": v} for k, v in SETTINGS.items()])


def downgrade() -> None:
    keys = ", ".join(f"'{k}'" for k in SETTINGS)
    op.execute(f"DELETE FROM app_settings WHERE key IN ({keys})")
    op.drop_index(
        "ix_appointment_action_tokens_appointment_id", table_name="appointment_action_tokens"
    )
    op.drop_table("appointment_action_tokens")
    op.execute("DROP TYPE IF EXISTS appointment_action")
    op.drop_column("reminders", "last_attempt_at")
    op.drop_column("reminders", "attempts")
