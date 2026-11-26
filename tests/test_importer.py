import io
import unittest
import zipfile
from datetime import date

from email_sender.importer import (ImportFileError, Mapping, apply_import, decode_upload, guess_mapping, parse_tags,
                                   plan_import, read_table, split_address)

COLUMNS = ["email", "name", "status", "tags"]
TODAY = date(2026, 11, 26)

GOOGLE_FORM = (
    '"Timestamp","Email address","Your name","How did you hear about us?","I agree to receive emails about the beta"\n'
    '"2026/11/20 9:15:02 AM GMT+1","ana@example.com","Ana Rossi","Friend","Yes"\n'
    '"2026/11/21 1:02:44 PM GMT+1","BEN@Example.com","Ben Lee","Twitter",""\n'
    '"2026/11/22 8:00:00 PM GMT+1","not-an-address","Cy","",Yes\n'
    '"2026/11/23 7:30:10 AM GMT+1","dana@example.com","Dana","Ad","Yes"\n'
)


def plan(text, rows=(), tags=("tester",), mapping=None):
    table = read_table(text)
    if mapping is None and table.header is not None:
        mapping = guess_mapping(table)
    return plan_import(table, mapping, COLUMNS, [list(r) for r in rows], tags=list(tags), today=TODAY)


class ReadingTests(unittest.TestCase):
    def test_google_form_columns_are_recognised(self):
        table = read_table(GOOGLE_FORM)
        self.assertEqual(guess_mapping(table), Mapping(email=1, name=[2], date=0, consent=4))

    def test_first_and_last_name_columns_are_combined(self):
        table = read_table("First Name;Last Name;E-mail\nAna;Rossi;ana@example.com\n")
        self.assertEqual(guess_mapping(table), Mapping(email=2, name=[0, 1], date=None, consent=None))
        result = plan_import(table, guess_mapping(table), COLUMNS, [], tags=[], today=TODAY)
        self.assertEqual(result.add, [{"email": "ana@example.com", "name": "Ana Rossi", "signed_up": "2026-11-26"}])

    def test_email_column_found_by_its_values_when_the_header_is_unusual(self):
        table = read_table("Who,Contact\nAna,ana@example.com\n")
        self.assertEqual(guess_mapping(table).email, 1)

    def test_company_name_is_not_taken_as_the_persons_name(self):
        table = read_table("email,company name\nana@example.com,Acme\n")
        self.assertEqual(guess_mapping(table).name, [])

    def test_plain_pasted_list_without_header(self):
        result = plan("ana@example.com\nBen Lee <ben@example.com>\ncy@example.com, Cy Young\n"
                      "dee@example.com; eve@example.com\nhello there\n")
        self.assertEqual([(p["email"], p["name"]) for p in result.add], [
            ("ana@example.com", ""), ("ben@example.com", "Ben Lee"), ("cy@example.com", "Cy Young"),
            ("dee@example.com", ""), ("eve@example.com", ""),
        ])
        self.assertEqual(result.skipped, [{"row": 5, "reason": "no email address in “hello there”"}])

    def test_first_line_with_several_addresses_is_not_a_header(self):
        result = plan("ana@example.com; bo@example.com\n")
        self.assertEqual([p["email"] for p in result.add], ["ana@example.com", "bo@example.com"])

    def test_split_address(self):
        self.assertEqual(split_address('"Ana R" <Ana@Example.com>'), ("Ana R", "ana@example.com"))
        self.assertEqual(split_address("mailto:ana@example.com"), ("", "ana@example.com"))
        self.assertEqual(split_address("ana@"), ("", ""))

    def test_line_breaks_in_cells_are_removed(self):
        result = plan('email,name\nana@example.com,"Ana\r\nBcc: x@example.com"\n')
        self.assertEqual(result.add[0]["name"], "Ana Bcc: x@example.com")

    def test_empty_and_header_only_files_are_refused(self):
        with self.assertRaises(ImportFileError):
            read_table("\n\n")
        with self.assertRaises(ImportFileError):
            read_table("email,name\n")

    def test_tags(self):
        self.assertEqual(parse_tags("Tester, beta|tester  new"), ["tester", "beta", "new"])
        self.assertEqual(parse_tags(["a b", "B"]), ["a", "b"])


