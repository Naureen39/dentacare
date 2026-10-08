"""Billing desk: invoices, items, discounts, payments, PDFs and receivables."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import AppSettings, CurrentUser, Session, require_roles
from app.core.errors import AppError
from app.db.enums import InvoiceStatus, UserRole
from app.db.models import Appointment, Dentist, Invoice, Patient, Payment
from app.schemas.billing import (
    ArAgingBucketOut,
    ArAgingResponse,
    InvoiceItemCreate,
    InvoiceListItem,
    InvoiceOut,
    InvoiceUpdate,
    PaymentCreate,
    VoidRequest,
)
from app.services import audit, patients
from app.services.billing import BillingService, display_number, money
from app.services.invoice_pdf import render_invoice_pdf

router = APIRouter(prefix="/billing", tags=["billing"])

BillingReader = Annotated[
    CurrentUser,
    Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST)),
]
BillingWriter = Annotated[
    CurrentUser, Depends(require_roles(UserRole.ADMIN, UserRole.RECEPTIONIST))
]


def get_billing(request: Request, db: Session, settings: AppSettings) -> BillingService:
    return BillingService(db, settings, request)


Billing = Annotated[BillingService, Depends(get_billing)]


async def ensure_can_view(db: AsyncSession, current: CurrentUser, invoice: Invoice) -> None:
    """Dentists see only invoices for their own appointments, others as if missing."""
    if current.role is not UserRole.DENTIST:
        return
    own = await patients.dentist_id_for_user(db, current)
    owner = (
        await db.execute(
            select(Appointment.dentist_id).where(Appointment.id == invoice.appointment_id)
        )
    ).scalar_one_or_none()
    if own is None or owner != own:
        raise AppError("not_found", "Invoice not found.", 404)


async def pdf_response(
    db: AsyncSession, settings: AppSettings, billing: BillingService, invoice: Invoice
) -> Response:
    view = await billing.present(invoice)
    appointment = (
        await db.execute(select(Appointment).where(Appointment.id == invoice.appointment_id))
    ).scalar_one()
    dentist = (
        await db.execute(select(Dentist.full_name).where(Dentist.id == appointment.dentist_id))
    ).scalar_one_or_none()
    email = (
        await db.execute(select(Patient.email).where(Patient.id == invoice.patient_id))
    ).scalar_one_or_none()
    content = render_invoice_pdf(
        view,
        settings,
        service_date=appointment.slot.lower,
        dentist_name=dentist,
        bill_to_email=email,
    )
    filename = f"invoice-{display_number(invoice.number)}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- listing and detail --------------------------------------------------------------


@router.get("/invoices", response_model=list[InvoiceListItem])
async def list_invoices(
    request: Request,
    current: BillingReader,
    db: Session,
    status: InvoiceStatus | None = None,
    open_only: bool = False,
    patient_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvoiceListItem]:
    """Invoices newest first. ``open_only`` lists issued or partially paid invoices."""
    paid = (
        select(Payment.invoice_id, func.sum(Payment.amount).label("paid"))
        .group_by(Payment.invoice_id)
        .subquery()
    )
    paid_amount = func.coalesce(paid.c.paid, 0)
    stmt = (
        select(Invoice, Patient, paid_amount)
        .join(Patient, Patient.id == Invoice.patient_id)
        .outerjoin(paid, paid.c.invoice_id == Invoice.id)
        .order_by(Invoice.issued_at.desc(), Invoice.number.desc())
    )
    if status is not None:
        stmt = stmt.where(Invoice.status == status)
    if open_only:
        stmt = stmt.where(
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID]),
            Invoice.total - paid_amount > 0,
        )
    if patient_id is not None:
        stmt = stmt.where(Invoice.patient_id == patient_id)
    if q:
        term = q.strip()
        digits = term.upper().removeprefix("INV-").lstrip("0")
        stmt = stmt.where(
            or_(
                Patient.last_name.ilike(f"{term}%"),
                Patient.first_name.ilike(f"{term}%"),
                Patient.last_name.op("%")(term),
                Invoice.number == int(digits) if digits.isdigit() else text("false"),
            )
        )
    if current.role is UserRole.DENTIST:
        own = await patients.dentist_id_for_user(db, current)
        if own is None:
            return []
        stmt = stmt.join(Appointment, Appointment.id == Invoice.appointment_id).where(
            Appointment.dentist_id == own
        )
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    await audit.record(
        db,
        "invoice.list",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="invoice",
        metadata={"results": len(rows)},
    )
    await db.commit()
    return [
        InvoiceListItem(
            id=inv.id,
            number=inv.number,
            display_number=display_number(inv.number),
            patient_id=inv.patient_id,
            patient_name=f"{patient.first_name} {patient.last_name}",
            issued_at=inv.issued_at,
            status=inv.status,
            total=inv.total,
            paid=money(amount_paid),
            balance=money(inv.total - amount_paid),
        )
        for inv, patient, amount_paid in rows
    ]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: uuid.UUID, request: Request, current: BillingReader, db: Session, billing: Billing
) -> InvoiceOut:
    invoice = await billing.get(invoice_id)
    await ensure_can_view(db, current, invoice)
    await audit.record(
        db,
        "invoice.view",
        request=request,
        actor_id=current.id,
        actor_role=current.role.value,
        entity="invoice",
        entity_id=invoice.id,
    )
    await db.commit()
    return await billing.present(invoice)


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: uuid.UUID,
    current: BillingReader,
    db: Session,
    settings: AppSettings,
    billing: Billing,
) -> Response:
    invoice = await billing.get(invoice_id)
    await ensure_can_view(db, current, invoice)
    return await pdf_response(db, settings, billing, invoice)


# --- editing -------------------------------------------------------------------------


@router.patch("/invoices/{invoice_id}", response_model=InvoiceOut)
async def update_invoice(
    invoice_id: uuid.UUID,
    body: InvoiceUpdate,
    current: BillingWriter,
    db: Session,
    billing: Billing,
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)
    await billing.update(invoice, body, current)
    await db.commit()
    return await billing.present(invoice)


@router.post("/invoices/{invoice_id}/items", response_model=InvoiceOut, status_code=201)
async def add_item(
    invoice_id: uuid.UUID,
    body: InvoiceItemCreate,
    current: BillingWriter,
    db: Session,
    billing: Billing,
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)
    await billing.add_item(invoice, body, current)
    await db.commit()
    return await billing.present(invoice)


@router.delete("/invoices/{invoice_id}/items/{item_id}", response_model=InvoiceOut)
async def remove_item(
    invoice_id: uuid.UUID, item_id: uuid.UUID, current: BillingWriter, db: Session, billing: Billing
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)
    await billing.remove_item(invoice, item_id, current)
    await db.commit()
    return await billing.present(invoice)


@router.post("/invoices/{invoice_id}/issue", response_model=InvoiceOut)
async def issue_invoice(
    invoice_id: uuid.UUID, current: BillingWriter, db: Session, billing: Billing
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)
    await billing.issue(invoice, current)
    await db.commit()
    return await billing.present(invoice)


@router.post("/invoices/{invoice_id}/void", response_model=InvoiceOut)
async def void_invoice(
    invoice_id: uuid.UUID, body: VoidRequest, current: BillingWriter, db: Session, billing: Billing
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)
    await billing.void(invoice, current, body.reason)
    await db.commit()
    return await billing.present(invoice)


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceOut, status_code=201)
async def record_payment(
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    current: BillingWriter,
    db: Session,
    billing: Billing,
) -> InvoiceOut:
    invoice = await billing.get(invoice_id, lock=True)  # serializes concurrent payments
    await billing.record_payment(
        invoice,
        current,
        amount=body.amount,
        method=body.method,
        reference=body.reference,
        paid_at=body.paid_at,
        card=body.card,
    )
    await db.commit()
    return await billing.present(invoice)


# --- receivables ---------------------------------------------------------------------


@router.get("/ar-aging", response_model=ArAgingResponse)
async def ar_aging(current: BillingWriter, db: Session) -> ArAgingResponse:
    rows = (await db.execute(text("SELECT * FROM ar_aging_summary"))).mappings().all()
    buckets = [
        ArAgingBucketOut(
            bucket=r["bucket"],
            invoices=r["invoices"],
            balance=r["balance"],
            insurance_outstanding=r["insurance_outstanding"],
            patient_outstanding=r["patient_outstanding"],
        )
        for r in rows
    ]
    return ArAgingResponse(
        buckets=buckets, total_balance=money(sum((b.balance for b in buckets), money(0)))
    )
