"""Shared FastAPI dependencies: application services, authentication and authorization."""

import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import FieldCipher
from app.core.errors import AppError
from app.core.security import (
    InvalidTokenError,
    PasswordService,
    TokenClaims,
    TokenType,
    decode_jwt,
)
from app.db.enums import UserRole
from app.db.models import Patient, User
from app.db.session import get_session
from app.services.mailer import Mailer

MFA_REQUIRED_ROLES = frozenset({UserRole.ADMIN, UserRole.DENTIST})

Session = Annotated[AsyncSession, Depends(get_session)]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_cipher(request: Request) -> FieldCipher:
    cipher: FieldCipher = request.app.state.cipher
    return cipher


def get_passwords(request: Request) -> PasswordService:
    passwords: PasswordService = request.app.state.passwords
    return passwords


def get_mailer(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


AppSettings = Annotated[Settings, Depends(get_settings_dep)]
RedisDep = Annotated[Redis, Depends(get_redis)]
Cipher = Annotated[FieldCipher, Depends(get_cipher)]
Passwords = Annotated[PasswordService, Depends(get_passwords)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


def unauthorized(message: str = "Authentication is required.") -> AppError:
    return AppError("unauthorized", message, 401, headers={"WWW-Authenticate": "Bearer"})


def _bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise unauthorized()
    return token.strip()


@dataclass(frozen=True)
class CurrentUser:
    user: User
    claims: TokenClaims

    @property
    def id(self) -> uuid.UUID:
        return self.user.id

    @property
    def role(self) -> UserRole:
        return self.user.role


async def _load_user(request: Request, session: AsyncSession, expected: TokenType) -> CurrentUser:
    settings: Settings = request.app.state.settings
    try:
        claims = decode_jwt(settings, _bearer_token(request), expected)
    except InvalidTokenError as exc:
        raise unauthorized("The session is invalid or has expired.") from exc
    user = (
        await session.execute(select(User).where(User.id == claims.user_id))
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        raise unauthorized("The session is invalid or has expired.")
    return CurrentUser(user=user, claims=claims)


async def get_current_user(request: Request, session: Session) -> CurrentUser:
    current = await _load_user(request, session, "access")
    # Roles that must use MFA can never hold a usable access token without having passed it.
    if current.role in MFA_REQUIRED_ROLES and not current.claims.mfa:
        raise AppError("mfa_required", "Multi-factor authentication is required.", 403)
    return current


async def get_mfa_setup_principal(request: Request, session: Session) -> CurrentUser:
    """Accepts a normal access token, or the limited token issued when MFA enrolment is due."""
    header_token = _bearer_token(request)
    settings: Settings = request.app.state.settings
    for expected in ("access", "mfa_setup"):
        try:
            decode_jwt(settings, header_token, expected)
        except InvalidTokenError:
            continue
        return await _load_user(request, session, expected)
    raise unauthorized("The session is invalid or has expired.")


Authenticated = Annotated[CurrentUser, Depends(get_current_user)]
MfaSetupPrincipal = Annotated[CurrentUser, Depends(get_mfa_setup_principal)]


def require_roles(*roles: UserRole) -> Callable[..., Coroutine[Any, Any, CurrentUser]]:
    """Dependency factory allowing only the listed roles."""
    allowed = frozenset(roles)

    async def dependency(current: Authenticated) -> CurrentUser:
        if current.role not in allowed:
            raise AppError("forbidden", "You do not have permission to perform this action.", 403)
        return current

    return dependency


async def get_own_patient(current: Authenticated, session: Session) -> Patient:
    """The patient record belonging to the signed in patient user."""
    patient = (
        await session.execute(select(Patient).where(Patient.user_id == current.id))
    ).scalar_one_or_none()
    if patient is None:
        raise AppError("forbidden", "No patient profile is linked to this account.", 403)
    return patient


OwnPatient = Annotated[Patient, Depends(get_own_patient)]
