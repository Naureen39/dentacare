"""Password hashing and policy, opaque tokens, access JWTs and TOTP helpers."""

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import Settings
from app.core.crypto import sha256_hex

JWT_ALGORITHM = "HS256"
JWT_ISSUER = "meridian-dental"

TokenType = Literal["access", "mfa_challenge", "mfa_setup"]

_COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


# --- passwords ----------------------------------------------------------------------


@lru_cache
def _common_passwords() -> frozenset[str]:
    return frozenset(
        line.strip() for line in _COMMON_PASSWORDS_FILE.read_text("utf-8").splitlines() if line
    )


def password_policy_issues(
    password: str, *, min_length: int = 12, email: str | None = None
) -> list[str]:
    """Return human readable reasons the password is unacceptable, empty when it is fine."""
    issues: list[str] = []
    if len(password) < min_length:
        issues.append(f"Use at least {min_length} characters.")
    if len(password) > 128:
        issues.append("Use at most 128 characters.")
    lowered = password.lower()
    if lowered in _common_passwords():
        issues.append("This password is too common.")
    if len(set(password)) <= 3:
        issues.append("Use a greater variety of characters.")
    if email:
        local = email.split("@", 1)[0].lower()
        if len(local) >= 4 and local in lowered:
            issues.append("The password must not contain your email name.")
    return issues


class PasswordService:
    """argon2id hashing with parameters taken from settings."""

    def __init__(self, settings: Settings) -> None:
        self._hasher = PasswordHasher(
            time_cost=settings.argon2_time_cost,
            memory_cost=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
        )
        # Verified against when an account does not exist, so response time does not
        # reveal which emails are registered.
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


# --- opaque tokens ------------------------------------------------------------------


def generate_token() -> str:
    """URL safe random token with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return sha256_hex(token)


_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def generate_recovery_codes(count: int = 8) -> list[str]:
    """Single use recovery codes such as ``k3m9x-t7qpa`` (about 49 bits each)."""
    return [
        "-".join("".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(5)) for _ in range(2))
        for _ in range(count)
    ]


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^a-z0-9]", "", code.lower())


# --- JWT ----------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    token_type: TokenType
    role: str
    mfa: bool
    jti: str
    expires_at: datetime


class InvalidTokenError(Exception):
    pass


def create_jwt(
    settings: Settings,
    *,
    user_id: uuid.UUID,
    role: str,
    token_type: TokenType,
    mfa: bool,
    lifetime: timedelta,
    now: datetime | None = None,
) -> str:
    issued = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": JWT_ISSUER,
        "sub": str(user_id),
        "typ": token_type,
        "role": role,
        "mfa": mfa,
        "jti": uuid.uuid4().hex,
        "iat": int(issued.timestamp()),
        "exp": int((issued + lifetime).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def create_access_token(settings: Settings, user_id: uuid.UUID, role: str, *, mfa: bool) -> str:
    return create_jwt(
        settings,
        user_id=user_id,
        role=role,
        token_type="access",
        mfa=mfa,
        lifetime=timedelta(minutes=settings.jwt_access_minutes),
    )


def decode_jwt(settings: Settings, token: str, expected_type: TokenType) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["exp", "iat", "sub", "typ", "jti"]},
        )
        if payload["typ"] != expected_type:
            raise InvalidTokenError("wrong token type")
        return TokenClaims(
            user_id=uuid.UUID(payload["sub"]),
            token_type=payload["typ"],
            role=str(payload.get("role", "")),
            mfa=bool(payload.get("mfa", False)),
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(str(exc)) from exc


# --- TOTP ---------------------------------------------------------------------------

TOTP_DIGITS = 6
TOTP_INTERVAL = 30


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Accept the current code and one step either side to tolerate clock drift."""
    if not re.fullmatch(r"\d{6}", code):
        return False
    return bool(
        pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL).verify(code, valid_window=1)
    )
