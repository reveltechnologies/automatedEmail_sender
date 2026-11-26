import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from email_sender.config import KEYS
from email_sender.web.server import App, make_server

from .helpers import FakeSMTP

ENV = (
    "SENDER_EMAIL=team@example.com\n"
    "SENDER_NAME=Example Team\n"
    "SMTP_HOST=smtp.example.com\n"
    "SMTP_USERNAME=team@example.com\n"
    "SMTP_PASSWORD=secret\n"
)
PEOPLE = (
    "email,name,status,tags\n"
    "ana@example.com,Ana Rossi,subscribed,tester\n"
    "bo@example.com,<b>Bo</b>,,tester beta\n"
    "cy@example.com,Cy,,newsletter\n"
    "di@example.com,Di,unsubscribed,tester\n"
)


class ServerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        clean_env = {k: v for k, v in os.environ.items() if k not in KEYS}
        patcher = mock.patch.dict(os.environ, clean_env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

        root = Path(self.tmp.name)
        self.root = root
        (root / ".env").write_text(ENV, encoding="utf-8")
        (root / "data").mkdir()
        (root / "data" / "recipients.csv").write_text(PEOPLE, encoding="utf-8")
        (root / "templates").mkdir()
        (root / "templates" / "welcome.txt").write_text("Subject: Hi $first_name\n\nHello $name\n", encoding="utf-8")

        self.app = App(recipients_path=root / "data" / "recipients.csv", templates_dir=root / "templates",
                       env_file=root / ".env", log_path=root / "state" / "log.csv", delay=0)
        self.smtp = FakeSMTP()
        self.app.connect = self.smtp
        self.server = make_server(self.app, 0)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, *, token=True, host=None, headers=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        all_headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            all_headers["X-Auth-Token"] = self.app.token
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        all_headers.update(headers or {})
        conn.request(method, path, body=data, headers=all_headers)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = payload
        return resp.status, parsed, resp

    def wait_for_job(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            _, job, _ = self.request("GET", "/api/job")
            if job["state"] != "running":
                return job
            time.sleep(0.02)
        self.fail("job did not finish")


class SecurityTests(ServerTestCase):
    def test_api_requires_token(self):
        status, body, _ = self.request("GET", "/api/status", token=False)
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/status", headers={"X-Auth-Token": "wrong"})
        self.assertEqual(status, 401)
        # Rejected requests that carry a body must still get a readable reply.
        status, body, _ = self.request("PUT", "/api/recipients", {"rows": [["x"] * 4] * 500}, token=False)
        self.assertEqual(status, 401)
        self.assertIn("access key", body["error"])

    def test_rejects_foreign_host_and_origin(self):
        self.assertEqual(self.request("GET", "/api/status", host="evil.example.com")[0], 403)
        self.assertEqual(self.request("GET", "/", host=f"evil.example.com:{self.port}")[0], 403)
        self.assertEqual(self.request("GET", "/api/status", headers={"Origin": "https://evil.example.com"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", headers={"Origin": f"http://localhost:{self.port}"})[0], 200)

    def test_post_must_be_json(self):
        status, _, _ = self.request("POST", "/api/preview", raw=b"subject=x",
                                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 415)
        status, _, _ = self.request("POST", "/api/preview", raw=b"{not json", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 400)

    def test_security_headers(self):
        _, _, resp = self.request("GET", "/api/status")
        self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(resp.getheader("Cache-Control"), "no-store")

    def test_template_path_traversal_blocked(self):
        status, body, _ = self.request("GET", "/api/templates/..%2F.env")
        self.assertEqual(status, 400)
        self.assertNotIn("secret", json.dumps(body))

    def test_unknown_route(self):
        self.assertEqual(self.request("GET", "/api/nope")[0], 404)
        self.assertEqual(self.request("GET", "/etc/passwd")[0], 404)


class ApiTests(ServerTestCase):
    def test_status_hides_password(self):
        status, body, _ = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["sender"]["email"], "team@example.com")
        self.assertTrue(body["smtp_ready"])
        self.assertNotIn("secret", json.dumps(body))

    def test_status_reports_missing_smtp(self):
        (self.root / ".env").write_text("SENDER_EMAIL=team@example.com\n", encoding="utf-8")
        body = self.request("GET", "/api/status")[1]
        self.assertFalse(body["smtp_ready"])
        self.assertIn("SMTP_HOST", body["smtp_error"])

    def test_recipients_round_trip_and_row_errors(self):
        _, data, _ = self.request("GET", "/api/recipients")
        self.assertEqual(len(data["rows"]), 4)
        data["rows"].append(["eve@example.com", "Eve", "subscribed", "tester"])
        status, saved, _ = self.request("PUT", "/api/recipients", data)
        self.assertEqual(status, 200)
        self.assertEqual(len(saved["rows"]), 5)

        saved["rows"].append(["broken", "", "", ""])
        status, body, _ = self.request("PUT", "/api/recipients", saved)
        self.assertEqual(status, 400)
        self.assertEqual(body["details"][0]["row"], 5)

        status, _, _ = self.request("PUT", "/api/recipients", data)  # stale version
        self.assertEqual(status, 409)

    def test_tags(self):
        self.assertEqual(self.request("GET", "/api/tags")[1], {"tags": ["beta", "newsletter", "tester"]})

    def test_templates(self):
        self.assertEqual(self.request("GET", "/api/templates")[1], {"templates": [{"name": "welcome", "has_html": False}]})
        status, body, _ = self.request("PUT", "/api/templates/launch",
                                       {"subject": "Launch!", "text": "Hi $first_name", "html": "", "create": True})
        self.assertEqual((status, body["subject"]), (200, "Launch!"))
        status, _, _ = self.request("PUT", "/api/templates/launch",
                                    {"subject": "x", "text": "y", "html": "", "create": True})
        self.assertEqual(status, 409)
        status, body, _ = self.request("PUT", "/api/templates/launch", {"subject": "x", "text": "$oops", "html": ""})
        self.assertEqual(status, 400)
        self.assertIn("$oops", body["error"])

    def test_preview_unsaved_content(self):
        status, body, _ = self.request("POST", "/api/preview", {
            "template": "welcome", "subject": "Hey $first_name", "text": "Unsaved $name",
            "html": "<p>$name</p>", "tags": ["tester"], "preview_email": "bo@example.com",
        })
        self.assertEqual(status, 200)
        self.assertEqual(body["summary"], {"eligible": 2, "already_sent": 0, "to_send": 2})
        self.assertEqual([p["email"] for p in body["pending"]], ["ana@example.com", "bo@example.com"])
        self.assertTrue(any("di@example.com" in s for s in body["skipped"]))
        msg = body["message"]
        self.assertEqual((msg["recipient"], msg["subject"]), ("bo@example.com", "Hey <b>Bo</b>"))
        self.assertTrue(msg["text"].startswith("Unsaved <b>Bo</b>"))
        self.assertIn("&lt;b&gt;Bo&lt;/b&gt;", msg["html"])
        self.assertIn("unsubscribe", msg["text"])

    def test_preview_template_error(self):
        status, body, _ = self.request("POST", "/api/preview", {"subject": "Hi", "text": "Hi $frist_name"})
        self.assertEqual(status, 400)
        self.assertIn("$frist_name", body["error"])

    def test_preview_without_list(self):
        (self.root / "data" / "recipients.csv").unlink()
        status, body, _ = self.request("POST", "/api/preview", {"subject": "Hi", "text": "Hi $first_name"})
        self.assertEqual(status, 200)
        self.assertIn("doesn't exist yet", body["list_error"])
        self.assertEqual(body["summary"]["to_send"], 0)

    def test_send_test(self):
        status, body, _ = self.request("POST", "/api/test", {"template": "welcome", "to": "me@example.com"})
        self.assertEqual(status, 200, body)
        self.assertEqual(len(self.smtp.sent), 1)
        self.assertEqual(self.smtp.sent[0]["To"], "me@example.com")
        self.assertEqual(self.smtp.sent[0]["Subject"], "[TEST] Hi Ana")
        self.assertEqual(self.request("GET", "/api/history")[1], {"campaigns": []})  # tests aren't logged

    def test_send_test_needs_valid_address(self):
        self.assertEqual(self.request("POST", "/api/test", {"template": "welcome", "to": "nope"})[0], 400)


class SendJobTests(ServerTestCase):
    def test_send_whole_group_then_nothing_left(self):
        status, body, _ = self.request("POST", "/api/send", {"template": "welcome", "tags": ["tester"], "expected": 5})
        self.assertEqual(status, 409)  # count doesn't match the preview
        self.assertEqual(self.smtp.sent, [])

        status, job, _ = self.request("POST", "/api/send", {"template": "welcome", "tags": ["tester"], "expected": 2})
        self.assertEqual(status, 200, job)
        job = self.wait_for_job()
        self.assertEqual((job["state"], job["sent"], job["total"]), ("done", 2, 2))
        self.assertEqual(sorted(m["To"].addresses[0].addr_spec for m in self.smtp.sent),
                         ["ana@example.com", "bo@example.com"])

        history = self.request("GET", "/api/history")[1]["campaigns"]
        self.assertEqual([(c["campaign"], c["sent"]) for c in history], [("welcome", 2)])
        status, body, _ = self.request("POST", "/api/send", {"template": "welcome", "tags": ["tester"], "expected": 0})
        self.assertEqual(status, 400)
        self.assertIn("already received", body["error"])

    def test_refused_and_connection_errors_reported(self):
        self.smtp.refuse = {"bo@example.com"}
        self.request("POST", "/api/send", {"template": "welcome", "tags": ["tester"], "expected": 2})
        job = self.wait_for_job()
        self.assertEqual((job["state"], job["sent"]), ("done", 1))
        self.assertEqual(job["failed"][0]["email"], "bo@example.com")

        self.smtp.refuse = set()
        self.smtp.disconnect_after = len(self.smtp.sent)  # next send drops the connection
        self.request("POST", "/api/send", {"template": "welcome", "campaign": "second", "expected": 3})
        job = self.wait_for_job()
        self.assertEqual(job["state"], "error")
        self.assertIn("Press Send again", job["message"])

    def test_stop(self):
        self.app.delay = 0.3
        self.request("POST", "/api/send", {"template": "welcome", "expected": 3})
        self.request("POST", "/api/job/stop", {})
        job = self.wait_for_job()
        self.assertEqual(job["state"], "stopped")
        self.assertLess(job["sent"], 3)

    def test_send_requires_saved_template(self):
        status, body, _ = self.request("POST", "/api/send", {"template": "unsaved", "expected": 3})
        self.assertEqual(status, 404)
        self.assertIn("Save it first", body["error"])


class ImportTests(ServerTestCase):
    FORM = ("Timestamp,Email address,Name\n"
            "2026/11/20 9:15,new@example.com,New Person\n"
            "2026/11/21 9:15,di@example.com,Di\n"
            "2026/11/22 9:15,cy@example.com,Cy\n"
            "2026/11/23 9:15,oops,Oops\n")

    def file_body(self, text, **extra):
        return {"file": base64.b64encode(text.encode("utf-8")).decode(), "tags": "tester", "source": "Form", **extra}

    def test_preview_changes_nothing_and_apply_merges(self):
        before = (self.root / "data" / "recipients.csv").read_bytes()
        status, preview, _ = self.request("POST", "/api/import/preview", self.file_body(self.FORM))
        self.assertEqual(status, 200)
        self.assertTrue(preview["has_header"])
        self.assertEqual(preview["mapping"], {"email": 1, "name": [2], "date": 0, "consent": None})
        self.assertEqual([p["email"] for p in preview["add"]], ["new@example.com"])
        self.assertEqual(preview["blocked"], [{"email": "di@example.com", "status": "unsubscribed"}])
        self.assertEqual(preview["update"], [{"email": "cy@example.com", "row": 2, "tags": ["tester"], "name": ""}])
        self.assertEqual(len(preview["skipped"]), 1)
        self.assertEqual((self.root / "data" / "recipients.csv").read_bytes(), before)

        status, result, _ = self.request("POST", "/api/import/apply",
                                         self.file_body(self.FORM, version=preview["version"]))
        self.assertEqual(status, 200, result)
        self.assertEqual((result["added"], result["updated"]), (1, 1))
        listing = result["list"]
        self.assertEqual(listing["columns"], ["email", "name", "status", "tags", "signed_up", "source"])
        self.assertIn(["new@example.com", "New Person", "subscribed", "tester", "2026/11/20 9:15", "Form"],
                      listing["rows"])
        self.assertIn(["di@example.com", "Di", "unsubscribed", "tester", "", ""], listing["rows"])
        self.assertTrue((self.root / "data" / "recipients.csv.bak").is_file())

    def test_apply_refuses_when_the_list_changed(self):
        _, preview, _ = self.request("POST", "/api/import/preview", {"text": "x@example.com"})
        with (self.root / "data" / "recipients.csv").open("a", encoding="utf-8") as fh:
            fh.write("zed@example.com,Zed,,\n")
        status, body, _ = self.request("POST", "/api/import/apply", {"text": "x@example.com", "version": preview["version"]})
        self.assertEqual(status, 409)
        self.assertIn("changed", body["error"])

    def test_chosen_columns_and_errors(self):
        status, body, _ = self.request("POST", "/api/import/preview",
                                       self.file_body(self.FORM, mapping={"email": 1, "name": [], "date": None}))
        self.assertEqual(status, 200)
        self.assertEqual(body["add"][0]["name"], "")
        status, body, _ = self.request("POST", "/api/import/preview", self.file_body(self.FORM, mapping={"email": 9}))
        self.assertEqual(status, 400)
        status, body, _ = self.request("POST", "/api/import/preview", {"file": "not base64!"})
        self.assertEqual(status, 400)
        status, body, _ = self.request("POST", "/api/import/preview", {"text": "  "})
        self.assertEqual(status, 400)
        status, body, _ = self.request("POST", "/api/import/apply", {"text": "ana@example.com", "version": "x"})
        self.assertEqual(status, 400)  # nothing to do is reported before the version check
        self.assertIn("nobody new", body["error"])

    def test_import_into_a_new_list(self):
        (self.root / "data" / "recipients.csv").unlink()
        _, preview, _ = self.request("POST", "/api/import/preview", {"text": "ana@example.com"})
        status, result, _ = self.request("POST", "/api/import/apply", {"text": "ana@example.com", "version": preview["version"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["list"]["rows"][0][:3], ["ana@example.com", "", "subscribed"])


class CliEntryTests(unittest.TestCase):
    def test_ui_subcommand_dispatches(self):
        from email_sender import cli

        with mock.patch("email_sender.web.server.main", return_value=0) as ui_main:
            self.assertEqual(cli.main(["ui", "--port", "9999"]), 0)
        ui_main.assert_called_once_with(["--port", "9999"])


if __name__ == "__main__":
    unittest.main()
