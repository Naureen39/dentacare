"""Patient records with field level encryption and object level access checks."""

import uuid
from datetime import date

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import FieldCipher
from app.core.deps import CurrentUser
from app.core.errors import AppError
from app.db.enums import UserRole
from app.db.models import Appointment, Dentist, Patient
from app.schemas.patients import PatientProfile, PatientSummary, PatientUpdate

DOB_FIELD = "patients.dob"
PHONE_FIELD = "patients.phone"
ADDRESS_FIELD = "patients.address"
MEMBER_FIELD = "patients.insurance_member_id"

SEARCH_LIMIT = 50
STAFF_WRITE_ROLES = frozenset({UserRole.ADMIN, UserRole.RECEPTIONIST})
STAFF_READ_ROLES = STAFF_WRITE_ROLES | {UserRole.DENTIST}


def _not_found() -> AppError:
    return AppError("not_found", "Patient not found.", 404)


def to_summary(patient: Patient) -> PatientSummary:
    return PatientSummary(
        id=patient.id,
        first_name=patient.first_name,
        last_name=patient.last_name,
        email=patient.email,
    )


def to_profile(patient: Patient, cipher: FieldCipher) -> PatientProfile:
    dob = cipher.decrypt_optional(patient.dob_enc, DOB_FIELD)
    return PatientProfile(
        id=patient.id,
        first_name=patient.first_name,
        last_name=patient.last_name,
        email=patient.email,
        phone=cipher.decrypt_optional(patient.phone_enc, PHONE_FIELD),
        date_of_birth=date.fromisoformat(dob) if dob else None,
        address=cipher.decrypt_optional(patient.address_enc, ADDRESS_FIELD),
        insurance_provider_id=patient.insurance_provider_id,
        insurance_member_id=cipher.decrypt_optional(patient.insurance_member_id_enc, MEMBER_FIELD),
        marketing_consent=patient.marketing_consent,
        source=patient.source,
        created_at=patient.created_at,
    )


def apply_update(patient: Patient, data: PatientUpdate, cipher: FieldCipher) -> list[str]:
    """Apply the supplied fields and return the names that changed (never their values)."""
    changed = data.model_dump(exclude_unset=True)
    for name in ("first_name", "last_name", "marketing_consent", "insurance_provider_id"):
        if name in changed and changed[name] is not None:
            setattr(patient, name, changed[name])
    if "email" in changed:
        patient.email = changed["email"]
    encrypted = {
        "phone": ("phone_enc", PHONE_FIELD, changed.get("phone")),
        "address": ("address_enc", ADDRESS_FIELD, changed.get("address")),
        "insurance_member_id": (
            "insurance_member_id_enc",
            MEMBER_FIELD,
            changed.get("insurance_member_id"),
        ),
        "date_of_birth": (
            "dob_enc",
            DOB_FIELD,
            changed["date_of_birth"].isoformat() if changed.get("date_of_birth") else None,
        ),
    }
    for name, (column, field, value) in encrypted.items():
        if name in changed:
            setattr(patient, column, cipher.encrypt_optional(value, field))
    return sorted(changed)


async def dentist_id_for_user(db: AsyncSession, current: CurrentUser) -> uuid.UUID | None:
    return (
        await db.execute(select(Dentist.id).where(Dentist.user_id == current.id))
    ).scalar_one_or_none()


async def get_patient_for_staff(
    db: AsyncSession, current: CurrentUser, patient_id: uuid.UUID, *, write: bool = False
) -> Patient:
    """Load a patient the signed in staff member may access.

    Receptionists and administrators see everyone. A dentist can read only patients who have
    an appointment with them, and a record they cannot see is reported as missing.
    """
    allowed = STAFF_WRITE_ROLES if write else STAFF_READ_ROLES
    if current.role not in allowed:
        raise AppError("forbidden", "You do not have permission to perform this action.", 403)
    patient = (
        await db.execute(select(Patient).where(Patient.id == patient_id))
    ).scalar_one_or_none()
    if patient is None:
        raise _not_found()
    if current.role is UserRole.DENTIST:
        dentist_id = await dentist_id_for_user(db, current)
        related = (
            dentist_id is not None
            and (
                await db.execute(
                    select(
                        exists().where(
                            Appointment.patient_id == patient.id,
                            Appointment.dentist_id == dentist_id,
                        )
                    )
                )
            ).scalar_one()
        )
        if not related:
            raise _not_found()
    return patient


async def search_patients(
    db: AsyncSession, current: CurrentUser, query: str | None
) -> list[Patient]:
    stmt = select(Patient).where(Patient.anonymized_at.is_(None))
    if query:
        q = query.strip()
        stmt = stmt.where(
            or_(
                Patient.first_name.op("%")(q),
                Patient.last_name.op("%")(q),
                Patient.first_name.ilike(f"{q}%"),
                Patient.last_name.ilike(f"{q}%"),
            )
        )
    if current.role is UserRole.DENTIST:
        dentist_id = await dentist_id_for_user(db, current)
        if dentist_id is None:
            return []
        stmt = stmt.where(
            exists().where(
                Appointment.patient_id == Patient.id, Appointment.dentist_id == dentist_id
            )
        )
    stmt = stmt.order_by(Patient.last_name, Patient.first_name).limit(SEARCH_LIMIT)
    return list((await db.execute(stmt)).scalars().all())
