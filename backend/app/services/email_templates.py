"""Branded email rendering with Jinja2.

Every message has an HTML and a plain text version built from the same context. The HTML
uses inline styles only and contains no images, remote resources or tracking pixels.
"""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.core.config import Settings
from app.services.mailer import Attachment, EmailContent

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

SUBJECTS = {
    "verify_email": "{clinic_name}: confirm your email address",
    "account_exists": "{clinic_name}: account already exists",
    "password_reset": "{clinic_name}: reset your password",
    "guest_code": "{clinic_name}: your verification code",
    "confirmation": "Appointment booked: {service} on {short_date}",
    "reminder": "{subject_hint}",
    "followup": "Thank you for visiting {clinic_name}",
    "recall": "Time for your next check-up at {clinic_name}",
}

_environment = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


def render_email(
    kind: str,
    *,
    to: str,
    settings: Settings,
    attachments: tuple[Attachment, ...] = (),
    **context: Any,
) -> EmailContent:
    if kind not in SUBJECTS:
        raise ValueError(f"unknown email template: {kind}")
    base = {
        "clinic_name": settings.clinic_name,
        "clinic_address": settings.clinic_address,
        "clinic_phone": settings.clinic_phone,
        "clinic_email": settings.clinic_email,
        "base_url": settings.public_base_url,
    }
    values = {**base, **context}
    subject = SUBJECTS[kind].format(**values)
    values["subject"] = subject
    html = _environment.get_template(f"{kind}.html.j2").render(**values)
    text = _environment.get_template(f"{kind}.txt.j2").render(**values)
    return EmailContent(to=to, subject=subject, text=text, html=html, attachments=attachments)
