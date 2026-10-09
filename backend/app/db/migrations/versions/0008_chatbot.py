"""chatbot

Adds what the chat orchestration records per assistant reply: how many model calls it took,
the controls shown with it, and the visitor's thumbs up or down.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("llm_calls", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("chat_messages", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.add_column("chat_messages", sa.Column("feedback", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_chat_messages_feedback_value", "chat_messages", "feedback IN (-1, 1)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_chat_messages_feedback_value", "chat_messages", type_="check")
    op.drop_column("chat_messages", "feedback")
    op.drop_column("chat_messages", "payload")
    op.drop_column("chat_messages", "llm_calls")
