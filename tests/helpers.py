from __future__ import annotations

import smtplib

from email_sender.config import Settings


def make_settings(**overrides) -> Settings:
    values = dict(
        sender_email="team@example.com",
        sender_name="Example Team",
        reply_to=None,
        unsubscribe_email="unsubscribe@example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security="starttls",
        smtp_username="team@example.com",
        smtp_password="secret-password",
    )
    values.update(overrides)
    return Settings(**values)


class FakeSMTP:
    """Stands in for smtplib.SMTP; records messages instead of sending them."""

    def __init__(self, refuse=(), disconnect_after=None):
        self.sent = []
        self.refuse = set(refuse)
        self.disconnect_after = disconnect_after
        self.closed = False

    def __call__(self, settings):  # used as the `connect` callable
        return self

    def send_message(self, msg):
        to = msg["To"].addresses[0].addr_spec
        if self.disconnect_after is not None and len(self.sent) >= self.disconnect_after:
            raise smtplib.SMTPServerDisconnected("connection lost")
        if to in self.refuse:
            raise smtplib.SMTPRecipientsRefused({to: (550, b"no such user")})
        self.sent.append(msg)

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True