class DecodeTests(unittest.TestCase):
    def test_utf8_with_bom_and_windows_encoding(self):
        self.assertEqual(decode_upload("email\n".encode("utf-8-sig")), "email\n")
        self.assertEqual(decode_upload("name\nJosé\n".encode("cp1252")), "name\nJosé\n")

    def test_google_forms_zip_is_unpacked(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Beta sign-up.csv", GOOGLE_FORM.encode("utf-8"))
        self.assertEqual(decode_upload(buffer.getvalue()), GOOGLE_FORM)

    def test_excel_workbook_gets_a_helpful_message(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("xl/workbook.xml", "<workbook/>")
        with self.assertRaisesRegex(ImportFileError, "Save As"):
            decode_upload(buffer.getvalue())

    def test_too_big(self):
        with self.assertRaises(ImportFileError):
            decode_upload(b"x" * (3 * 1024 * 1024 + 1))


class MergeTests(unittest.TestCase):
    def test_google_form_import(self):
        result = plan(GOOGLE_FORM)
        self.assertEqual(result.add, [
            {"email": "ana@example.com", "name": "Ana Rossi", "signed_up": "2026/11/20 9:15:02 AM GMT+1"},
            {"email": "dana@example.com", "name": "Dana", "signed_up": "2026/11/23 7:30:10 AM GMT+1"},
        ])
        reasons = [s["reason"] for s in result.skipped]
        self.assertIn("didn't agree", reasons[0])        # Ben left the consent box empty
        self.assertIn("isn't a valid email", reasons[1])

    def test_unsubscribed_people_are_never_added_back(self):
        rows = [["dana@example.com", "Dana", "subscribed", ""], ["DANA@example.com", "", "unsubscribed", ""]]
        result = plan("dana@example.com\nbo@example.com\n", rows)
        self.assertEqual(result.blocked, [{"email": "dana@example.com", "status": "unsubscribed"}])
        self.assertEqual([p["email"] for p in result.add], ["bo@example.com"])
        columns, new_rows = apply_import(result, COLUMNS, rows, tags=["tester"], source="form")
        self.assertEqual([r[2] for r in new_rows[:2]], ["subscribed", "unsubscribed"])  # untouched

    def test_existing_people_get_new_tags_and_a_missing_name_but_keep_their_status(self):
        rows = [["ana@example.com", "", "pending", "beta"]]
        result = plan("Ana <ana@example.com>\n", rows, tags=["tester", "beta"])
        self.assertEqual(result.blocked, [{"email": "ana@example.com", "status": "pending"}])

        rows = [["ana@example.com", "", "subscribed", "beta"], ["bo@example.com", "Bo", "", "tester|beta"]]
        result = plan("Ana <ana@example.com>\nbo@example.com\n", rows, tags=["tester", "beta"])
        self.assertEqual(result.update, [{"email": "ana@example.com", "row": 0, "tags": ["tester"], "name": "Ana"}])
        self.assertEqual(result.unchanged, ["bo@example.com"])
        self.assertEqual(result.add, [])
        columns, new_rows = apply_import(result, COLUMNS, rows, tags=["tester", "beta"], source="")
        self.assertEqual(new_rows[0], ["ana@example.com", "Ana", "subscribed", "beta tester"])
        self.assertEqual(columns, COLUMNS)  # nobody new, so no new columns

    def test_duplicates_in_the_file_use_the_first(self):
        result = plan("ana@example.com\nAna@Example.com\n")
        self.assertEqual(len(result.add), 1)
        self.assertIn("more than once", result.skipped[0]["reason"])

    def test_new_people_get_status_tags_date_and_source(self):
        rows = [["ana@example.com", "Ana", "subscribed", "beta", "x"]]
        columns = COLUMNS + ["Signed_Up"]
        result = plan_import(read_table("bo@example.com\n"), None, columns, rows, tags=["tester", "beta"], today=TODAY)
        new_columns, new_rows = apply_import(result, columns, rows, tags=["tester", "beta"], source="Beta form")
        self.assertEqual(new_columns, columns + ["source"])  # existing sign-up column reused
        self.assertEqual(new_rows[0], ["ana@example.com", "Ana", "subscribed", "beta", "x", ""])
        self.assertEqual(new_rows[1], ["bo@example.com", "", "subscribed", "tester beta", "2026-11-26", "Beta form"])
        self.assertEqual(rows[0], ["ana@example.com", "Ana", "subscribed", "beta", "x"])  # input not modified

    def test_chosen_mapping_is_validated(self):
        with self.assertRaises(ImportFileError):
            Mapping.from_dict({"email": 7}, width=3)
        with self.assertRaises(ImportFileError):
            Mapping.from_dict({"email": True}, width=3)
        with self.assertRaises(ImportFileError):
            Mapping.from_dict({"name": [0]}, width=3)
        self.assertEqual(Mapping.from_dict({"email": 1, "name": [0, 2]}, width=3), Mapping(1, [0, 2]))


if __name__ == "__main__":
    unittest.main()
