"""Masking of personal details in text shown to reviewers, such as chat transcripts."""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# A phone number or other long run of digits, with the usual separators.
NUMBER = re.compile(r"(?<![\w])\+?\d[\d\s().-]{6,}\d(?![\w])")
# A date written with digits, such as 03/04/1988.
DATE = re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{2}|\d{4})\b")
NAME_INTRO = re.compile(
    r"\b(my name is|i am|i'm|this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE
)


def mask_text(text: str) -> str:
    """Replace email addresses, phone numbers, dates and introduced names with placeholders."""
    text = EMAIL.sub("[email]", text)
    text = DATE.sub("[date]", text)
    text = NUMBER.sub("[number]", text)
    return NAME_INTRO.sub(lambda m: f"{m.group(1)} [name]", text)
