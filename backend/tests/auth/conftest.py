"""Fixtures for tests that exercise the real API against PostgreSQL and an in-memory Redis."""

import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import fakeredis
import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import PasswordService
from app.db.enums import UserRole
from app.db.models import Dentist, Patient, User
from app.main import create_app
from app.services.mailer import InMemoryMailer
from app.services.queue import RecordingJobQueue
from tests.db.conftest import sqlalchemy_url

STRONG_PASSWORD = "correct-horse-battery-staple-9"

# Children first so foreign keys never block cleanup. app_settings is deliberately kept.
CLEANUP_ORDER = [
    "kb_chunks", "kb_documents", "intent_examples",
    "audit_logs", "llm_usage", "chat_messages", "chat_sessions", "payments", "invoice_items",
    "invoices", "appointment_action_tokens", "reminders", "appointment_status_history", "appointments", "dentist_services",
    "dentist_schedules", "schedule_exceptions", "patients", "dentists", "services",
    "insurance_providers", "newsletter_subscribers", "contact_inquiries", "testimonials",
    "guest_verifications", "auth_tokens", "mfa_recovery_codes", "refresh_tokens", "users",
]  # fmt: skip


def make_settings(database: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "database_url": sqlalchemy_url(database),
        "jwt_secret": "test-signing-secret-that-is-long-enough-0123456789",
        "argon2_time_cost": 1,
        "argon2_memory_kib": 64,
        "argon2_parallelism": 1,
        "rate_limit_login_per_minute": 1000,
        "rate_limit_account_email_per_hour": 1000,
        "rate_limit_public_booking_per_hour": 1000,
        "rate_limit_contact_per_hour": 1000,
        "cors_origins": "http://localhost:5173",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@dataclass
class Ctx:
    app: FastAPI
    client: AsyncClient
    mailer: InMemoryMailer
    jobs: RecordingJobQueue
    redis: fakeredis.FakeAsyncRedis
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    passwords: PasswordService

    # --- direct database helpers ----------------------------------------------------

    async def create_user(
        self,
        email: str,
        role: UserRole = UserRole.PATIENT,
        password: str = STRONG_PASSWORD,
        *,
        verified: bool = True,
        with_patient: bool | None = None,
        first_name: str = "Test",
        last_name: str = "Person",
    ) -> User:
        async with self.session_factory() as db:
            from datetime import UTC, datetime

            user = User(
                email=email,
                password_hash=self.passwords.hash(password),
                role=role,
                email_verified_at=datetime.now(UTC) if verified else None,
            )
            db.add(user)
            await db.flush()
            if with_patient if with_patient is not None else role is UserRole.PATIENT:
                db.add(
                    Patient(
                        user_id=user.id, first_name=first_name, last_name=last_name, email=email
                    )
                )
            if role is UserRole.DENTIST:
                db.add(Dentist(user_id=user.id, full_name=f"Dr. {last_name}", specialty="general"))
            await db.commit()
            await db.refresh(user)
            return user

    async def fetch(self, query: str, **params: object) -> list[tuple[Any, ...]]:
        async with self.session_factory() as db:
            return [tuple(r) for r in (await db.execute(text(query), params)).all()]

    async def execute(self, query: str, **params: object) -> None:
        async with self.session_factory() as db:
            await db.execute(text(query), params)
            await db.commit()

    def set_settings(self, **overrides: object) -> None:
        self.settings = self.settings.model_copy(update=overrides)
        self.app.state.settings = self.settings

    # --- API flows ------------------------------------------------------------------

    def last_token(self, path_hint: str) -> str:
        """Extract the token from the most recent email containing the given link path."""
        for message in reversed(self.mailer.outbox):
            match = re.search(rf"{re.escape(path_hint)}\?token=([\w-]+)", message.body)
            if match:
                return match.group(1)
        raise AssertionError(f"no email with {path_hint} link")

    async def login(self, email: str, password: str = STRONG_PASSWORD):  # type: ignore[no-untyped-def]
        return await self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )

    async def access_token(self, email: str, password: str = STRONG_PASSWORD) -> str:
        """Sign in a user created with ``create_user``, completing MFA enrolment if required."""
        response = await self.login(email, password)
        body = response.json()
        if body["status"] == "mfa_setup_required":
            return str((await self.enrol_mfa(body["mfa_token"]))["access_token"])
        assert body["status"] == "authenticated", body
        return str(body["access_token"])

    async def enrol_mfa(self, bearer: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {bearer}"}
        setup = await self.client.post("/api/v1/auth/mfa/setup", headers=headers)
        secret = setup.json()["secret"]
        self.totp_secrets[bearer] = secret
        enabled = await self.client.post(
            "/api/v1/auth/mfa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()}
        )
        assert enabled.status_code == 200, enabled.text
        body: dict[str, Any] = enabled.json()
        body["secret"] = secret
        return body

    totp_secrets: dict[str, str] = None  # type: ignore[assignment]

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    async def clear_totp_replay_keys(self) -> None:
        async for key in self.redis.scan_iter("totp:*"):
            await self.redis.delete(key)


async def _cleanup(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as db:
        for table in CLEANUP_ORDER:
            await db.execute(text(f"DELETE FROM {table}"))  # noqa: S608
        await db.commit()


@pytest.fixture
async def ctx(migrated_schema_db: str) -> AsyncIterator[Ctx]:
    settings = make_settings(migrated_schema_db)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        mailer = InMemoryMailer()
        jobs = RecordingJobQueue()
        app.state.redis = redis
        app.state.mailer = mailer
        app.state.jobs = jobs
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="https://test") as client:
            context = Ctx(
                app=app,
                client=client,
                mailer=mailer,
                jobs=jobs,
                redis=redis,
                settings=settings,
                session_factory=app.state.session_factory,
                passwords=app.state.passwords,
            )
            context.totp_secrets = {}
            await _cleanup(context.session_factory)
            yield context
            await _cleanup(context.session_factory)
        await redis.aclose()


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
