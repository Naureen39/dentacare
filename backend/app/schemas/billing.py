import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field, SecretStr

from app.db.enums import InvoiceStatus, PaymentMethod
from app.schemas.auth import StrictModel

Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
NonNegativeMoney = Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]


# --- responses -----------------------------------------------------------------------


class InvoiceItemOut(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID | None
    description: str
    qty: int
    unit_price: Money
    amount: Money


class PaymentOut(BaseModel):
    id: uuid.UUID
    amount: Money
    method: PaymentMethod
    payer_type: str
    paid_at: datetime
    reference: str | None
    card_last4: str | None
    sandbox: bool


class InvoiceOut(BaseModel):
    id: uuid.UUID
    number: int
    display_number: str
    appointment_id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str
    issued_at: datetime
    status: InvoiceStatus
    subtotal: Money
    discount: Money
    discount_reason: str | None
    tax: Money
    total: Money
    insurance_expected: Money
    patient_responsibility: Money
    paid: Money
    balance: Money
    void_reason: str | None
    items: list[InvoiceItemOut]
    payments: list[PaymentOut]


class InvoiceListItem(BaseModel):
    id: uuid.UUID
    number: int
    display_number: str
    patient_id: uuid.UUID
    patient_name: str
    issued_at: datetime
    status: InvoiceStatus
    total: Money
    paid: Money
    balance: Money


class ArAgingBucketOut(BaseModel):
    bucket: str
    invoices: int
    balance: Money
    insurance_outstanding: Money
    patient_outstanding: Money


class ArAgingResponse(BaseModel):
    buckets: list[ArAgingBucketOut]
    total_balance: Money
    note: str = "Age is counted in whole UTC days from the invoice issue date."


# --- requests ------------------------------------------------------------------------


class InvoiceItemCreate(StrictModel):
    description: str = Field(min_length=1, max_length=300)
    qty: int = Field(default=1, ge=1, le=99)
    unit_price: Annotated[Decimal, Field(ge=0, le=100000, max_digits=12, decimal_places=2)]
    service_id: uuid.UUID | None = None


class InvoiceUpdate(StrictModel):
    """Give either a discount amount or a discount percentage, not both."""

    discount_amount: NonNegativeMoney | None = None
    discount_percent: (
        Annotated[Decimal, Field(ge=0, le=100, max_digits=5, decimal_places=2)] | None
    ) = None
    discount_reason: str | None = Field(default=None, max_length=300)
    insurance_expected: NonNegativeMoney | None = None


class VoidRequest(StrictModel):
    reason: str = Field(min_length=3, max_length=300)


class CardDetails(StrictModel):
    """Sandbox card details. SecretStr keeps the values out of reprs and logs."""

    card_number: SecretStr = Field(min_length=12, max_length=23)
    exp_month: int = Field(ge=1, le=12)
    exp_year: int = Field(ge=0, le=2100)
    cvv: SecretStr = Field(min_length=3, max_length=4)
    cardholder: str | None = Field(default=None, max_length=100)


class PaymentCreate(StrictModel):
    amount: PositiveMoney
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=100)
    paid_at: AwareDatetime | None = None
    card: CardDetails | None = None


class PayInvoiceRequest(StrictModel):
    """Patient payment from the portal. Omit the amount to pay the whole balance."""

    amount: PositiveMoney | None = None
    card: CardDetails
