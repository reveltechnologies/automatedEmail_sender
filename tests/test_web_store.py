import tempfile
import unittest
from pathlib import Path

from email_sender.recipients import load_recipients
from email_sender.templates import TemplateError
from email_sender.web.store import RecipientTable, StoreError, TemplateStore


class RecipientTableTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "data" / "recipients.csv"
        self.table = RecipientTable(self.path)

    def write(self, text, encoding="utf-8"):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding=encoding)

    def test_missing_file_starts_empty_and_save_creates_it(self):
        data = self.table.load()
        self.assertEqual((data["columns"], data["rows"], data["exists"]), (["email", "name", "status", "tags"], [], False))
        saved = self.table.save(data["columns"], [["ana@example.com", "Ana", "subscribed", "tester"]], data["version"])
        self.assertTrue(saved["exists"])
        self.assertEqual([r.email for r in load_recipients(self.path).recipients], ["ana@example.com"])
        self.assertFalse(self.path.with_name("recipients.csv.bak").exists())  # nothing to back up yet

    def test_extra_columns_and_semicolons_survive_round_trip(self):
        self.write("Email;Name;signup_date\nana@example.com;Zoë Ana;2026-11-01\n", encoding="utf-8-sig")
        data = self.table.load()
        self.assertEqual(data["columns"], ["email", "name", "signup_date", "status", "tags"])
        self.assertEqual(data["rows"], [["ana@example.com", "Zoë Ana", "2026-11-01", "", ""]])
        rows = data["rows"] + [["bo@example.com", "Bo", "2026-11-20", "unsubscribed", ""]]
        self.table.save(data["columns"], rows, data["version"])

        written = self.path.read_bytes()
        self.assertTrue(written.startswith(b"\xef\xbb\xbf"))  # BOM so Excel shows accents
        self.assertIn("email;name;signup_date;status;tags", written.decode("utf-8-sig"))
        self.assertEqual(self.table.load()["rows"][0][2], "2026-11-01")
        self.assertEqual([r.email for r in load_recipients(self.path).recipients], ["ana@example.com"])

    def test_backup_of_previous_version(self):
        self.write("email\nold@example.com\n")
        data = self.table.load()
        self.table.save(data["columns"], [["new@example.com", "", "", ""]], data["version"])
        self.assertIn("old@example.com", self.path.with_name("recipients.csv.bak").read_text(encoding="utf-8"))

    def test_conflict_when_file_changed_elsewhere(self):
        self.write("email\nana@example.com\n")
        data = self.table.load()
        self.write("email\nana@example.com\nexcel-edit@example.com\n")
        with self.assertRaises(StoreError) as ctx:
            self.table.save(data["columns"], data["rows"], data["version"])
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("excel-edit", self.path.read_text(encoding="utf-8"))  # untouched

    def test_row_errors_reported_with_index_and_nothing_written(self):
        self.write("email\nana@example.com\n")
        data = self.table.load()
        rows = [
            ["ana@example.com", "", "", ""],
            ["", "", "", ""],               # blank row: dropped, not an error
            ["not-an-email", "X", "", ""],
            ["", "No Email", "", ""],
            ["ANA@example.com", "", "", ""],  # duplicate
        ]
        with self.assertRaises(StoreError) as ctx:
            self.table.save(data["columns"], rows, data["version"])
        self.assertEqual([d["row"] for d in ctx.exception.details], [2, 3, 4])
        self.assertEqual(self.path.read_text(encoding="utf-8"), "email\nana@example.com\n")

    def test_blank_rows_dropped_and_newlines_flattened(self):
        data = self.table.load()
        self.table.save(data["columns"], [["", "", "", ""], ["ana@example.com", "Ana\nRossi", "", ""]], data["version"])
        self.assertEqual(self.table.load()["rows"], [["ana@example.com", "Ana Rossi", "", ""]])

    def test_duplicate_header_names_are_made_unique(self):
        self.write("Email,email,note,note\nana@example.com,x,a,b\n")
        data = self.table.load()
        self.assertEqual(data["columns"], ["email", "email_2", "note", "note_2", "name", "status", "tags"])
        self.table.save(data["columns"], data["rows"], data["version"])  # must not raise

    def test_bad_columns_rejected(self):
        data = self.table.load()
        for columns in (["name"], ["email", "Email"], ["email", ""], "email"):
            with self.assertRaises(StoreError):
                self.table.save(columns, [], data["version"])


class TemplateStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "templates"
        self.store = TemplateStore(self.dir)

    def test_save_list_get_load(self):
        self.assertEqual(self.store.list(), [])
        self.store.save("welcome", "Hi $first_name", "Hello!\n", "<p>Hello</p>", create=True)
        self.assertEqual(self.store.list(), [{"name": "welcome", "has_html": True}])
        self.assertEqual(self.store.get("welcome"),
                         {"name": "welcome", "subject": "Hi $first_name", "text": "Hello!\n", "html": "<p>Hello</p>"})
        self.assertEqual(self.store.load("welcome").subject, "Hi $first_name")

    def test_clearing_html_removes_file(self):
        self.store.save("welcome", "Hi", "Body", "<p>x</p>", create=True)
        self.store.save("welcome", "Hi", "Body", "   ", create=False)
        self.assertFalse((self.dir / "welcome.html").exists())

    def test_create_does_not_overwrite(self):
        self.store.save("welcome", "Hi", "Body", "", create=True)
        with self.assertRaises(StoreError) as ctx:
            self.store.save("welcome", "Other", "Body", "", create=True)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.store.get("welcome")["subject"], "Hi")

    def test_invalid_template_not_saved(self):
        with self.assertRaises(TemplateError):
            self.store.save("welcome", "Hi", "Hi $frist_name", "", create=True)
        self.assertFalse((self.dir / "welcome.txt").exists())

    def test_names_cannot_escape_folder(self):
        for name in ("../secret", "..", "a/b", "a\\b", ".env", "", "x" * 65, "con.txt"):
            with self.assertRaises(StoreError, msg=name):
                self.store.get(name)

    def test_broken_file_can_still_be_opened(self):
        self.dir.mkdir()
        (self.dir / "broken.txt").write_text("No subject line here", encoding="utf-8")
        self.assertEqual(self.store.get("broken"),
                         {"name": "broken", "subject": "", "text": "No subject line here", "html": ""})
        with self.assertRaises(TemplateError):
            self.store.load("broken")

    def test_missing_template(self):
        with self.assertRaises(StoreError) as ctx:
            self.store.get("nope")
        self.assertEqual(ctx.exception.status, 404)


if __name__ == "__main__":
    unittest.main()
