"""Invoices, discounts, payments and derived invoice status.

All money is ``Decimal`` and every stored amount is rounded half up to cents. The invoice
total is always ``subtotal - discount + tax`` where the subtotal is the sum of the line
amounts, and the database enforces the same identity. Invoice status follows the payments:
issued with no payment, partially paid, then paid; draft and void are set explicitly.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.deps import CurrentUser
from app.core.errors import AppError
from app.db.enums import InvoiceStatus, PayerType, PaymentMethod, UserRole
from app.db.models import Appointment, Invoice, InvoiceItem, Patient, Payment, Service
from app.schemas.billing import (
    CardDetails,
    InvoiceItemCreate,
    InvoiceItemOut,
    InvoiceOut,
    InvoiceUpdate,
    PaymentOut,
)
from app.services import audit, sandbox_payments
from app.services.app_settings import get_setting

CENT = Decimal("0.01")
HUNDRED = Decimal(100)


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def display_number(number: int) -> str:
    return f"INV-{number:06d}"


@dataclass(frozen=True)
class Totals:
    paid: Decimal
    patient_paid: Decimal
    insurer_paid: Decimal

    def balance(self, total: Decimal) -> Decimal:
        return money(total - self.paid)


class BillingService:
    def __init__(
        self, db: AsyncSession, settings: Settings, request: Request | None = None
    ) -> None:
        self.db = db
        self.settings = settings
        self.request = request

    # --- loading --------------------------------------------------------------------

    async def get(self, invoice_id: uuid.UUID, *, lock: bool = False) -> Invoice:
        stmt = select(Invoice).where(Invoice.id == invoice_id)
        if lock:
            stmt = stmt.with_for_update()
        invoice = (await self.db.execute(stmt)).scalar_one_or_none()
        if invoice is None:
            raise AppError("not_found", "Invoice not found.", 404)
        return invoice

    async def totals(self, invoice_id: uuid.UUID) -> Totals:
        rows = (
            await self.db.execute(
                select(Payment.payer_type, func.coalesce(func.sum(Payment.amount), 0))
                .where(Payment.invoice_id == invoice_id)
                .group_by(Payment.payer_type)
            )
        ).all()
        by_payer = {payer: Decimal(total) for payer, total in rows}
        patient = by_payer.get(PayerType.PATIENT, Decimal(0))
        insurer = by_payer.get(PayerType.INSURER, Decimal(0))
        return Totals(money(patient + insurer), money(patient), money(insurer))

    # --- creation -------------------------------------------------------------------

    async def create_for_appointment(
        self, appointment: Appointment, actor: CurrentUser | None
    ) -> Invoice:
        """Create the draft invoice for a completed visit, once."""
        existing = (
            await self.db.execute(
                select(Invoice).where(
                    Invoice.appointment_id == appointment.id,
                    Invoice.status != InvoiceStatus.VOID,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

        service = (
            await self.db.execute(select(Service).where(Service.id == appointment.service_id))
        ).scalar_one()
        invoice = Invoice(
            appointment_id=appointment.id,
            patient_id=appointment.patient_id,
            subtotal=Decimal(0),
            total=Decimal(0),
            status=InvoiceStatus.DRAFT,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(invoice)
                await self.db.flush()
        except IntegrityError:
            # A concurrent completion created it first.
            return (
                await self.db.execute(
                    select(Invoice).where(
                        Invoice.appointment_id == appointment.id,
                        Invoice.status != InvoiceStatus.VOID,
                    )
                )
            ).scalar_one()
        self.db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                service_id=service.id,
                description=service.name,
                qty=1,
                unit_price=money(service.base_price),
                amount=money(service.base_price),
            )
        )
        await self.db.flush()
        await self.recompute(invoice)
        await self._audit("invoice.create", invoice, actor, {"source": "completed_visit"})
        return invoice

    # --- totals ---------------------------------------------------------------------

    async def _tax_rate(self) -> Decimal:
        return Decimal(str(await get_setting(self.db, "billing_tax_rate_percent", 0)))

    async def recompute(self, invoice: Invoice) -> None:
        """Rebuild subtotal, tax and total from the line items and keep status consistent.

        Reads run without autoflush: the caller may already have changed the discount, and
        flushing that before the total is rebuilt would violate the database identity
        ``total = subtotal - discount + tax``.
        """
        with self.db.no_autoflush:
            subtotal = money(
                (
                    await self.db.execute(
                        select(func.coalesce(func.sum(InvoiceItem.amount), 0)).where(
                            InvoiceItem.invoice_id == invoice.id
                        )
                    )
                ).scalar_one()
            )
            rate = await self._tax_rate()
        discount = money(invoice.discount)
        if discount > subtotal:
            raise AppError(
                "invalid_discount", "The discount cannot be larger than the subtotal.", 422
            )
        tax = money((subtotal - discount) * rate / HUNDRED)
        total = money(subtotal - discount + tax)
        if money(invoice.insurance_expected) > total:
            raise AppError(
                "invalid_insurance_amount",
                "The expected insurance payment cannot exceed the invoice total.",
                422,
            )
        invoice.subtotal, invoice.tax, invoice.total = subtotal, tax, total
        await self.db.flush()
        await self.refresh_status(invoice)

    async def refresh_status(self, invoice: Invoice) -> None:
        if invoice.status in (InvoiceStatus.DRAFT, InvoiceStatus.VOID):
            return
        paid = (await self.totals(invoice.id)).paid
        if paid >= invoice.total:
            invoice.status = InvoiceStatus.PAID
        elif paid > 0:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
        else:
            invoice.status = InvoiceStatus.ISSUED

    # --- editing a draft ------------------------------------------------------------

    def _require_draft(self, invoice: Invoice) -> None:
        if invoice.status is not InvoiceStatus.DRAFT:
            raise AppError(
                "invoice_locked",
                "Only draft invoices can be edited. Void the invoice to replace it.",
                409,
            )

    async def add_item(
        self, invoice: Invoice, data: InvoiceItemCreate, actor: CurrentUser
    ) -> InvoiceItem:
        self._require_draft(invoice)
        unit_price = money(data.unit_price)
        item = InvoiceItem(
            invoice_id=invoice.id,
            service_id=data.service_id,
            description=data.description,
            qty=data.qty,
            unit_price=unit_price,
            amount=money(unit_price * data.qty),
        )
        self.db.add(item)
        await self.db.flush()
        await self.recompute(invoice)
        await self._enforce_discount_limit(invoice, actor)
        await self._audit("invoice.item_add", invoice, actor, {"qty": data.qty})
        return item

    async def remove_item(self, invoice: Invoice, item_id: uuid.UUID, actor: CurrentUser) -> None:
        self._require_draft(invoice)
        item = (
            await self.db.execute(
                select(InvoiceItem).where(
                    InvoiceItem.id == item_id, InvoiceItem.invoice_id == invoice.id
                )
            )
        ).scalar_one_or_none()
        if item is None:
            raise AppError("not_found", "Invoice item not found.", 404)
        await self.db.delete(item)
        await self.db.flush()
        await self.recompute(invoice)
        await self._enforce_discount_limit(invoice, actor)
        await self._audit("invoice.item_remove", invoice, actor, {})

    async def update(self, invoice: Invoice, data: InvoiceUpdate, actor: CurrentUser) -> None:
        provided = data.model_fields_set
        if {"discount_amount", "discount_percent"} <= provided and (
            data.discount_amount is not None and data.discount_percent is not None
        ):
            raise AppError(
                "validation_error", "Give a discount amount or a percentage, not both.", 422
            )
        changes: list[str] = []
        if "insurance_expected" in provided and data.insurance_expected is not None:
            if invoice.status in (InvoiceStatus.VOID, InvoiceStatus.PAID):
                raise AppError(
                    "invoice_locked", "The expected insurance payment can no longer change.", 409
                )
            invoice.insurance_expected = money(data.insurance_expected)
            changes.append("insurance_expected")

        discount_given = "discount_amount" in provided or "discount_percent" in provided
        if discount_given:
            self._require_draft(invoice)
            if data.discount_percent is not None:
                new_discount = money(money(invoice.subtotal) * data.discount_percent / HUNDRED)
            else:
                new_discount = money(data.discount_amount or Decimal(0))
            invoice.discount = new_discount
            changes.append("discount")
        if "discount_reason" in provided:
            self._require_draft(invoice)
            invoice.discount_reason = (data.discount_reason or "").strip() or None
            changes.append("discount_reason")
        if money(invoice.discount) == 0:
            invoice.discount_reason = None
        elif not invoice.discount_reason:
            raise AppError(
                "discount_reason_required", "A reason is required when applying a discount.", 422
            )

        await self.recompute(invoice)
        await self._enforce_discount_limit(invoice, actor)
        await self._audit(
            "invoice.update", invoice, actor, {"fields": changes, "discount": str(invoice.discount)}
        )

    async def _enforce_discount_limit(self, invoice: Invoice, actor: CurrentUser) -> None:
        """Receptionists may discount up to a configured percentage; administrators any amount."""
        if actor.role is UserRole.ADMIN or money(invoice.discount) == 0:
            return
        limit = Decimal(str(await get_setting(self.db, "receptionist_max_discount_percent", 10)))
        subtotal = money(invoice.subtotal)
        percent = (money(invoice.discount) / subtotal * HUNDRED) if subtotal > 0 else HUNDRED
        if percent > limit:
            raise AppError(
                "discount_limit_exceeded",
                f"Discounts above {limit}% need an administrator.",
                403,
                {"limit_percent": str(limit), "requested_percent": str(percent.quantize(CENT))},
            )

    # --- lifecycle ------------------------------------------------------------------

    async def issue(self, invoice: Invoice, actor: CurrentUser) -> None:
        self._require_draft(invoice)
        count = (
            await self.db.execute(
                select(func.count())
                .select_from(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice.id)
            )
        ).scalar_one()
        if count == 0:
            raise AppError("invoice_empty", "Add at least one item before issuing.", 422)
        invoice.status = InvoiceStatus.ISSUED
        invoice.issued_at = datetime.now(UTC)
        await self.refresh_status(invoice)  # a fully discounted invoice is paid on issue
        await self._audit("invoice.issue", invoice, actor, {"total": str(invoice.total)})

    async def void(self, invoice: Invoice, actor: CurrentUser, reason: str) -> None:
        if invoice.status is InvoiceStatus.VOID:
            raise AppError("invoice_locked", "The invoice is already void.", 409)
        if (await self.totals(invoice.id)).paid > 0:
            raise AppError(
                "invoice_has_payments",
                "An invoice with payments cannot be voided.",
                409,
            )
        invoice.status = InvoiceStatus.VOID
        invoice.voided_at = datetime.now(UTC)
        invoice.void_reason = reason
        await self._audit("invoice.void", invoice, actor, {"was_draft": False})

    # --- payments -------------------------------------------------------------------

    async def record_payment(
        self,
        invoice: Invoice,
        actor: CurrentUser,
        *,
        amount: Decimal,
        method: PaymentMethod,
        reference: str | None,
        paid_at: datetime | None,
        card: CardDetails | None,
    ) -> Payment:
        """Record a payment. The caller must hold the invoice row lock."""
        if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
            raise AppError(
                "invoice_not_payable",
                f"A {invoice.status.value} invoice cannot receive payments.",
                409,
            )
        amount = money(amount)
        balance = (await self.totals(invoice.id)).balance(invoice.total)
        if amount > balance:
            raise AppError(
                "overpayment",
                "The payment is larger than the remaining balance.",
                422,
                {"balance": str(balance)},
            )
        payer = PayerType.INSURER if method is PaymentMethod.INSURANCE else PayerType.PATIENT
        if payer is PayerType.INSURER and actor.role is UserRole.PATIENT:
            raise AppError("forbidden", "Only staff can record insurance payments.", 403)
        if paid_at is not None and paid_at > datetime.now(UTC):
            raise AppError("validation_error", "The payment date cannot be in the future.", 422)

        last4: str | None = None
        sandbox = False
        if method is PaymentMethod.CARD:
            if card is None:
                raise AppError("validation_error", "Card details are required.", 422)
            try:
                result = sandbox_payments.charge(
                    card.card_number.get_secret_value(),
                    card.exp_month,
                    card.exp_year,
                    card.cvv.get_secret_value(),
                )
            except sandbox_payments.CardValidationError as exc:
                raise AppError(
                    "invalid_card",
                    exc.message,
                    422,
                    [{"field": exc.field, "message": exc.message}],
                ) from exc
            if not result.approved:
                await self._audit("payment.declined", invoice, actor, {"sandbox": True})
                await self.db.commit()
                raise AppError("card_declined", result.decline_message or "Card declined.", 402)
            reference, last4, sandbox = result.reference, result.last4, True
        elif card is not None:
            raise AppError("validation_error", "Card details apply to card payments only.", 422)

        payment = Payment(
            invoice_id=invoice.id,
            amount=amount,
            method=method,
            payer_type=payer,
            paid_at=paid_at or datetime.now(UTC),
            reference=reference,
            card_last4=last4,
            sandbox=sandbox,
            recorded_by=actor.id,
        )
        self.db.add(payment)
        await self.db.flush()
        await self.refresh_status(invoice)
        await self._audit(
            "payment.record",
            invoice,
            actor,
            {"method": method.value, "payer": payer.value, "amount": str(amount)},
        )
        return payment

    # --- presentation ---------------------------------------------------------------

    async def present(self, invoice: Invoice) -> InvoiceOut:
        items = (
            (
                await self.db.execute(
                    select(InvoiceItem)
                    .where(InvoiceItem.invoice_id == invoice.id)
                    .order_by(InvoiceItem.created_at, InvoiceItem.id)
                )
            )
            .scalars()
            .all()
        )
        payments = (
            (
                await self.db.execute(
                    select(Payment)
                    .where(Payment.invoice_id == invoice.id)
                    .order_by(Payment.paid_at)
                )
            )
            .scalars()
            .all()
        )
        patient = (
            await self.db.execute(select(Patient).where(Patient.id == invoice.patient_id))
        ).scalar_one()
        totals = await self.totals(invoice.id)
        return InvoiceOut(
            id=invoice.id,
            number=invoice.number,
            display_number=display_number(invoice.number),
            appointment_id=invoice.appointment_id,
            patient_id=invoice.patient_id,
            patient_name=f"{patient.first_name} {patient.last_name}",
            issued_at=invoice.issued_at,
            status=invoice.status,
            subtotal=invoice.subtotal,
            discount=invoice.discount,
            discount_reason=invoice.discount_reason,
            tax=invoice.tax,
            total=invoice.total,
            insurance_expected=invoice.insurance_expected,
            patient_responsibility=money(invoice.total - invoice.insurance_expected),
            paid=totals.paid,
            balance=totals.balance(invoice.total),
            void_reason=invoice.void_reason,
            items=[InvoiceItemOut.model_validate(i, from_attributes=True) for i in items],
            payments=[
                PaymentOut(
                    id=p.id,
                    amount=p.amount,
                    method=p.method,
                    payer_type=p.payer_type.value,
                    paid_at=p.paid_at,
                    reference=p.reference,
                    card_last4=p.card_last4,
                    sandbox=p.sandbox,
                )
                for p in payments
            ],
        )

    async def _audit(
        self, action: str, invoice: Invoice, actor: CurrentUser | None, metadata: dict[str, object]
    ) -> None:
        await audit.record(
            self.db,
            action,
            request=self.request,
            actor_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            entity="invoice",
            entity_id=invoice.id,
            metadata=metadata,
        )
