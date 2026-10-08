import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.db.enums import PatientSource, UserRole
from app.schemas.auth import StrictModel


class PatientSummary(BaseModel):
    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None


class PatientProfile(PatientSummary):
    phone: str | None
    date_of_birth: date | None
    address: str | None
    insurance_provider_id: uuid.UUID | None
    insurance_member_id: str | None
    marketing_consent: bool
    source: PatientSource
    created_at: datetime


class PatientUpdate(StrictModel):
    """Fields a caller may change. Anything else is rejected, which prevents mass assignment."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=40)
    date_of_birth: date | None = None
    address: str | None = Field(default=None, max_length=300)
    insurance_provider_id: uuid.UUID | None = None
    insurance_member_id: str | None = Field(default=None, max_length=60)
    marketing_consent: bool | None = None


class StaffPatientUpdate(PatientUpdate):
    email: EmailStr | None = None


class PatientCreate(PatientUpdate):
    """Walk-in or phone registration by front desk staff."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr | None = None
    source: PatientSource = PatientSource.WALK_IN


class RoleChangeRequest(StrictModel):
    role: UserRole


class RoleChangeResponse(BaseModel):
    id: uuid.UUID
    role: UserRole


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None
    actor_role: str | None
    action: str
    entity: str | None
    entity_id: str | None
    ip: str | None
    metadata: dict[str, object]
    created_at: datetime
