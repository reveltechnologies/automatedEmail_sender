import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from email_sender import cli
from email_sender.config import KEYS

from .helpers import FakeSMTP

ENV = (
    "SENDER_EMAIL=team@example.com\n"
    "SENDER_NAME=Example Team\n"
    "SMTP_HOST=smtp.example.com\n"
    "SMTP_USERNAME=team@example.com\n"
    "SMTP_PASSWORD=secret\n"
)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        clean_env = {k: v for k, v in os.environ.items() if k not in KEYS}
        patcher = mock.patch.dict(os.environ, clean_env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        (root / ".env").write_text(ENV, encoding="utf-8")
        (root / "welcome.txt").write_text("Subject: Welcome $first_name\n\nHi $first_name!\n", encoding="utf-8")
        (root / "people.csv").write_text(
            "email,name,status,tags\n"
            "ana@example.com,Ana Rossi,subscribed,tester\n"
            "bo@example.com,Bo,unsubscribed,tester\n"
            "cy@example.com,Cy,,newsletter\n",
            encoding="utf-8",
        )
        self.base = [
            "-t", str(root / "welcome.txt"),
            "-r", str(root / "people.csv"),
            "--env-file", str(root / ".env"),
            "--log", str(root / "state" / "log.csv"),
            "--delay", "0",
        ]
        self.server = FakeSMTP()
        patcher = mock.patch.object(cli, "open_smtp", self.server)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(self.base + list(extra))
        return code, out.getvalue(), err.getvalue()

    def test_preview_sends_nothing(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(self.server.sent, [])
        self.assertIn("Subject: Welcome Ana", out)
        self.assertIn("nothing was sent", out)
        self.assertNotIn("bo@example.com", out.split("Recipients:")[1])

    def test_send_then_rerun_sends_nothing_new(self):
        code, out, _ = self.run_cli("--send", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(sorted(m["To"].addresses[0].addr_spec for m in self.server.sent),
                         ["ana@example.com", "cy@example.com"])
        self.server.sent.clear()
        code, out, _ = self.run_cli("--send", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual(self.server.sent, [])
        self.assertIn("Nothing to send", out)

    def test_tag_filter(self):
        self.run_cli("--send", "--yes", "--tag", "tester")
        self.assertEqual([m["To"].addresses[0].addr_spec for m in self.server.sent], ["ana@example.com"])

    def test_limit_sends_in_batches(self):
        self.run_cli("--send", "--yes", "--limit", "1")
        self.assertEqual([m["To"].addresses[0].addr_spec for m in self.server.sent], ["ana@example.com"])
        self.run_cli("--send", "--yes", "--limit", "1")
        self.assertEqual([m["To"].addresses[0].addr_spec for m in self.server.sent],
                         ["ana@example.com", "cy@example.com"])

    def test_confirmation_declined(self):
        with mock.patch("builtins.input", return_value="no"):
            code, out, _ = self.run_cli("--send")
        self.assertEqual(code, 1)
        self.assertEqual(self.server.sent, [])

    def test_test_to_sends_single_marked_copy(self):
        code, out, _ = self.run_cli("--test-to", "me@example.com")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.server.sent), 1)
        msg = self.server.sent[0]
        self.assertEqual(msg["To"], "me@example.com")
        self.assertEqual(msg["Subject"], "[TEST] Welcome Ana")

    def test_template_error_reported(self):
        Path(self.tmp.name, "welcome.txt").write_text("Subject: Hi\n\nHi $nmae\n", encoding="utf-8")
        code, _, err = self.run_cli("--send", "--yes")
        self.assertEqual(code, 1)
        self.assertIn("$nmae", err)
        self.assertEqual(self.server.sent, [])


if __name__ == "__main__":
    unittest.main()
