"""Build one message per recipient and deliver them over a single SMTP session.

Every message is addressed to exactly one person. Recipients are never put
together in To/Cc/Bcc, so no subscriber can see another subscriber's address.
"""

from __future__ import annotations

import csv
import html
import smtplib
import ssl
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import Settings
from .recipients import Recipient
from .templates import RenderedEmail

LOG_FIELDS = ("timestamp", "campaign", "email", "result", "detail")


def footer_text(settings: Settings) -> str:
    return (
        "\n--\n"
        f"You are receiving this email because you signed up for updates from {settings.display_name}.\n"
        f'To unsubscribe, reply with "unsubscribe" or write to {settings.unsubscribe_email}.\n'
    )


def footer_html(settings: Settings) -> str:
    name = html.escape(settings.display_name)
    addr = html.escape(settings.unsubscribe_email)
    return (
        '<hr><p style="font-size:12px;color:#666">'
        f"You are receiving this email because you signed up for updates from {name}. "
        f'To unsubscribe, reply with "unsubscribe" or write to '
        f'<a href="mailto:{addr}?subject=unsubscribe">{addr}</a>.</p>'
    )


def _append_html_footer(body: str, settings: Settings) -> str:
    footer = footer_html(settings)
    index = body.lower().rfind("</body>")
    if index == -1:
        return body + footer
    return body[:index] + footer + body[index:]


def build_message(settings: Settings, recipient: Recipient, rendered: RenderedEmail) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.sender_name, settings.sender_email))
    msg["To"] = formataddr((recipient.name, recipient.email))
    msg["Subject"] = rendered.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.sender_email.rpartition("@")[2])
    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to
    msg["List-Unsubscribe"] = f"<mailto:{settings.unsubscribe_email}?subject=unsubscribe>"
    msg.set_content(rendered.text + footer_text(settings))
    if rendered.html is not None:
        msg.add_alternative(_append_html_footer(rendered.html, settings), subtype="html")
    return msg


class SendLog:
    """Append-only CSV of every delivery attempt, used to resume interrupted runs.

    It contains subscriber addresses, so it lives in ``state/`` (git-ignored).
    """

    def __init__(self, path: Path):
        self.path = path

    def sent_to(self, campaign: str) -> set[str]:
        if not self.path.is_file():
            return set()
        with self.path.open(newline="", encoding="utf-8") as fh:
            return {
                row["email"]
                for row in csv.DictReader(fh)
                if row.get("campaign") == campaign and row.get("result") == "sent"
            }

    def record(self, campaign: str, email: str, result: str, detail: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists()
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if is_new:
                writer.writerow(LOG_FIELDS)
            timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            writer.writerow([timestamp, campaign, email, result, detail])


def open_smtp(settings: Settings, timeout: float = 30.0) -> smtplib.SMTP:
    """Connect and log in. Only encrypted connections are supported."""
    context = ssl.create_default_context()
    if settings.smtp_security == "ssl":
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=timeout, context=context
        )
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    try:
        if settings.smtp_security == "starttls":
            server.ehlo()
            server.starttls(context=context)  # raises if the server can't encrypt
            server.ehlo()
        server.login(settings.smtp_username, settings.smtp_password)
    except BaseException:
        server.close()
        raise
    return server


def _quit(server: smtplib.SMTP) -> None:
    try:
        server.quit()
    except (smtplib.SMTPException, OSError):
        server.close()


def send_test(settings: Settings, msg: EmailMessage, connect: Callable[[Settings], smtplib.SMTP] = open_smtp) -> None:
    server = connect(settings)
    try:
        server.send_message(msg)
    finally:
        _quit(server)


@dataclass
class SendReport:
    sent: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def send_all(
    settings: Settings,
    messages: Sequence[tuple[Recipient, EmailMessage]],
    *,
    campaign: str,
    log: SendLog,
    delay: float = 1.0,
    connect: Callable[[Settings], smtplib.SMTP] = open_smtp,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str], None] = print,
) -> SendReport:
    """Send each message, logging every attempt as it happens.

    A refused recipient is logged and skipped. Any other SMTP or network
    error stops the run (after logging), because it usually means every
    following message would fail too; re-running resumes where it stopped.
    """
    report = SendReport()
    total = len(messages)
    server = connect(settings)
    try:
        for index, (recipient, msg) in enumerate(messages, start=1):
            if index > 1 and delay > 0:
                sleep(delay)
            try:
                server.send_message(msg)
            except smtplib.SMTPRecipientsRefused as exc:
                detail = "; ".join(f"{code} {reason.decode(errors='replace')}" for code, reason in exc.recipients.values())
                log.record(campaign, recipient.email, "failed", detail)
                report.failed.append((recipient.email, detail))
                progress(f"[{index}/{total}] refused {recipient.email}: {detail}")
                continue
            except (smtplib.SMTPException, OSError) as exc:
                log.record(campaign, recipient.email, "failed", str(exc))
                report.failed.append((recipient.email, str(exc)))
                raise
            log.record(campaign, recipient.email, "sent")
            report.sent += 1
            progress(f"[{index}/{total}] sent to {recipient.email}")
    finally:
        _quit(server)
    return report
