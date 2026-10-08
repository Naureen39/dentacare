"""Sandbox card payments.

This module simulates a card processor. It validates the shape of the details a person
types, applies a few fixed test outcomes and returns a generated reference. Card numbers,
expiry dates and security codes exist only for the duration of the call: nothing here is
stored or logged, and callers keep only the last four digits.
"""

import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

# Well known test numbers with fixed outcomes. Any other Luhn valid number is approved.
DECLINED_NUMBERS = {"4000000000000002": "The card was declined."}
INSUFFICIENT_FUNDS_NUMBERS = {"4000000000009995": "The card has insufficient funds."}


class CardValidationError(ValueError):
    """The supplied card details are malformed."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    reference: str
    last4: str
    decline_message: str | None = None


def normalize_number(raw: str) -> str:
    return re.sub(r"[ -]", "", raw)


def luhn_valid(number: str) -> bool:
    """Luhn checksum over a string of digits."""
    if not number.isdigit():
        return False
    total = 0
    for position, char in enumerate(reversed(number)):
        digit = int(char)
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_card(
    number: str, exp_month: int, exp_year: int, cvv: str, *, now: datetime | None = None
) -> str:
    """Validate the details and return the normalized number."""
    current = now or datetime.now(UTC)
    digits = normalize_number(number)
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        raise CardValidationError("card_number", "Enter a valid card number.")
    if not luhn_valid(digits):
        raise CardValidationError("card_number", "The card number is not valid.")
    if not 1 <= exp_month <= 12:
        raise CardValidationError("exp_month", "Enter a month from 1 to 12.")
    year = exp_year + 2000 if exp_year < 100 else exp_year
    if (year, exp_month) < (current.year, current.month):
        raise CardValidationError("exp_year", "The card has expired.")
    if not re.fullmatch(r"\d{3,4}", cvv):
        raise CardValidationError("cvv", "Enter the 3 or 4 digit security code.")
    return digits


def charge(number: str, exp_month: int, exp_year: int, cvv: str) -> ChargeResult:
    digits = validate_card(number, exp_month, exp_year, cvv)
    reference = f"SBX-{secrets.token_hex(6).upper()}"
    last4 = digits[-4:]
    if digits in DECLINED_NUMBERS:
        return ChargeResult(False, reference, last4, DECLINED_NUMBERS[digits])
    if digits in INSUFFICIENT_FUNDS_NUMBERS:
        return ChargeResult(False, reference, last4, INSUFFICIENT_FUNDS_NUMBERS[digits])
    return ChargeResult(True, reference, last4)
