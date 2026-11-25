import smtplib
import tempfile
import unittest
from pathlib import Path

from email_sender.recipients import Recipient
from email_sender.sender import SendLog, build_message, send_all
from email_sender.templates import RenderedEmail

from .helpers import FakeSMTP, make_settings


def message_for(email, name=""):
    settings = make_settings()
    recipient = Recipient(email, name)
    return recipient, build_message(settings, recipient, RenderedEmail("Hello", "Body\n"))


class BuildMessageTests(unittest.TestCase):
    def test_one_recipient_per_message_with_unsubscribe(self):
        _, msg = message_for("ana@example.com", "Ana Rossi")
        self.assertEqual(msg["To"], "Ana Rossi <ana@example.com>")
        self.assertIsNone(msg["Cc"])
        self.assertIsNone(msg["Bcc"])
        self.assertEqual(msg["From"], "Example Team <team@example.com>")
        self.assertEqual(msg["List-Unsubscribe"], "<mailto:unsubscribe@example.com?subject=unsubscribe>")
        body = msg.get_body(("plain",)).get_content()
        self.assertTrue(body.startswith("Body\n"))
        self.assertIn("unsubscribe@example.com", body)

    def test_html_part_gets_footer_inside_body(self):
        settings = make_settings()
        msg = build_message(settings, Recipient("a@example.com"),
                            RenderedEmail("Hi", "Body\n", "<html><body><p>Hi</p></body></html>"))
        html = msg.get_body(("html",)).get_content()
        self.assertIn("unsubscribe@example.com", html)
        self.assertTrue(html.rstrip().endswith("</body></html>"))

    def test_header_injection_is_rejected(self):
        with self.assertRaises(ValueError):
            build_message(make_settings(), Recipient("a@example.com"),
                          RenderedEmail("Hi\r\nBcc: victim@example.com", "Body\n"))


class SendAllTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = SendLog(Path(self.tmp.name) / "state" / "sent_log.csv")
        self.messages = [message_for(f"user{i}@example.com") for i in range(3)]

    def run_send(self, server):
        return send_all(make_settings(), self.messages, campaign="welcome", log=self.log,
                        delay=0, connect=server, progress=lambda _: None)

    def test_sends_each_and_logs(self):
        server = FakeSMTP()
        report = self.run_send(server)
        self.assertEqual(report.sent, 3)
        self.assertEqual(len(server.sent), 3)
        self.assertTrue(server.closed)
        self.assertEqual(self.log.sent_to("welcome"), {f"user{i}@example.com" for i in range(3)})
        self.assertEqual(self.log.sent_to("other-campaign"), set())

    def test_refused_recipient_is_skipped_not_fatal(self):
        report = self.run_send(FakeSMTP(refuse={"user1@example.com"}))
        self.assertEqual(report.sent, 2)
        self.assertEqual([email for email, _ in report.failed], ["user1@example.com"])
        self.assertNotIn("user1@example.com", self.log.sent_to("welcome"))

    def test_connection_loss_stops_and_can_resume(self):
        server = FakeSMTP(disconnect_after=1)
        with self.assertRaises(smtplib.SMTPServerDisconnected):
            self.run_send(server)
        self.assertTrue(server.closed)
        self.assertEqual(self.log.sent_to("welcome"), {"user0@example.com"})


if __name__ == "__main__":
    unittest.main()
