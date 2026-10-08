import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pyotp
import pytest

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    PasswordService,
    create_jwt,
    decode_jwt,
    generate_recovery_codes,
    generate_token,
    hash_token,
    normalize_recovery_code,
    password_policy_issues,
    verify_totp,
)

SETTINGS = Settings(
    env="test",
    jwt_secret="unit-test-signing-secret-with-enough-length-12345",
    argon2_time_cost=1,
    argon2_memory_kib=64,
    argon2_parallelism=1,
)


# --- password policy ----------------------------------------------------------------


def test_short_password_is_rejected() -> None:
    assert password_policy_issues("short-pass1")  # 11 characters


def test_twelve_character_password_is_accepted() -> None:
    assert password_policy_issues("vN7#kd2!Qp9z") == []


@pytest.mark.parametrize("common", ["passwordpassword", "PASSWORD123456", "qwertyuiop123"])
def test_common_passwords_are_rejected_case_insensitively(common: str) -> None:
    assert any("common" in issue for issue in password_policy_issues(common))


def test_repeated_characters_are_rejected() -> None:
    assert password_policy_issues("aaaaaaaaaaaaaa")


def test_password_containing_the_email_name_is_rejected() -> None:
    issues = password_policy_issues("amelia.hartwell-2026!", email="amelia.hartwell@example.com")
    assert any("email" in issue for issue in issues)


def test_overlong_password_is_rejected() -> None:
    assert password_policy_issues("a1" * 70)


# --- hashing ------------------------------------------------------------------------


def test_argon2id_hash_verifies_and_is_salted() -> None:
    service = PasswordService(SETTINGS)
    first, second = service.hash("vN7#kd2!Qp9z"), service.hash("vN7#kd2!Qp9z")

    assert first.startswith("$argon2id$")
    assert first != second
    assert service.verify(first, "vN7#kd2!Qp9z") is True
    assert service.verify(first, "wrong-password-1") is False


def test_verify_handles_garbage_hashes() -> None:
    assert PasswordService(SETTINGS).verify("not-a-hash", "whatever") is False


def test_rehash_is_requested_when_parameters_change() -> None:
    old = PasswordService(SETTINGS).hash("vN7#kd2!Qp9z")
    stronger = PasswordService(
        Settings(env="test", argon2_time_cost=2, argon2_memory_kib=128, argon2_parallelism=1)
    )
    assert stronger.needs_rehash(old) is True
    assert stronger.needs_rehash(stronger.hash("vN7#kd2!Qp9z")) is False


# --- tokens -------------------------------------------------------------------------


def test_generated_tokens_are_long_and_unique() -> None:
    tokens = {generate_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 40 for t in tokens)


def test_token_hash_is_stable_and_not_the_token() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != "abc"
    assert len(hash_token("abc")) == 64


def test_recovery_codes_format_and_count() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == 8 and len(set(codes)) == 8
    assert all(len(c) == 11 and c[5] == "-" for c in codes)


def test_recovery_code_normalization_ignores_case_and_separators() -> None:
    assert normalize_recovery_code("K3M9X-T7QPA") == normalize_recovery_code(" k3m9x t7qpa ")


# --- JWT ----------------------------------------------------------------------------


def _token(
    token_type: str = "access", lifetime: timedelta = timedelta(minutes=5), **kw: object
) -> str:
    return create_jwt(
        SETTINGS,
        user_id=kw.get("user_id", uuid.uuid4()),  # type: ignore[arg-type]
        role="patient",
        token_type=token_type,  # type: ignore[arg-type]
        mfa=False,
        lifetime=lifetime,
        now=kw.get("now"),  # type: ignore[arg-type]
    )


def test_jwt_round_trip() -> None:
    user_id = uuid.uuid4()
    claims = decode_jwt(SETTINGS, _token(user_id=user_id), "access")
    assert claims.user_id == user_id
    assert claims.role == "patient"
    assert claims.mfa is False


def test_expired_jwt_is_rejected() -> None:
    old = datetime.now(UTC) - timedelta(hours=1)
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, _token(now=old), "access")


def test_jwt_of_the_wrong_type_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, _token("mfa_challenge"), "access")
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, _token("access"), "mfa_challenge")


def test_jwt_signed_with_another_secret_is_rejected() -> None:
    other = Settings(env="test", jwt_secret="a-completely-different-secret-value-1234567890")
    forged = create_jwt(
        other,
        user_id=uuid.uuid4(),
        role="admin",
        token_type="access",
        mfa=True,
        lifetime=timedelta(minutes=5),
    )
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, forged, "access")


def test_unsigned_jwt_is_rejected() -> None:
    payload = {
        "sub": str(uuid.uuid4()),
        "typ": "access",
        "jti": "x",
        "iss": "meridian-dental",
        "iat": 0,
        "exp": 9999999999,
    }
    unsigned = jwt.encode(payload, key="", algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, unsigned, "access")


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidTokenError):
        decode_jwt(SETTINGS, "not.a.jwt", "access")


# --- TOTP ---------------------------------------------------------------------------


def test_totp_accepts_current_code_and_rejects_others() -> None:
    secret = pyotp.random_base32()
    assert verify_totp(secret, pyotp.TOTP(secret).now()) is True
    assert verify_totp(secret, "000000") is False or pyotp.TOTP(secret).now() == "000000"


def test_totp_tolerates_one_step_of_clock_drift_but_not_more() -> None:
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    now = datetime.now(UTC).timestamp()
    assert verify_totp(secret, totp.at(int(now - 30))) is True
    assert verify_totp(secret, totp.at(int(now - 120))) is False


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 345"])
def test_totp_rejects_malformed_codes(bad: str) -> None:
    assert verify_totp(pyotp.random_base32(), bad) is False
