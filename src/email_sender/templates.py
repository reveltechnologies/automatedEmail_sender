"""Email templates: a subject line plus a plain-text (and optional HTML) body.

A text template looks like::

    Subject: Welcome to the beta, $first_name!

    Hi $first_name,
    ...

Placeholders use ``$name`` / ``${name}`` syntax; write ``$$`` for a literal
dollar sign. Only the placeholders in ``PLACEHOLDERS`` are allowed, so a
typo fails before anything is sent instead of reaching subscribers.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from string import Template

from .recipients import Recipient

PLACEHOLDERS = ("name", "first_name", "email")
NAME_FALLBACK = "there"


class TemplateError(Exception):
    """Raised when a template file is malformed or uses unknown placeholders."""


@dataclass(frozen=True)
class EmailTemplate:
    subject: str
    text: str
    html: str | None = None


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str | None = None


def _check(source: str, label: str) -> None:
    tmpl = Template(source)
    if not tmpl.is_valid():
        raise TemplateError(f"{label}: stray '$' - write '$$' for a literal dollar sign")
    unknown = sorted(set(tmpl.get_identifiers()) - set(PLACEHOLDERS))
    if unknown:
        allowed = ", ".join(f"${p}" for p in PLACEHOLDERS)
        raise TemplateError(f"{label}: unknown placeholder(s) {', '.join('$' + u for u in unknown)} (allowed: {allowed})")


def load_template(text_path: Path, html_path: Path | None = None) -> EmailTemplate:
    raw = text_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    header, sep, body = raw.partition("\n\n")
    if not sep or not header.lower().startswith("subject:"):
        raise TemplateError(f"{text_path}: must start with a 'Subject: ...' line followed by a blank line")
    subject = header[len("subject:"):].strip()
    if not subject or "\n" in subject:
        raise TemplateError(f"{text_path}: the subject must be a single, non-empty line")
    body = body.strip("\n") + "\n"
    html_body = html_path.read_text(encoding="utf-8-sig") if html_path else None

    _check(subject, f"{text_path} (subject)")
    _check(body, str(text_path))
    if html_body is not None:
        _check(html_body, str(html_path))
    return EmailTemplate(subject=subject, text=body, html=html_body)


def placeholder_values(recipient: Recipient) -> dict[str, str]:
    name = recipient.name or NAME_FALLBACK
    return {
        "name": name,
        "first_name": name.split()[0],
        "email": recipient.email,
    }


def render(template: EmailTemplate, recipient: Recipient) -> RenderedEmail:
    values = placeholder_values(recipient)
    html_body = None
    if template.html is not None:
        # Names come from a CSV that may contain anything; never let them become markup.
        escaped = {key: html.escape(value) for key, value in values.items()}
        html_body = Template(template.html).substitute(escaped)
    return RenderedEmail(
        subject=Template(template.subject).substitute(values),
        text=Template(template.text).substitute(values),
        html=html_body,
    )
