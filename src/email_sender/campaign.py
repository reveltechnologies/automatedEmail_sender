"""Work out who a campaign goes to and build the messages; shared by the CLI and the web page."""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from .config import Settings
from .recipients import Recipient, load_recipients
from .sender import SendLog, build_message
from .templates import EmailTemplate, render


@dataclass
class Plan:
    campaign: str
    eligible: list[Recipient] = field(default_factory=list)
    already_sent: int = 0
    pending: list[Recipient] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def plan_campaign(recipients_path: Path, tags: set[str] | None, campaign: str, log: SendLog,
                  limit: int | None = None) -> Plan:
    loaded = load_recipients(recipients_path, tags or None)
    already = log.sent_to(campaign)
    pending = [r for r in loaded.recipients if r.email not in already]
    if limit is not None:
        pending = pending[:limit]
    return Plan(
        campaign=campaign,
        eligible=loaded.recipients,
        already_sent=len(already & {r.email for r in loaded.recipients}),
        pending=pending,
        skipped=loaded.skipped,
    )


def build_messages(settings: Settings, template: EmailTemplate,
                   recipients: list[Recipient]) -> list[tuple[Recipient, EmailMessage]]:
    """Render every message up front so a template problem shows before the first send."""
    return [(r, build_message(settings, r, render(template, r))) for r in recipients]


def sample_recipient(plan: Plan | None, fallback_email: str) -> Recipient:
    if plan is not None and (plan.pending or plan.eligible):
        return (plan.pending or plan.eligible)[0]
    return Recipient(email=fallback_email)


def build_test_message(settings: Settings, template: EmailTemplate, sample: Recipient, to: str) -> EmailMessage:
    """A copy rendered for ``sample`` but addressed only to ``to``, marked [TEST]."""
    rendered = render(template, sample)
    msg = build_message(settings, sample, rendered)
    msg.replace_header("To", to)
    msg.replace_header("Subject", f"[TEST] {rendered.subject}")
    return msg
