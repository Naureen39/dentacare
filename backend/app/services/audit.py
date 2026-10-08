"""Audit trail. Entries never contain personal data values or credentials."""

import re
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import sha256_hex
from app.core.rate_limit import client_ip
from app.db.models import AuditLog

# Metadata keys matching this pattern are dropped, whatever the caller passes.
_FORBIDDEN_KEY = re.compile(
    r"pass|token|secret|code|otp|dob|birth|phone|address|email|member|card|ssn|note",
    re.IGNORECASE,
)
_ALLOWED_KEYS = {"email_fingerprint"}
_MAX_VALUE_LENGTH = 200


class AuditAction:
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    LOGIN_LOCKED = "auth.account_locked"
    LOGOUT = "auth.logout"
    REGISTER = "auth.register"
    EMAIL_VERIFIED = "auth.email_verified"
    PASSWORD_CHANGE = "auth.password_change"  # noqa: S105
    PASSWORD_RESET_REQUEST = "auth.password_reset_request"  # noqa: S105
    REFRESH_REUSE = "auth.refresh_token_reuse"
    MFA_ENABLED = "auth.mfa_enabled"
    MFA_DISABLED = "auth.mfa_disabled"
    MFA_FAILED = "auth.mfa_failed"
    MFA_RECOVERY_USED = "auth.mfa_recovery_used"
    APPOINTMENT_CREATE = "appointment.create"
    APPOINTMENT_STATUS = "appointment.status"
    APPOINTMENT_RESCHEDULE = "appointment.reschedule"
    SCHEDULE_VIEW = "schedule.view"
    PATIENT_CREATE = "patient.create"
    PATIENT_VIEW = "patient.view"
    PATIENT_LIST = "patient.list"
    PATIENT_UPDATE = "patient.update"
    PROFILE_UPDATE = "profile.update"
    ROLE_CHANGE = "user.role_change"
    EXPORT = "data.export"
    AUDIT_VIEW = "audit.view"


def email_fingerprint(email: str) -> str:
    """Short one way fingerprint used to correlate failed logins without storing the address."""
    return sha256_hex(email.strip().lower())[:16]


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key not in _ALLOWED_KEYS and _FORBIDDEN_KEY.search(key):
            continue
        if isinstance(value, str):
            value = value[:_MAX_VALUE_LENGTH]
        elif isinstance(value, list):
            value = [v[:_MAX_VALUE_LENGTH] if isinstance(v, str) else v for v in value][:50]
        clean[key] = value
    return clean


async def record(
    session: AsyncSession,
    action: str,
    *,
    request: Request | None = None,
    actor_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    entity: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            ip=client_ip(request) if request is not None and request.client else None,
            metadata_=sanitize_metadata(metadata),
        )
    )
