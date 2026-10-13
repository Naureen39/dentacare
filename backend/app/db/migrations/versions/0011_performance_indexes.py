"""indexes found missing by EXPLAIN ANALYZE

The invoice of an appointment is read on every completion, receipt and payment, and had no index
on its appointment. The staff schedule asks for every appointment that overlaps a day, which the
per dentist index cannot answer.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_invoices_appointment_id", "invoices", ["appointment_id"])
    op.create_index("ix_appointments_slot_gist", "appointments", ["slot"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_appointments_slot_gist", table_name="appointments")
    op.drop_index("ix_invoices_appointment_id", table_name="invoices")
