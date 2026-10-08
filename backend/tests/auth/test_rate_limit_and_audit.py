import fakeredis
import pytest

from app.core.errors import AppError
from app.core.rate_limit import RateLimitRule, enforce
from app.services.audit import email_fingerprint, sanitize_metadata


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_requests_up_to_the_limit_are_allowed(redis) -> None:  # type: ignore[no-untyped-def]
    rule = RateLimitRule("t", 3, 60)
    for _ in range(3):
        await enforce(redis, rule, "ip-1")


async def test_request_over_the_limit_is_rejected_with_retry_after(redis) -> None:  # type: ignore[no-untyped-def]
    rule = RateLimitRule("t", 2, 60)
    await enforce(redis, rule, "ip-1")
    await enforce(redis, rule, "ip-1")
    with pytest.raises(AppError) as raised:
        await enforce(redis, rule, "ip-1")

    assert raised.value.status_code == 429
    assert raised.value.code == "rate_limited"
    assert 0 < int(raised.value.headers["Retry-After"]) <= 60  # type: ignore[index]


async def test_identities_and_scopes_are_counted_separately(redis) -> None:  # type: ignore[no-untyped-def]
    rule = RateLimitRule("a", 1, 60)
    await enforce(redis, rule, "ip-1")
    await enforce(redis, rule, "ip-2")
    await enforce(redis, RateLimitRule("b", 1, 60), "ip-1")


async def test_missing_expiry_is_repaired(redis) -> None:  # type: ignore[no-untyped-def]
    rule = RateLimitRule("t", 1, 60)
    await redis.set("rl:t:ip-1", 5)  # a counter that lost its expiry
    with pytest.raises(AppError):
        await enforce(redis, rule, "ip-1")
    assert await redis.ttl("rl:t:ip-1") > 0


def test_audit_metadata_drops_sensitive_keys() -> None:
    clean = sanitize_metadata(
        {
            "password": "x",
            "new_password": "x",
            "refresh_token": "x",
            "mfa_code": "123456",
            "email": "a@example.com",
            "phone": "555",
            "dob": "1990-01-01",
            "address": "street",
            "insurance_member_id": "9",
            "card_number": "4242",
            "clinical_note": "text",
            "reason": "locked",
            "fields": ["first_name"],
            "results": 3,
        }
    )
    assert clean == {"reason": "locked", "fields": ["first_name"], "results": 3}


def test_audit_metadata_truncates_long_values() -> None:
    assert len(sanitize_metadata({"reason": "x" * 5000})["reason"]) == 200


def test_email_fingerprint_is_short_stable_and_case_insensitive() -> None:
    assert email_fingerprint("A@Example.com ") == email_fingerprint("a@example.com")
    assert len(email_fingerprint("a@example.com")) == 16
    assert "example" not in email_fingerprint("a@example.com")
    assert (
        email_fingerprint("a@example.com")
        == sanitize_metadata({"email_fingerprint": email_fingerprint("a@example.com")})[
            "email_fingerprint"
        ]
    )
