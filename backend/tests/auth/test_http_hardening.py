import pytest
from pydantic import ValidationError

from app.core.config import Settings
from tests.auth.conftest import Ctx, unique_email


async def test_security_headers_are_present_on_api_responses(ctx: Ctx) -> None:
    response = await ctx.client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers  # development only


async def test_hsts_is_enabled_in_production(ctx: Ctx) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.main import create_app
    from tests.auth.conftest import make_settings

    settings = make_settings(
        "meridian_schema_test",
        env="production",
        field_encryption_key="k1:" + "A" * 43 + "=",
    )
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="https://test") as client,
    ):
        response = await client.get("/health")
    assert "max-age=31536000" in response.headers["strict-transport-security"]


async def test_cors_allows_only_configured_origins(ctx: Ctx) -> None:
    allowed = await ctx.client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    denied = await ctx.client.options(
        "/api/v1/auth/login",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in denied.headers


async def test_error_bodies_never_leak_internal_details(ctx: Ctx) -> None:
    response = await ctx.client.post(
        "/api/v1/auth/login", json={"email": "not-an-email", "password": ""}
    )
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message", "details", "request_id"}
    assert "Traceback" not in response.text


async def test_unknown_json_fields_are_rejected_on_auth_endpoints(ctx: Ctx) -> None:
    response = await ctx.client.post(
        "/api/v1/auth/login",
        json={"email": unique_email(), "password": "x", "role": "admin"},
    )
    assert response.status_code == 422


async def test_sql_metacharacters_in_search_are_treated_as_data(ctx: Ctx) -> None:
    from app.db.enums import UserRole

    email = unique_email("rec")
    await ctx.create_user(email, UserRole.RECEPTIONIST)
    token = await ctx.access_token(email)
    response = await ctx.client.get(
        "/api/v1/patients", params={"q": "'; DROP TABLE patients; --"}, headers=ctx.auth(token)
    )
    assert response.status_code == 200
    assert await ctx.fetch("SELECT count(*) FROM patients") == [(0,)]


# --- configuration guards ------------------------------------------------------------


def test_production_requires_a_strong_signing_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", field_encryption_key="k1:" + "A" * 43 + "=")
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret="short", field_encryption_key="k1:" + "A" * 43 + "=")


def test_production_requires_an_encryption_key() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", jwt_secret="x" * 40)


def test_production_accepts_proper_secrets() -> None:
    settings = Settings(
        env="production", jwt_secret="x" * 40, field_encryption_key="k1:" + "A" * 43 + "="
    )
    assert settings.is_production
