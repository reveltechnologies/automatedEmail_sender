import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from email_sender.config import KEYS, ConfigError, load_settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Start from an environment without any of our keys.
        clean_env = {k: v for k, v in os.environ.items() if k not in KEYS}
        patcher = mock.patch.dict(os.environ, clean_env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def env_file(self, text):
        path = Path(self.tmp.name) / ".env"
        path.write_text(text, encoding="utf-8")
        return path

    FULL = (
        "# comment\n"
        "SENDER_EMAIL=team@example.com\n"
        'SENDER_NAME="Example Team"\n'
        "SMTP_HOST=smtp.example.com\n"
        "SMTP_USERNAME=team@example.com\n"
        "SMTP_PASSWORD='p@ss word'\n"
    )

    def test_loads_file_with_defaults(self):
        s = load_settings(self.env_file(self.FULL))
        self.assertEqual(s.sender_name, "Example Team")
        self.assertEqual(s.smtp_password, "p@ss word")
        self.assertEqual(s.smtp_port, 587)
        self.assertEqual(s.smtp_security, "starttls")
        self.assertEqual(s.unsubscribe_email, "team@example.com")

    def test_ssl_default_port(self):
        s = load_settings(self.env_file(self.FULL + "SMTP_SECURITY=SSL\n"))
        self.assertEqual((s.smtp_security, s.smtp_port), ("ssl", 465))

    def test_environment_overrides_file(self):
        with mock.patch.dict(os.environ, {"SMTP_PASSWORD": "from-env"}):
            self.assertEqual(load_settings(self.env_file(self.FULL)).smtp_password, "from-env")

    def test_missing_settings_listed(self):
        with self.assertRaisesRegex(ConfigError, "SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD"):
            load_settings(self.env_file("SENDER_EMAIL=team@example.com\n"))

    def test_preview_needs_no_credentials(self):
        s = load_settings(self.env_file("SENDER_EMAIL=team@example.com\n"), require_smtp=False)
        self.assertEqual(s.sender_email, "team@example.com")

    def test_rejects_plaintext_security(self):
        with self.assertRaises(ConfigError):
            load_settings(self.env_file(self.FULL + "SMTP_SECURITY=none\n"))

    def test_rejects_bad_port_and_address(self):
        with self.assertRaises(ConfigError):
            load_settings(self.env_file(self.FULL + "SMTP_PORT=abc\n"))
        with self.assertRaises(ConfigError):
            load_settings(self.env_file(self.FULL + "REPLY_TO=not-an-address\n"))

    def test_password_not_in_repr(self):
        s = load_settings(self.env_file(self.FULL))
        self.assertNotIn("p@ss word", repr(s))


if __name__ == "__main__":
    unittest.main()
