"""staff and admin console

Dated price changes for services, front desk notes about patients, and the dentist's encrypted
clinical note on an appointment.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_price_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("services.id", ondelete="CASCADE"), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("price >= 0", name=op.f("ck_service_price_changes_price_non_negative")),
    )
    op.create_index("ix_service_price_changes_service_id", "service_price_changes", ["service_id", "effective_from"])

    op.create_table(
        "patient_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("body_enc", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_patient_notes_patient_id", "patient_notes", ["patient_id", "created_at"])

    op.add_column("appointments", sa.Column("clinical_note_enc", sa.Text()))


def downgrade() -> None:
    op.drop_column("appointments", "clinical_note_enc")
    op.drop_index("ix_patient_notes_patient_id", table_name="patient_notes")
    op.drop_table("patient_notes")
    op.drop_index("ix_service_price_changes_service_id", table_name="service_price_changes")
    op.drop_table("service_price_changes")
