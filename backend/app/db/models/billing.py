import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Sequence,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, pg_enum, uuid_pk
from app.db.enums import InvoiceStatus, PayerType, PaymentMethod

invoice_number_seq = Sequence("invoice_number_seq", start=1000, metadata=Base.metadata)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "subtotal >= 0 AND discount >= 0 AND tax >= 0", name="amounts_non_negative"
        ),
        CheckConstraint("discount <= subtotal", name="discount_within_subtotal"),
        CheckConstraint("total = subtotal - discount + tax", name="total_matches_components"),
        CheckConstraint("insurance_expected >= 0", name="insurance_non_negative"),
        # A voided invoice may be replaced, so uniqueness applies to live invoices only.
        Index(
            "uq_invoices_live_appointment",
            "appointment_id",
            unique=True,
            postgresql_where=text("status <> 'void'"),
        ),
        Index("ix_invoices_issued_at", "issued_at"),
        Index("ix_invoices_patient_id", "patient_id"),
        Index("ix_invoices_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[int] = mapped_column(
        BigInteger, invoice_number_seq, unique=True, server_default=invoice_number_seq.next_value()
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default=text("0"), nullable=False
    )
    tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    insurance_expected: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), server_default=text("0"), nullable=False
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        pg_enum(InvoiceStatus, "invoice_status"), server_default=text("'draft'"), nullable=False
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("qty > 0", name="qty_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint("amount = round(qty * unit_price, 2)", name="amount_matches_qty_price"),
        Index("ix_invoice_items_invoice_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL")
    )
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, server_default=text("1"), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_payments_paid_at", "paid_at"),
        Index("ix_payments_invoice_id", "invoice_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        pg_enum(PaymentMethod, "payment_method"), nullable=False
    )
    payer_type: Mapped[PayerType] = mapped_column(pg_enum(PayerType, "payer_type"), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reference: Mapped[str | None] = mapped_column(Text)
