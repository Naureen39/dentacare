"""Authentication workflows: registration, login, MFA, token rotation and password recovery."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import Settings
from app.core.crypto import CryptoError, FieldCipher, sha256_hex
from app.core.deps import MFA_REQUIRED_ROLES
from app.core.errors import AppError
from app.core.rate_limit import client_ip
from app.core.security import (
    InvalidTokenError,
    PasswordService,
    create_access_token,
    create_jwt,
    decode_jwt,
    generate_recovery_codes,
    generate_token,
    hash_token,
    new_totp_secret,
    normalize_recovery_code,
    password_policy_issues,
    totp_uri,
    verify_totp,
)
from app.db.enums import AuthTokenPurpose, PatientSource, UserRole
from app.db.models import AuthToken, MfaRecoveryCode, Patient, RefreshToken, User
from app.services import audit
from app.services.audit import AuditAction
from app.services.email_templates import render_email
from app.services.mailer import Mailer

MFA_SECRET_FIELD = "users.mfa_secret"  # noqa: S105
PHONE_FIELD = "patients.phone"
TOTP_REPLAY_SECONDS = 90
GENERIC_LOGIN_ERROR = "The email address or password is incorrect."


def invalid_credentials() -> AppError:
    return AppError("invalid_credentials", GENERIC_LOGIN_ERROR, 401)


def invalid_token() -> AppError:
    return AppError("invalid_token", "This link is invalid or has expired.", 400)


@dataclass
class Session:
    """A freshly issued session: a short lived access token and an opaque refresh token."""

    access_token: str
    refresh_token: str
    expires_in: int
    recovery_codes: list[str] | None = None


@dataclass
class LoginOutcome:
    kind: str  # "authenticated" | "mfa_required" | "mfa_setup_required"
    session: Session | None = None
    mfa_token: str | None = None


class AuthService:
    def __init__(
        self,
        *,
        db: AsyncSession,
        settings: Settings,
        redis: Redis,
        passwords: PasswordService,
        cipher: FieldCipher,
        mailer: Mailer,
        request: Request,
    ) -> None:
        self.db = db
        self.settings = settings
        self.redis = redis
        self.passwords = passwords
        self.cipher = cipher
        self.mailer = mailer
        self.request = request

    # --- helpers --------------------------------------------------------------------

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _check_policy(self, password: str, email: str | None) -> None:
        issues = password_policy_issues(
            password, min_length=self.settings.password_min_length, email=email
        )
        if issues:
            raise AppError(
                "weak_password", "The password does not meet the requirements.", 422, issues
            )

    async def _user_by_email(self, email: str) -> User | None:
        return (await self.db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    async def _issue_one_time_token(
        self, user: User, purpose: AuthTokenPurpose, ttl: timedelta
    ) -> str:
        await self.db.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user.id,
                AuthToken.purpose == purpose,
                AuthToken.used_at.is_(None),
            )
            .values(used_at=self._now())
        )
        raw = generate_token()
        self.db.add(
            AuthToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_token(raw),
                expires_at=self._now() + ttl,
            )
        )
        return raw

    async def _consume_one_time_token(self, raw: str, purpose: AuthTokenPurpose) -> User:
        row = (
            await self.db.execute(
                select(AuthToken)
                .where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None or row.used_at is not None or row.expires_at <= self._now():
            raise invalid_token()
        user = (await self.db.execute(select(User).where(User.id == row.user_id))).scalar_one()
        if not user.is_active:
            raise invalid_token()
        row.used_at = self._now()
        return user

    async def _revoke_all_sessions(self, user_id: uuid.UUID) -> None:
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=self._now())
        )

    async def _create_session(
        self, user: User, *, mfa: bool, family_id: uuid.UUID | None = None
    ) -> Session:
        raw = generate_token()
        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                family_id=family_id or uuid.uuid4(),
                expires_at=self._now() + timedelta(days=self.settings.refresh_days),
                user_agent=(self.request.headers.get("User-Agent") or "")[:400] or None,
                ip=client_ip(self.request) if self.request.client else None,
            )
        )
        return Session(
            access_token=create_access_token(self.settings, user.id, user.role.value, mfa=mfa),
            refresh_token=raw,
            expires_in=self.settings.jwt_access_minutes * 60,
        )

    def _challenge(self, user: User, token_type: str) -> str:
        return create_jwt(
            self.settings,
            user_id=user.id,
            role=user.role.value,
            token_type=token_type,  # type: ignore[arg-type]
            mfa=False,
            lifetime=timedelta(minutes=self.settings.mfa_challenge_minutes),
        )

    async def _register_failure(self, user: User, action: str, reason: str) -> None:
        """Count a failed credential check and lock the account at the configured threshold."""
        failures = (
            await self.db.execute(
                update(User)
                .where(User.id == user.id)
                .values(failed_logins=User.failed_logins + 1)
                .returning(User.failed_logins)
            )
        ).scalar_one()
        await audit.record(
            self.db,
            action,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
            metadata={"reason": reason},
        )
        if failures >= self.settings.lockout_attempts:
            await self.db.execute(
                update(User)
                .where(User.id == user.id)
                .values(
                    failed_logins=0,
                    locked_until=self._now() + timedelta(minutes=self.settings.lockout_minutes),
                )
            )
            await audit.record(
                self.db,
                AuditAction.LOGIN_LOCKED,
                request=self.request,
                actor_id=user.id,
                actor_role=user.role.value,
            )
        await self.db.commit()

    # --- registration and email verification ----------------------------------------

    async def register(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: str | None,
        marketing_consent: bool,
    ) -> None:
        self._check_policy(password, email)
        # Hash first so the cost is the same whether or not the address is already registered.
        password_hash = self.passwords.hash(password)
        existing = await self._user_by_email(email)
        if existing is not None:
            await self.mailer.send_content(
                render_email(
                    "account_exists",
                    to=email,
                    settings=self.settings,
                    action_url=f"{self.settings.public_base_url}/login",
                )
            )
            return

        user = User(
            email=email,
            password_hash=password_hash,
            role=UserRole.PATIENT,
            password_changed_at=self._now(),
        )
        self.db.add(user)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            return  # lost a race with a concurrent registration of the same address
        self.db.add(
            Patient(
                user_id=user.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone_enc=self.cipher.encrypt_optional(phone, PHONE_FIELD),
                marketing_consent=marketing_consent,
                source=PatientSource.WEB,
            )
        )
        raw = await self._issue_one_time_token(
            user,
            AuthTokenPurpose.EMAIL_VERIFICATION,
            timedelta(hours=self.settings.email_verification_hours),
        )
        await audit.record(
            self.db,
            AuditAction.REGISTER,
            request=self.request,
            actor_id=user.id,
            actor_role="patient",
        )
        await self.db.commit()
        await self.mailer.send_content(
            render_email(
                "verify_email",
                to=email,
                settings=self.settings,
                action_url=f"{self.settings.public_base_url}/verify-email?token={raw}",
                hours=self.settings.email_verification_hours,
            )
        )

    async def verify_email(self, raw_token: str) -> None:
        user = await self._consume_one_time_token(raw_token, AuthTokenPurpose.EMAIL_VERIFICATION)
        if user.email_verified_at is None:
            user.email_verified_at = self._now()
        await audit.record(
            self.db,
            AuditAction.EMAIL_VERIFIED,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
        )
        await self.db.commit()

    # --- login ----------------------------------------------------------------------

    async def login(self, email: str, password: str) -> LoginOutcome:
        await rate_limit.enforce(
            self.redis, rate_limit.login_rule(self.settings), f"acct:{sha256_hex(email.lower())}"
        )
        user = await self._user_by_email(email)

        if user is None:
            self.passwords.verify_dummy(password)
            await audit.record(
                self.db,
                AuditAction.LOGIN_FAILED,
                request=self.request,
                metadata={
                    "reason": "unknown_account",
                    "email_fingerprint": audit.email_fingerprint(email),
                },
            )
            await self.db.commit()
            raise invalid_credentials()

        password_ok = self.passwords.verify(user.password_hash, password)
        locked = user.locked_until is not None and user.locked_until > self._now()

        if locked:
            await audit.record(
                self.db,
                AuditAction.LOGIN_FAILED,
                request=self.request,
                actor_id=user.id,
                actor_role=user.role.value,
                metadata={"reason": "locked"},
            )
            await self.db.commit()
            raise invalid_credentials()
        if not password_ok or not user.is_active:
            await self._register_failure(user, AuditAction.LOGIN_FAILED, "bad_password")
            raise invalid_credentials()
        if user.email_verified_at is None:
            raise AppError(
                "email_not_verified", "Confirm your email address before signing in.", 403
            )

        if self.passwords.needs_rehash(user.password_hash):
            user.password_hash = self.passwords.hash(password)
        user.failed_logins = 0
        user.locked_until = None

        if user.mfa_enabled:
            await self.db.commit()
            return LoginOutcome("mfa_required", mfa_token=self._challenge(user, "mfa_challenge"))
        if user.role in MFA_REQUIRED_ROLES:
            await self.db.commit()
            return LoginOutcome("mfa_setup_required", mfa_token=self._challenge(user, "mfa_setup"))

        session = await self._complete_login(user, mfa=False)
        return LoginOutcome("authenticated", session=session)

    async def _complete_login(self, user: User, *, mfa: bool) -> Session:
        user.last_login_at = self._now()
        session = await self._create_session(user, mfa=mfa)
        await audit.record(
            self.db,
            AuditAction.LOGIN,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
            metadata={"mfa": mfa},
        )
        await self.db.commit()
        return session

    # --- MFA ------------------------------------------------------------------------

    def _decrypt_secret(self, user: User) -> str | None:
        try:
            return self.cipher.decrypt_optional(user.mfa_secret_enc, MFA_SECRET_FIELD)
        except CryptoError:
            return None

    async def verify_mfa(
        self, mfa_token: str, code: str | None, recovery_code: str | None
    ) -> Session:
        try:
            claims = decode_jwt(self.settings, mfa_token, "mfa_challenge")
        except InvalidTokenError as exc:
            raise AppError(
                "invalid_mfa_token", "The sign in attempt has expired. Please sign in again.", 401
            ) from exc
        await rate_limit.enforce(
            self.redis, rate_limit.login_rule(self.settings), f"mfa:{claims.user_id}"
        )

        user = (
            await self.db.execute(select(User).where(User.id == claims.user_id))
        ).scalar_one_or_none()
        if user is None or not user.is_active or not user.mfa_enabled:
            raise AppError(
                "invalid_mfa_token", "The sign in attempt has expired. Please sign in again.", 401
            )
        if user.locked_until is not None and user.locked_until > self._now():
            raise invalid_credentials()
        if (code is None) == (recovery_code is None):
            raise AppError("validation_error", "Provide either a code or a recovery code.", 422)

        ok = False
        if code is not None:
            ok = await self._check_totp(user, code)
        elif recovery_code is not None:
            ok = await self._use_recovery_code(user, recovery_code)
            if ok:
                await audit.record(
                    self.db,
                    AuditAction.MFA_RECOVERY_USED,
                    request=self.request,
                    actor_id=user.id,
                    actor_role=user.role.value,
                )
        if not ok:
            await self._register_failure(user, AuditAction.MFA_FAILED, "bad_code")
            raise AppError("invalid_mfa_code", "The verification code is incorrect.", 401)

        user.failed_logins = 0
        return await self._complete_login(user, mfa=True)

    async def _check_totp(self, user: User, code: str) -> bool:
        secret = self._decrypt_secret(user)
        if secret is None or not verify_totp(secret, code):
            return False
        # A code may be used once: reject replays within its validity window.
        fresh = await self.redis.set(f"totp:{user.id}:{code}", "1", nx=True, ex=TOTP_REPLAY_SECONDS)
        return bool(fresh)

    async def _use_recovery_code(self, user: User, supplied: str) -> bool:
        normalized = normalize_recovery_code(supplied)
        rows = (
            (
                await self.db.execute(
                    select(MfaRecoveryCode)
                    .where(MfaRecoveryCode.user_id == user.id, MfaRecoveryCode.used_at.is_(None))
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if self.passwords.verify(row.code_hash, normalized):
                row.used_at = self._now()
                return True
        return False

    async def mfa_setup(self, user: User) -> tuple[str, str]:
        if user.mfa_enabled:
            raise AppError(
                "mfa_already_enabled", "Multi-factor authentication is already enabled.", 409
            )
        secret = new_totp_secret()
        user.mfa_secret_enc = self.cipher.encrypt(secret, MFA_SECRET_FIELD)
        await self.db.commit()
        return secret, totp_uri(secret, user.email, self.settings.clinic_name)

    async def mfa_enable(self, user: User, code: str) -> list[str]:
        if user.mfa_enabled:
            raise AppError(
                "mfa_already_enabled", "Multi-factor authentication is already enabled.", 409
            )
        secret = self._decrypt_secret(user)
        if secret is None:
            raise AppError("mfa_not_started", "Start MFA setup first.", 409)
        if not verify_totp(secret, code):
            await self._register_failure(user, AuditAction.MFA_FAILED, "bad_enrolment_code")
            raise AppError("invalid_mfa_code", "The verification code is incorrect.", 401)
        await self.redis.set(f"totp:{user.id}:{code}", "1", nx=True, ex=TOTP_REPLAY_SECONDS)

        codes = generate_recovery_codes()
        await self.db.execute(
            MfaRecoveryCode.__table__.delete().where(MfaRecoveryCode.user_id == user.id)  # type: ignore[attr-defined]
        )
        for plain in codes:
            self.db.add(
                MfaRecoveryCode(
                    user_id=user.id, code_hash=self.passwords.hash(normalize_recovery_code(plain))
                )
            )
        user.mfa_enabled = True
        await audit.record(
            self.db,
            AuditAction.MFA_ENABLED,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
        )
        await self.db.commit()
        return codes

    async def finish_enrolment_login(self, user: User) -> Session:
        return await self._complete_login(user, mfa=True)

    async def mfa_disable(self, user: User, password: str, code: str) -> None:
        if user.role in MFA_REQUIRED_ROLES:
            raise AppError(
                "mfa_mandatory", "Multi-factor authentication is mandatory for this role.", 403
            )
        if not user.mfa_enabled:
            raise AppError("mfa_not_enabled", "Multi-factor authentication is not enabled.", 409)
        if not self.passwords.verify(user.password_hash, password) or not await self._check_totp(
            user, code
        ):
            await self._register_failure(user, AuditAction.MFA_FAILED, "bad_disable_attempt")
            raise AppError(
                "invalid_credentials", "The password or verification code is incorrect.", 401
            )
        user.mfa_enabled = False
        user.mfa_secret_enc = None
        await self.db.execute(
            MfaRecoveryCode.__table__.delete().where(MfaRecoveryCode.user_id == user.id)  # type: ignore[attr-defined]
        )
        await audit.record(
            self.db,
            AuditAction.MFA_DISABLED,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
        )
        await self.db.commit()

    # --- refresh token rotation -----------------------------------------------------

    async def refresh(self, raw_token: str | None) -> Session:
        if not raw_token:
            raise AppError("unauthorized", "Please sign in again.", 401)
        row = (
            await self.db.execute(
                select(RefreshToken)
                .where(RefreshToken.token_hash == hash_token(raw_token))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise AppError("unauthorized", "Please sign in again.", 401)

        if row.revoked_at is not None:
            # A token that was already rotated or revoked is being replayed: assume theft and
            # end every session in the family.
            await self.db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=self._now())
            )
            await audit.record(
                self.db,
                AuditAction.REFRESH_REUSE,
                request=self.request,
                actor_id=row.user_id,
                metadata={"family_id": str(row.family_id)},
            )
            await self.db.commit()
            raise AppError("session_revoked", "Your session ended. Please sign in again.", 401)

        user = (await self.db.execute(select(User).where(User.id == row.user_id))).scalar_one()
        if row.expires_at <= self._now() or not user.is_active:
            raise AppError("unauthorized", "Please sign in again.", 401)

        session = await self._create_session(user, mfa=user.mfa_enabled, family_id=row.family_id)
        await self.db.flush()
        new_row = (
            await self.db.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == hash_token(session.refresh_token)
                )
            )
        ).scalar_one()
        row.revoked_at = self._now()
        row.replaced_by = new_row.id
        await self.db.commit()
        return session

    async def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        row = (
            await self.db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token))
            )
        ).scalar_one_or_none()
        if row is None:
            return
        await self.db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == row.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=self._now())
        )
        await audit.record(self.db, AuditAction.LOGOUT, request=self.request, actor_id=row.user_id)
        await self.db.commit()

    # --- the user's own sessions ------------------------------------------------------

    async def list_sessions(
        self, user_id: uuid.UUID, current_raw: str | None
    ) -> list[tuple[RefreshToken, bool]]:
        """Each signed in device once: a family has exactly one live token at a time."""
        rows = (
            (
                await self.db.execute(
                    select(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > self._now(),
                    )
                    .order_by(RefreshToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        current = hash_token(current_raw) if current_raw else None
        return [(row, row.token_hash == current) for row in rows]

    async def revoke_session(self, user_id: uuid.UUID, family_id: uuid.UUID) -> None:
        """End one of the user's own sessions. Someone else's session is reported as missing."""
        result = await self.db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=self._now())
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise AppError("not_found", "Session not found.", 404)
        await audit.record(
            self.db,
            AuditAction.SESSION_REVOKE,
            request=self.request,
            actor_id=user_id,
            metadata={"family_id": str(family_id)},
        )
        await self.db.commit()

    # --- password recovery and change -----------------------------------------------

    async def forgot_password(self, email: str) -> None:
        """Always completes silently so the response never reveals whether an account exists."""
        try:
            await rate_limit.enforce(
                self.redis,
                rate_limit.account_email_rule(self.settings),
                f"reset:{sha256_hex(email.lower())}",
            )
        except AppError:
            return
        user = await self._user_by_email(email)
        if user is None or not user.is_active:
            return
        raw = await self._issue_one_time_token(
            user,
            AuthTokenPurpose.PASSWORD_RESET,
            timedelta(minutes=self.settings.password_reset_minutes),
        )
        await audit.record(
            self.db,
            AuditAction.PASSWORD_RESET_REQUEST,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
        )
        await self.db.commit()
        await self.mailer.send_content(
            render_email(
                "password_reset",
                to=user.email,
                settings=self.settings,
                action_url=f"{self.settings.public_base_url}/reset-password?token={raw}",
                minutes=self.settings.password_reset_minutes,
            )
        )

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        user = await self._consume_one_time_token(raw_token, AuthTokenPurpose.PASSWORD_RESET)
        self._check_policy(new_password, user.email)
        await self._set_password(user, new_password, via="reset")
        # Receiving the link proves control of the mailbox.
        if user.email_verified_at is None:
            user.email_verified_at = self._now()
        await self.db.commit()

    async def change_password(self, user: User, current: str, new: str) -> None:
        if not self.passwords.verify(user.password_hash, current):
            await self._register_failure(user, AuditAction.LOGIN_FAILED, "bad_current_password")
            raise AppError("invalid_credentials", "The current password is incorrect.", 401)
        self._check_policy(new, user.email)
        if self.passwords.verify(user.password_hash, new):
            raise AppError(
                "weak_password",
                "Choose a password you have not used before.",
                422,
                ["The new password must differ."],
            )
        await self._set_password(user, new, via="change")
        await self.db.commit()

    async def _set_password(self, user: User, new_password: str, *, via: str) -> None:
        user.password_hash = self.passwords.hash(new_password)
        user.password_changed_at = self._now()
        user.failed_logins = 0
        user.locked_until = None
        await self._revoke_all_sessions(user.id)
        await audit.record(
            self.db,
            AuditAction.PASSWORD_CHANGE,
            request=self.request,
            actor_id=user.id,
            actor_role=user.role.value,
            metadata={"via": via},
        )
