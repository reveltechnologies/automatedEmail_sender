"""SMTP connection and sender identity settings.

Values come from environment variables, optionally pre-loaded from a
``.env`` file. Real environment variables win over the file, so secrets
can be injected by a password manager or CI without being written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .recipients import is_valid_email

KEYS = (
    "SENDER_EMAIL",
    "SENDER_NAME",
    "REPLY_TO",
    "UNSUBSCRIBE_EMAIL",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_SECURITY",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
)
SECURITY_MODES = ("starttls", "ssl")
DEFAULT_PORTS = {"starttls": 587, "ssl": 465}


class ConfigError(Exception):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    sender_email: str
    sender_name: str
    reply_to: str | None
    unsubscribe_email: str
    smtp_host: str
    smtp_port: int
    smtp_security: str
    smtp_username: str
    smtp_password: str = field(repr=False)

    @property
    def display_name(self) -> str:
        return self.sender_name or self.sender_email


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfigError(f"{path}:{lineno}: expected KEY=VALUE")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_settings(env_file: Path | None = Path(".env"), *, require_smtp: bool = True) -> Settings:
    """Load settings. With ``require_smtp=False`` (previews) no login details are needed."""
    values: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        values.update(parse_env_file(env_file))
    values.update({key: os.environ[key] for key in KEYS if key in os.environ})

    def get(key: str) -> str:
        return values.get(key, "").strip()

    required = ["SENDER_EMAIL"]
    if require_smtp:
        required += ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD"]
    missing = [key for key in required if not get(key)]
    if missing:
        where = f" (looked in the environment and {env_file})" if env_file else ""
        raise ConfigError(f"missing setting(s): {', '.join(missing)}{where}")

    security = (get("SMTP_SECURITY") or "starttls").lower()
    if security not in SECURITY_MODES:
        raise ConfigError(f"SMTP_SECURITY must be one of {', '.join(SECURITY_MODES)}, not {security!r}")

    port_text = get("SMTP_PORT")
    try:
        port = int(port_text) if port_text else DEFAULT_PORTS[security]
    except ValueError:
        raise ConfigError(f"SMTP_PORT must be a number, not {port_text!r}") from None

    sender_email = get("SENDER_EMAIL")
    unsubscribe_email = get("UNSUBSCRIBE_EMAIL") or sender_email
    reply_to = get("REPLY_TO") or None
    for key, value in (("SENDER_EMAIL", sender_email), ("UNSUBSCRIBE_EMAIL", unsubscribe_email), ("REPLY_TO", reply_to)):
        if value is not None and not is_valid_email(value):
            raise ConfigError(f"{key} is not a valid email address: {value!r}")

    return Settings(
        sender_email=sender_email,
        sender_name=" ".join(get("SENDER_NAME").split()),
        reply_to=reply_to,
        unsubscribe_email=unsubscribe_email,
        smtp_host=get("SMTP_HOST"),
        smtp_port=port,
        smtp_security=security,
        smtp_username=get("SMTP_USERNAME"),
        smtp_password=values.get("SMTP_PASSWORD", ""),
    )
