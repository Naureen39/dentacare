"""booking support

Adds the late cancellation flag on appointments and the table that holds guest email
verification codes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "appointments",
        sa.Column("late_cancel", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "guest_verifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guest_verifications")),
    )
    op.create_index("ix_guest_verifications_email", "guest_verifications", ["email"])


def downgrade() -> None:
    op.drop_index("ix_guest_verifications_email", table_name="guest_verifications")
    op.drop_table("guest_verifications")
    op.drop_column("appointments", "late_cancel")
