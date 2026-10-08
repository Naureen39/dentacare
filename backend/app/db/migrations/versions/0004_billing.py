"""billing and payments

Adds discount, void and payment detail columns, integrity constraints that keep invoice
amounts consistent, the accounts receivable aging views and the tax rate setting.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Age is counted in whole UTC days from the issue date. Only issued and partially paid
# invoices with a remaining balance appear. The insurer share of the balance is whatever is
# still expected from the insurer, capped at the balance; the rest is the patient's share.
AR_AGING_VIEW = """
CREATE VIEW ar_aging AS
WITH paid AS (
    SELECT invoice_id,
           SUM(amount) AS paid,
           SUM(amount) FILTER (WHERE payer_type = 'insurer') AS insurer_paid
    FROM payments
    GROUP BY invoice_id
),
open_invoices AS (
    SELECT i.id AS invoice_id,
           i.number,
           i.patient_id,
           i.issued_at,
           i.total,
           i.insurance_expected,
           COALESCE(p.paid, 0) AS paid,
           i.total - COALESCE(p.paid, 0) AS balance,
           COALESCE(p.insurer_paid, 0) AS insurer_paid,
           GREATEST(0, (now() AT TIME ZONE 'UTC')::date - (i.issued_at AT TIME ZONE 'UTC')::date)
               AS days_outstanding
    FROM invoices i
    LEFT JOIN paid p ON p.invoice_id = i.id
    WHERE i.status IN ('issued', 'partially_paid')
)
SELECT invoice_id,
       number,
       patient_id,
       issued_at,
       total,
       paid,
       balance,
       LEAST(balance, GREATEST(0, insurance_expected - insurer_paid)) AS insurance_outstanding,
       balance - LEAST(balance, GREATEST(0, insurance_expected - insurer_paid))
           AS patient_outstanding,
       days_outstanding,
       CASE
           WHEN days_outstanding <= 30 THEN '0_30'
           WHEN days_outstanding <= 60 THEN '31_60'
           WHEN days_outstanding <= 90 THEN '61_90'
           ELSE 'over_90'
       END AS bucket
FROM open_invoices
WHERE balance > 0
"""

AR_AGING_SUMMARY_VIEW = """
CREATE VIEW ar_aging_summary AS
SELECT b.bucket,
       COUNT(a.invoice_id) AS invoices,
       COALESCE(SUM(a.balance), 0)::numeric(12, 2) AS balance,
       COALESCE(SUM(a.insurance_outstanding), 0)::numeric(12, 2) AS insurance_outstanding,
       COALESCE(SUM(a.patient_outstanding), 0)::numeric(12, 2) AS patient_outstanding
FROM (VALUES ('0_30', 1), ('31_60', 2), ('61_90', 3), ('over_90', 4)) AS b(bucket, position)
LEFT JOIN ar_aging a ON a.bucket = b.bucket
GROUP BY b.bucket, b.position
ORDER BY b.position
"""


def upgrade() -> None:
    op.add_column("invoices", sa.Column("discount_reason", sa.String(length=300), nullable=True))
    op.add_column("invoices", sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("invoices", sa.Column("void_reason", sa.String(length=300), nullable=True))
    op.create_check_constraint(
        op.f("ck_invoices_insurance_within_total"), "invoices", "insurance_expected <= total"
    )
    op.create_check_constraint(
        op.f("ck_invoices_discount_needs_reason"),
        "invoices",
        "discount = 0 OR discount_reason IS NOT NULL",
    )

    op.add_column(
        "invoice_items",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
    )

    op.add_column("payments", sa.Column("card_last4", sa.String(length=4), nullable=True))
    op.add_column(
        "payments",
        sa.Column("sandbox", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("payments", sa.Column("recorded_by", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_payments_recorded_by_users"),
        "payments",
        "users",
        ["recorded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        op.f("ck_payments_method_matches_payer"),
        "payments",
        "(method = 'insurance') = (payer_type = 'insurer')",
    )
    op.create_check_constraint(
        op.f("ck_payments_card_last4_format"),
        "payments",
        "card_last4 IS NULL OR (method = 'card' AND card_last4 ~ '^[0-9]{4}$')",
    )

    op.execute(AR_AGING_VIEW)
    op.execute(AR_AGING_SUMMARY_VIEW)

    settings = sa.table(
        "app_settings", sa.column("key", sa.String), sa.column("value", postgresql.JSONB)
    )
    op.bulk_insert(settings, [{"key": "billing_tax_rate_percent", "value": 0}])


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'billing_tax_rate_percent'")
    op.execute("DROP VIEW IF EXISTS ar_aging_summary")
    op.execute("DROP VIEW IF EXISTS ar_aging")
    op.drop_constraint(op.f("ck_payments_card_last4_format"), "payments", type_="check")
    op.drop_constraint(op.f("ck_payments_method_matches_payer"), "payments", type_="check")
    op.drop_constraint(op.f("fk_payments_recorded_by_users"), "payments", type_="foreignkey")
    op.drop_column("payments", "recorded_by")
    op.drop_column("payments", "sandbox")
    op.drop_column("payments", "card_last4")
    op.drop_constraint(op.f("ck_invoices_discount_needs_reason"), "invoices", type_="check")
    op.drop_constraint(op.f("ck_invoices_insurance_within_total"), "invoices", type_="check")
    op.drop_column("invoice_items", "created_at")
    op.drop_column("invoices", "void_reason")
    op.drop_column("invoices", "voided_at")
    op.drop_column("invoices", "discount_reason")
