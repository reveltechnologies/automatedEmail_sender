import tempfile
import unittest
from pathlib import Path

from email_sender.recipients import RecipientError, is_valid_email, load_recipients


class LoadRecipientsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, text, encoding="utf-8"):
        path = Path(self.tmp.name) / "people.csv"
        path.write_text(text, encoding=encoding)
        return path

    def test_reads_names_tags_and_lowercases_email(self):
        path = self.write("email,name,status,tags\nAna@Example.com,Ana Rossi,subscribed,tester beta\n")
        result = load_recipients(path)
        self.assertEqual(len(result.recipients), 1)
        r = result.recipients[0]
        self.assertEqual(r.email, "ana@example.com")
        self.assertEqual(r.name, "Ana Rossi")
        self.assertEqual(r.tags, {"tester", "beta"})

    def test_only_email_column_required(self):
        result = load_recipients(self.write("email\nbo@example.com\n"))
        self.assertEqual([r.email for r in result.recipients], ["bo@example.com"])

    def test_missing_email_column(self):
        with self.assertRaises(RecipientError):
            load_recipients(self.write("name\nAna\n"))

    def test_invalid_and_blank_emails_are_reported(self):
        result = load_recipients(self.write("email,name\nnot-an-email,X\n,Y\nok@example.com,Z\n"))
        self.assertEqual([r.email for r in result.recipients], ["ok@example.com"])
        self.assertEqual(len(result.skipped), 2)

    def test_unsubscribed_blocks_address_everywhere(self):
        path = self.write(
            "email,status\n"
            "cy@example.com,subscribed\n"
            "CY@example.com,unsubscribed\n"
            "di@example.com,\n"
        )
        result = load_recipients(path)
        self.assertEqual([r.email for r in result.recipients], ["di@example.com"])
        self.assertTrue(any("unsubscribed" in s for s in result.skipped))

    def test_duplicates_removed(self):
        result = load_recipients(self.write("email\nan@example.com\nAN@example.com\n"))
        self.assertEqual(len(result.recipients), 1)
        self.assertIn("duplicate", result.skipped[0])

    def test_tag_filter(self):
        path = self.write("email,tags\na@example.com,tester\nb@example.com,newsletter\nc@example.com,Tester|vip\n")
        result = load_recipients(path, {"tester"})
        self.assertEqual([r.email for r in result.recipients], ["a@example.com", "c@example.com"])

    def test_semicolon_csv_with_excel_bom(self):
        path = self.write("email;name\nzoe@example.com;Zoë\n", encoding="utf-8-sig")
        result = load_recipients(path)
        self.assertEqual(result.recipients[0].name, "Zoë")

    def test_newlines_in_name_are_removed(self):
        path = self.write('email,name\nev@example.com,"Eve\r\nBcc: victim@example.com"\n')
        self.assertEqual(load_recipients(path).recipients[0].name, "Eve Bcc: victim@example.com")


class EmailValidationTests(unittest.TestCase):
    def test_valid(self):
        for value in ("a@b.co", "first.last+tag@sub.example.co.uk"):
            self.assertTrue(is_valid_email(value), value)

    def test_invalid(self):
        for value in ("", "a@b", "a b@c.com", "a@b.com\nBcc: x@y.com", "<a@b.com>", "a@b.com,c@d.com"):
            self.assertFalse(is_valid_email(value), value)


if __name__ == "__main__":
    unittest.main()
