import tempfile
import unittest
from pathlib import Path

from email_sender.campaign import build_messages, build_test_message, plan_campaign, sample_recipient
from email_sender.sender import SendLog
from email_sender.templates import parse_template

from .helpers import make_settings


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.csv = root / "people.csv"
        self.csv.write_text(
            "email,name,status,tags\n"
            "ana@example.com,Ana,,tester\n"
            "bo@example.com,Bo,,tester\n"
            "cy@example.com,Cy,,newsletter\n"
            "di@example.com,Di,unsubscribed,tester\n",
            encoding="utf-8",
        )
        self.log = SendLog(root / "log.csv")
        self.template = parse_template("Subject: Hi $first_name\n\nHello $name\n")

    def test_plan_skips_already_sent_and_applies_limit(self):
        self.log.record("welcome", "ana@example.com", "sent")
        plan = plan_campaign(self.csv, {"tester"}, "welcome", self.log)
        self.assertEqual([r.email for r in plan.eligible], ["ana@example.com", "bo@example.com"])
        self.assertEqual(plan.already_sent, 1)
        self.assertEqual([r.email for r in plan.pending], ["bo@example.com"])
        self.assertEqual(len(plan.skipped), 1)  # di is unsubscribed
        self.assertEqual(len(plan_campaign(self.csv, None, "other", self.log, limit=2).pending), 2)

    def test_build_messages_one_per_recipient(self):
        plan = plan_campaign(self.csv, None, "welcome", self.log)
        messages = build_messages(make_settings(), self.template, plan.pending)
        self.assertEqual([str(m["Subject"]) for _, m in messages], ["Hi Ana", "Hi Bo", "Hi Cy"])

    def test_test_message_goes_only_to_tester(self):
        plan = plan_campaign(self.csv, None, "welcome", self.log)
        sample = sample_recipient(plan, "me@example.com")
        msg = build_test_message(make_settings(), self.template, sample, "me@example.com")
        self.assertEqual((msg["To"], msg["Subject"]), ("me@example.com", "[TEST] Hi Ana"))
        self.assertEqual(sample_recipient(None, "me@example.com").email, "me@example.com")


if __name__ == "__main__":
    unittest.main()
