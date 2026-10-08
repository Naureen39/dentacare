"""knowledge base indexing state

Tracks which content each document's chunks were embedded from, who manages a document, and
makes intent examples unique so seeding them is idempotent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("kb_documents", sa.Column("embedded_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "kb_documents", sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "kb_documents",
        sa.Column("managed_by", sa.String(length=10), server_default=sa.text("'file'"), nullable=False),
    )
    op.create_unique_constraint(
        op.f("uq_intent_examples_intent_text"), "intent_examples", ["intent", "text"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_intent_examples_intent_text"), "intent_examples", type_="unique")
    op.drop_column("kb_documents", "managed_by")
    op.drop_column("kb_documents", "embedded_at")
    op.drop_column("kb_documents", "embedded_hash")
