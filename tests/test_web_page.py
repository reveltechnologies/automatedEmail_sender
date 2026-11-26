import re
import unittest
from pathlib import Path

from .test_web_server import ServerTestCase

STATIC = Path(__file__).resolve().parent.parent / "src" / "email_sender" / "web" / "static"


class PageServingTests(ServerTestCase):
    def test_page_and_assets_served_without_token(self):
        for path, kind in (("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css")):
            status, _, resp = self.request("GET", path, token=False)
            self.assertEqual(status, 200, path)
            self.assertTrue(resp.getheader("Content-Type").startswith(kind), path)
            self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))

    def test_page_holds_no_data(self):
        # The page itself is public to anything that can reach the port; all data needs the token.
        _, body, _ = self.request("GET", "/", token=False)
        html = body.decode("utf-8")
        for secret in ("ana@example.com", "team@example.com", self.app.token):
            self.assertNotIn(secret, html)


class PageConsistencyTests(unittest.TestCase):
    """Cheap checks that catch typos between index.html and app.js."""

    def setUp(self):
        self.html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.js = (STATIC / "app.js").read_text(encoding="utf-8")

    def test_every_element_id_used_by_script_exists(self):
        ids = set(re.findall(r'\bid="([\w-]+)"', self.html))
        used = set(re.findall(r'\$\("([\w-]+)"\)', self.js))
        for tab in ("recipients", "compose", "history"):  # built as $(`tab-${tab}`) / $(`panel-${tab}`)
            used |= {f"tab-{tab}", f"panel-{tab}"}
        self.assertTrue(used)
        self.assertEqual(sorted(used - ids), [])

    def test_no_inline_script_or_external_resources(self):
        self.assertNotRegex(self.html, r"<script(?![^>]*\bsrc=)")
        self.assertNotRegex(self.html, r"\son\w+=")  # inline event handlers would be blocked by the CSP
        self.assertNotRegex(self.html + self.js, r"https?://")

    def test_script_never_uses_innerhtml(self):
        for pattern in (r"\.(inner|outer)HTML\b", r"\.insertAdjacentHTML\(", r"document\.write", r"\beval\("):
            self.assertNotRegex(self.js, pattern)


if __name__ == "__main__":
    unittest.main()
