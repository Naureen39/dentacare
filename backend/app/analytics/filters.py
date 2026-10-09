"""Query filters shared by every analytics endpoint, and who may see what."""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from app.core.errors import AppError
from app.db.enums import UserRole

Granularity = Literal["day", "week", "month", "quarter"]
GRANULARITIES = ("day", "week", "month", "quarter")
MAX_SPAN_DAYS = 1100
DEFAULT_SPAN_DAYS = 365

# Endpoint groups, and the roles that may use them.
OPERATIONS = "operations"  # appointments, patient flow, no show risk
FINANCE = "finance"  # revenue, receivables, forecast
CLINIC = "clinic"  # comparisons between dentists, retention, the chatbot
ACCESS: dict[str, frozenset[UserRole]] = {
    OPERATIONS: frozenset({UserRole.ADMIN, UserRole.RECEPTIONIST, UserRole.DENTIST}),
    FINANCE: frozenset({UserRole.ADMIN}),
    CLINIC: frozenset({UserRole.ADMIN}),
}
# A dentist may also see their own revenue; the endpoint marks itself with this group.
OWN_FINANCE = "own_finance"
ACCESS[OWN_FINANCE] = frozenset({UserRole.ADMIN, UserRole.DENTIST})
# Receptionists see the patient and chatbot figures that support the front desk.
FRONT_DESK = "front_desk"
ACCESS[FRONT_DESK] = frozenset({UserRole.ADMIN, UserRole.RECEPTIONIST})


@dataclass(frozen=True)
class Scope:
    """What the caller may see. A dentist is limited to their own data."""

    role: UserRole
    dentist_id: uuid.UUID | None = None  # forced filter for a dentist


@dataclass(frozen=True)
class Filters:
    date_from: date
    date_to: date
    granularity: Granularity = "month"
    dentist_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    payer_type: Literal["patient", "insurer"] | None = None

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    def previous(self) -> "Filters":
        """The period of the same length immediately before this one."""
        end = self.date_from - timedelta(days=1)
        return Filters(
            end - timedelta(days=self.days - 1),
            end,
            self.granularity,
            self.dentist_id,
            self.service_id,
            self.payer_type,
        )

    def key(self) -> str:
        raw = "|".join(
            str(v)
            for v in (
                self.date_from,
                self.date_to,
                self.granularity,
                self.dentist_id,
                self.service_id,
                self.payer_type,
            )
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:24]


def resolve(
    scope: Scope,
    *,
    today: date,
    date_from: date | None,
    date_to: date | None,
    granularity: Granularity,
    dentist_id: uuid.UUID | None,
    service_id: uuid.UUID | None,
    payer_type: Literal["patient", "insurer"] | None,
) -> Filters:
    """Validate the request and apply the caller's scope."""
    end = date_to or today - timedelta(days=1)
    start = date_from or end - timedelta(days=DEFAULT_SPAN_DAYS - 1)
    if start > end:
        raise AppError("validation_error", "The start date is after the end date.", 422)
    if (end - start).days + 1 > MAX_SPAN_DAYS:
        raise AppError("validation_error", f"Choose at most {MAX_SPAN_DAYS} days at a time.", 422)
    if granularity not in GRANULARITIES:
        raise AppError("validation_error", "Unknown granularity.", 422)
    if scope.role is UserRole.DENTIST:
        if scope.dentist_id is None:
            raise AppError("forbidden", "No dentist profile is linked to this account.", 403)
        if dentist_id is not None and dentist_id != scope.dentist_id:
            raise AppError("forbidden", "You can only see your own figures.", 403)
        dentist_id = scope.dentist_id
    return Filters(start, end, granularity, dentist_id, service_id, payer_type)


def require(scope: Scope, group: str) -> None:
    if scope.role not in ACCESS[group]:
        raise AppError("forbidden", "You do not have permission to see these figures.", 403)
