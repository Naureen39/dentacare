import pytest

from app.core.crypto import CryptoError, FieldCipher, generate_key, parse_key


def _cipher(active: str | None = None, old: str = "") -> FieldCipher:
    return FieldCipher.from_settings(active or generate_key("k1"), old)


def test_round_trip_and_unique_ciphertexts() -> None:
    cipher = _cipher()
    first = cipher.encrypt("1990-04-12", "patients.dob")
    second = cipher.encrypt("1990-04-12", "patients.dob")

    assert first != second  # random nonce
    assert "1990" not in first
    assert cipher.decrypt(first, "patients.dob") == "1990-04-12"
    assert cipher.decrypt(second, "patients.dob") == "1990-04-12"


def test_ciphertext_carries_the_key_id_prefix() -> None:
    assert _cipher().encrypt("x", "f").startswith("k1:")


def test_value_cannot_be_moved_to_another_field() -> None:
    cipher = _cipher()
    token = cipher.encrypt("555-0100", "patients.phone")
    with pytest.raises(CryptoError):
        cipher.decrypt(token, "patients.address")


def test_tampered_value_is_rejected() -> None:
    cipher = _cipher()
    token = cipher.encrypt("secret", "f")
    key_id, _, payload = token.partition(":")
    flipped = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB")
    with pytest.raises(CryptoError):
        cipher.decrypt(f"{key_id}:{flipped}", "f")


@pytest.mark.parametrize("bad", ["", "nokeyid", "unknown:abcd", "k1:"])
def test_malformed_values_are_rejected(bad: str) -> None:
    with pytest.raises(CryptoError):
        _cipher().decrypt(bad, "f")


def test_old_keys_still_decrypt_after_rotation() -> None:
    old_entry = generate_key("k1")
    old = FieldCipher.from_settings(old_entry)
    token = old.encrypt("kept", "f")

    rotated = FieldCipher.from_settings(generate_key("k2"), old_entry)
    assert rotated.decrypt(token, "f") == "kept"
    assert rotated.needs_rotation(token) is True
    assert rotated.encrypt("new", "f").startswith("k2:")
    assert rotated.needs_rotation(rotated.encrypt("new", "f")) is False


def test_wrong_key_cannot_decrypt() -> None:
    token = _cipher(generate_key("k1")).encrypt("data", "f")
    with pytest.raises(CryptoError):
        _cipher(generate_key("k1")).decrypt(token, "f")


def test_optional_helpers_pass_empty_values_through() -> None:
    cipher = _cipher()
    assert cipher.encrypt_optional(None, "f") is None
    assert cipher.encrypt_optional("", "f") is None
    assert cipher.decrypt_optional(None, "f") is None


@pytest.mark.parametrize("entry", ["", "nokey", "k1:", "k1:c2hvcnQ="])
def test_invalid_key_entries_are_rejected(entry: str) -> None:
    with pytest.raises(ValueError):
        parse_key(entry)


def test_development_fallback_key_is_derived_from_the_secret() -> None:
    a = FieldCipher.from_settings("", "", "secret-one")
    b = FieldCipher.from_settings("", "", "secret-one")
    c = FieldCipher.from_settings("", "", "secret-two")
    token = a.encrypt("x", "f")
    assert b.decrypt(token, "f") == "x"
    with pytest.raises(CryptoError):
        c.decrypt(token, "f")
