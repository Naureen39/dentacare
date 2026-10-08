"""Guest booking: email one time codes and guest patient records."""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import Settings
from app.core.crypto import FieldCipher, sha256_hex
from app.core.errors import AppError
from app.db.enums import PatientSource
from app.db.models import GuestVerification, Patient
from app.services.email_templates import render_email
from app.services.mailer import Mailer

OTP_TTL_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
PHONE_FIELD = "patients.phone"


def _hash_code(secret: str, verification_id: uuid.UUID, code: str) -> str:
    return hmac.new(
        secret.encode(), f"{verification_id}:{code}".encode(), hashlib.sha256
    ).hexdigest()


class GuestService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        redis: Redis,
        cipher: FieldCipher,
        mailer: Mailer,
    ) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis
        self.cipher = cipher
        self.mailer = mailer

    async def request_code(self, email: str, first_name: str) -> GuestVerification:
        """Send a six digit code. Earlier unused codes for the address stop working."""
        await rate_limit.enforce(
            self.redis,
            rate_limit.account_email_rule(self.settings),
            f"guest:{sha256_hex(email.lower())}",
        )
        await self.db.execute(
            update(GuestVerification)
            .where(GuestVerification.email == email, GuestVerification.consumed_at.is_(None))
            .values(consumed_at=datetime.now(UTC))
        )
        code = f"{secrets.randbelow(1_000_000):06d}"
        verification = GuestVerification(
            email=email,
            code_hash="pending",
            expires_at=datetime.now(UTC) + timedelta(minutes=OTP_TTL_MINUTES),
        )
        self.db.add(verification)
        await self.db.flush()
        verification.code_hash = _hash_code(self.settings.jwt_secret, verification.id, code)
        await self.db.commit()
        await self.mailer.send_content(
            render_email(
                "guest_code",
                to=email,
                settings=self.settings,
                first_name=first_name,
                code=code,
                minutes=OTP_TTL_MINUTES,
            )
        )
        return verification

    async def verify_code(
        self, verification_id: uuid.UUID, email: str, code: str
    ) -> GuestVerification:
        """Check the code. A wrong guess is counted and committed even though booking then fails."""
        row = (
            await self.db.execute(
                select(GuestVerification)
                .where(GuestVerification.id == verification_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if (
            row is None
            or row.email.lower() != email.lower()
            or row.consumed_at is not None
            or row.expires_at <= now
        ):
            raise AppError("otp_invalid", "The verification code is invalid or has expired.", 400)
        if row.attempts >= OTP_MAX_ATTEMPTS:
            raise AppError(
                "otp_locked", "Too many incorrect codes. Request a new verification code.", 400
            )
        expected = _hash_code(self.settings.jwt_secret, row.id, code)
        if not hmac.compare_digest(expected, row.code_hash):
            row.attempts += 1
            remaining = OTP_MAX_ATTEMPTS - row.attempts
            await self.db.commit()
            raise AppError(
                "otp_invalid",
                "The verification code is incorrect.",
                400,
                {"attempts_remaining": remaining},
            )
        return row

    async def patient_for_guest(
        self, *, email: str, first_name: str, last_name: str, phone: str | None, marketing: bool
    ) -> Patient:
        """The patient record for a verified address, created on first booking."""
        existing = (
            await self.db.execute(
                select(Patient).where(Patient.email == email).order_by(Patient.created_at).limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        patient = Patient(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone_enc=self.cipher.encrypt_optional(phone, PHONE_FIELD),
            marketing_consent=marketing,
            source=PatientSource.WEB,
        )
        self.db.add(patient)
        await self.db.flush()
        return patient
