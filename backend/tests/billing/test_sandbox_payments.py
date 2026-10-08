from datetime import UTC, datetime

import pytest

from app.services.sandbox_payments import (
    CardValidationError,
    charge,
    luhn_valid,
    normalize_number,
    validate_card,
)

NOW = datetime(2027, 6, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    "number",
    [
        "4242424242424242",
        "4111111111111111",
        "5555555555554444",
        "378282246310005",
        "6011111111111117",
    ],
)
def test_known_valid_test_numbers_pass_luhn(number: str) -> None:
    assert luhn_valid(number)


@pytest.mark.parametrize(
    "number", ["4242424242424241", "1234567812345678", "0000000000000001", "abcd", ""]
)
def test_invalid_numbers_fail_luhn(number: str) -> None:
    assert not luhn_valid(number)


def test_single_digit_transposition_is_detected() -> None:
    assert luhn_valid("4242424242424242")
    assert not luhn_valid("4422424242424242")


def test_spaces_and_dashes_are_ignored() -> None:
    assert normalize_number("4242 4242-4242 4242") == "4242424242424242"


def test_valid_details_return_the_normalized_number() -> None:
    assert validate_card("4242 4242 4242 4242", 12, 2030, "123", now=NOW) == "4242424242424242"


@pytest.mark.parametrize(
    ("number", "month", "year", "cvv", "field"),
    [
        ("4242", 12, 2030, "123", "card_number"),
        ("4242424242424241", 12, 2030, "123", "card_number"),
        ("4242 4242 4242 42ab", 12, 2030, "123", "card_number"),
        ("4242424242424242", 13, 2030, "123", "exp_month"),
        ("4242424242424242", 0, 2030, "123", "exp_month"),
        ("4242424242424242", 5, 2027, "123", "exp_year"),
        ("4242424242424242", 12, 2026, "123", "exp_year"),
        ("4242424242424242", 12, 2030, "12", "cvv"),
        ("4242424242424242", 12, 2030, "12a", "cvv"),
        ("4242424242424242", 12, 2030, "12345", "cvv"),
    ],
)
def test_invalid_details_name_the_offending_field(
    number: str, month: int, year: int, cvv: str, field: str
) -> None:
    with pytest.raises(CardValidationError) as raised:
        validate_card(number, month, year, cvv, now=NOW)
    assert raised.value.field == field


def test_card_expiring_this_month_is_still_valid_and_two_digit_years_work() -> None:
    assert validate_card("4242424242424242", 6, 2027, "123", now=NOW)
    assert validate_card("4242424242424242", 12, 30, "123", now=NOW)


def test_charge_approves_and_returns_only_last_four_and_a_reference() -> None:
    result = charge("4242 4242 4242 4242", 12, 2099, "123")
    assert result.approved and result.last4 == "4242"
    assert result.reference.startswith("SBX-") and len(result.reference) == 16
    assert "4242424242424242" not in repr(result)


def test_charge_references_are_unique() -> None:
    assert len({charge("4242424242424242", 12, 2099, "123").reference for _ in range(20)}) == 20


def test_test_numbers_with_fixed_outcomes_are_declined() -> None:
    declined = charge("4000000000000002", 12, 2099, "123")
    funds = charge("4000000000009995", 12, 2099, "123")
    assert not declined.approved and "declined" in (declined.decline_message or "")
    assert not funds.approved and "insufficient" in (funds.decline_message or "")
