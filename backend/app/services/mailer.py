"""Outgoing email.

Two entry points exist on purpose. ``send`` never raises: authentication flows use it so that
a delivery problem cannot reveal whether an account exists. ``deliver`` raises
``MailDeliveryError``: background jobs use it so they can retry with backoff and finally
record a dead letter.
"""

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)

SEND_TIMEOUT_SECONDS = 10


class MailDeliveryError(Exception):
    """The message could not be handed to the mail server."""


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes
    maintype: str = "application"
    subtype: str = "octet-stream"
    params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EmailContent:
    to: str
    subject: str
    text: str
    html: str | None = None
    attachments: tuple[Attachment, ...] = ()


class Mailer(Protocol):
    async def send(self, to: str, subject: str, text_body: str) -> None: ...

    async def send_content(self, content: EmailContent) -> None: ...

    async def deliver(self, content: EmailContent) -> None: ...


def build_message(settings: Settings, content: EmailContent) -> EmailMessage:
    message = EmailMessage()
    message["From"] = f"{settings.clinic_name} <{settings.mail_from}>"
    message["Reply-To"] = settings.clinic_email
    message["To"] = content.to
    message["Subject"] = content.subject
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(content.text)
    if content.html:
        message.add_alternative(content.html, subtype="html")
    for attachment in content.attachments:
        message.add_attachment(
            attachment.content,
            maintype=attachment.maintype,
            subtype=attachment.subtype,
            filename=attachment.filename,
            params=attachment.params or None,
        )
    return message


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def deliver(self, content: EmailContent) -> None:
        try:
            await aiosmtplib.send(
                build_message(self._settings, content),
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                username=self._settings.smtp_user or None,
                password=self._settings.smtp_pass or None,
                start_tls=bool(self._settings.smtp_user),
                timeout=SEND_TIMEOUT_SECONDS,
            )
        except (aiosmtplib.SMTPException, OSError, TimeoutError) as exc:
            raise MailDeliveryError(f"{type(exc).__name__}: {exc}"[:300]) from exc

    async def send_content(self, content: EmailContent) -> None:
        try:
            await self.deliver(content)
        except MailDeliveryError:
            logger.error("email_delivery_failed", subject=content.subject)

    async def send(self, to: str, subject: str, text_body: str) -> None:
        await self.send_content(EmailContent(to=to, subject=subject, text=text_body))


@dataclass
class SentMessage:
    to: str
    subject: str
    body: str
    html: str | None = None
    attachments: tuple[Attachment, ...] = ()


@dataclass
class InMemoryMailer:
    """Collects messages. Used by tests. ``failures`` makes the next deliveries fail."""

    outbox: list[SentMessage] = field(default_factory=list)
    failures: int = 0

    async def deliver(self, content: EmailContent) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise MailDeliveryError("simulated mail server outage")
        self.outbox.append(
            SentMessage(
                content.to, content.subject, content.text, content.html, content.attachments
            )
        )

    async def send_content(self, content: EmailContent) -> None:
        try:
            await self.deliver(content)
        except MailDeliveryError:
            return

    async def send(self, to: str, subject: str, text_body: str) -> None:
        await self.send_content(EmailContent(to=to, subject=subject, text=text_body))
