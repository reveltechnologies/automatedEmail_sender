import tempfile
import unittest
from pathlib import Path

from email_sender.recipients import Recipient
from email_sender.templates import (
    TemplateError,
    compose_template_text,
    load_template,
    parse_template,
    render,
    split_template_text,
)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, text):
        path = Path(self.tmp.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_load_and_render(self):
        path = self.write("t.txt", "Subject: Hi $first_name\n\nHello $name ($email).\nIt costs $$5.\n")
        rendered = render(load_template(path), Recipient("ana@example.com", "Ana Rossi"))
        self.assertEqual(rendered.subject, "Hi Ana")
        self.assertEqual(rendered.text, "Hello Ana Rossi (ana@example.com).\nIt costs $5.\n")
        self.assertIsNone(rendered.html)

    def test_name_fallback(self):
        path = self.write("t.txt", "Subject: Hello\n\nHi $first_name\n")
        self.assertEqual(render(load_template(path), Recipient("x@example.com")).text, "Hi there\n")

    def test_windows_line_endings(self):
        path = Path(self.tmp.name) / "t.txt"
        path.write_bytes(b"Subject: Hi\r\n\r\nBody\r\n")
        self.assertEqual(load_template(path).text, "Body\n")

    def test_missing_subject(self):
        with self.assertRaises(TemplateError):
            load_template(self.write("t.txt", "Hello there\n\nBody\n"))

    def test_unknown_placeholder(self):
        with self.assertRaisesRegex(TemplateError, r"\$frist_name"):
            load_template(self.write("t.txt", "Subject: Hi\n\nHi $frist_name\n"))

    def test_stray_dollar(self):
        with self.assertRaisesRegex(TemplateError, r"\$\$"):
            load_template(self.write("t.txt", "Subject: Hi\n\nOnly $5 today\n"))

    def test_compose_split_parse_round_trip(self):
        raw = compose_template_text("  Hi $first_name ", "\r\nLine one\r\nLine two\r\n\r\n")
        self.assertEqual(raw, "Subject: Hi $first_name\n\nLine one\nLine two\n")
        self.assertEqual(split_template_text(raw), ("Hi $first_name", "Line one\nLine two\n"))
        self.assertIsNone(split_template_text("no subject here"))
        tmpl = parse_template(raw, "<p>$name</p>", "editor")
        self.assertEqual((tmpl.subject, tmpl.html), ("Hi $first_name", "<p>$name</p>"))

    def test_parse_errors_use_label(self):
        with self.assertRaisesRegex(TemplateError, "^Message"):
            parse_template(compose_template_text("", "Body"), label="Message")
        with self.assertRaisesRegex(TemplateError, "^HTML version"):
            parse_template(compose_template_text("Hi", "Body"), "<p>$bad</p>", "Message", "HTML version")

    def test_html_values_are_escaped(self):
        text = self.write("t.txt", "Subject: Hi\n\nHi $name\n")
        html = self.write("t.html", "<p>Hi $name</p>")
        rendered = render(load_template(text, html), Recipient("x@example.com", "<script>alert(1)</script>"))
        self.assertEqual(rendered.html, "<p>Hi &lt;script&gt;alert(1)&lt;/script&gt;</p>")
        self.assertIn("<script>", rendered.text)  # plain text is not markup


if __name__ == "__main__":
    unittest.main()
