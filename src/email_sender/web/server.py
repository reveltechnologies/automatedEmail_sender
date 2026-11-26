"""Local web interface: ``email-sender ui``.

The server listens on 127.0.0.1 only. Every API call must carry a random
token generated at start-up and handed to the browser in the URL fragment,
so other websites open in the same browser cannot read or send anything.
"""

from __future__ import annotations

import argparse
import json
import secrets
import smtplib
import sys
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .. import __version__
from ..campaign import Plan, build_messages, build_test_message, plan_campaign, sample_recipient
from ..config import ConfigError, load_settings
from ..recipients import RecipientError, is_valid_email
from ..sender import SendLog, build_message, open_smtp, send_all, send_test
from ..templates import TemplateError, compose_template_text, parse_template, render
from .store import RecipientTable, StoreError, TemplateStore

STATIC_DIR = Path(__file__).parent / "static"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}
MAX_BODY_BYTES = 5 * 1024 * 1024
AUTH_HINT = ("The email server rejected the login. Check SMTP_USERNAME and SMTP_PASSWORD in .env "
             "(Gmail and Outlook need an app password, not your normal password).")
SECURITY_HEADERS = {
    # Inline styles and https images are allowed only so email HTML previews look right;
    # scripts are limited to our own app.js and the preview iframe is fully sandboxed.
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; connect-src 'self'; frame-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


class Job:
    """One send run. Request threads read it while the worker thread updates it."""

    def __init__(self, campaign: str = "", total: int = 0):
        self.lock = threading.Lock()
        self.state = "running" if total else "idle"  # idle | running | done | stopped | error
        self.campaign = campaign
        self.total = total
        self.sent = 0
        self.failed: list[dict] = []
        self.lines: list[str] = []
        self.message = ""
        self.stop_requested = False
        self.thread: threading.Thread | None = None

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "state": self.state, "campaign": self.campaign, "total": self.total, "sent": self.sent,
                "failed": list(self.failed), "lines": self.lines[-200:], "message": self.message,
            }

    def add_line(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)

    def on_result(self, recipient, result: str, detail: str) -> None:
        with self.lock:
            if result == "sent":
                self.sent += 1
            else:
                self.failed.append({"email": recipient.email, "detail": detail})

    def finish(self, state: str, message: str) -> None:
        with self.lock:
            self.state, self.message = state, message


class App:
    def __init__(self, *, recipients_path: Path, templates_dir: Path, env_file: Path, log_path: Path,
                 delay: float = 1.0):
        self.recipients_path = recipients_path
        self.table = RecipientTable(recipients_path)
        self.templates = TemplateStore(templates_dir)
        self.env_file = env_file
        self.log = SendLog(log_path)
        self.delay = delay
        self.token = secrets.token_urlsafe(32)
        self.job = Job()
        self.job_start_lock = threading.Lock()
        self.connect = open_smtp  # tests swap this for a fake server

    # ---- input helpers -------------------------------------------------
    @staticmethod
    def _text(body: dict, key: str) -> str:
        value = body.get(key, "")
        if value is None:
            return ""
        if not isinstance(value, str):
            raise StoreError(f"'{key}' must be text")
        return value

    @staticmethod
    def _tags(body: dict) -> set[str]:
        tags = body.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise StoreError("'tags' must be a list of text")
        return {t.strip().lower() for t in tags if t.strip()}

    def _campaign(self, body: dict, fallback: str) -> str:
        campaign = " ".join(self._text(body, "campaign").split()) or fallback
        if len(campaign) > 100:
            raise StoreError("The campaign name is too long (max 100 characters).")
        return campaign

    def _plan(self, body: dict, template_name: str) -> Plan:
        if not self.recipients_path.is_file():
            raise StoreError("The recipient list doesn't exist yet. Add people on the Recipients tab.")
        return plan_campaign(self.recipients_path, self._tags(body), self._campaign(body, template_name), self.log)

    # ---- endpoints -----------------------------------------------------
    def status(self) -> dict:
        sender, config_error, smtp_error = None, None, None
        try:
            settings = load_settings(self.env_file, require_smtp=False)
            sender = {"email": settings.sender_email, "name": settings.sender_name,
                      "reply_to": settings.reply_to, "unsubscribe_email": settings.unsubscribe_email}
        except ConfigError as exc:
            config_error = str(exc)
        try:
            load_settings(self.env_file, require_smtp=True)
        except ConfigError as exc:
            smtp_error = str(exc)
        return {
            "version": __version__, "sender": sender, "config_error": config_error,
            "smtp_ready": smtp_error is None, "smtp_error": smtp_error,
            "paths": {"recipients": str(self.recipients_path), "templates": str(self.templates.directory),
                      "env": str(self.env_file), "log": str(self.log.path)},
        }

    def tags(self) -> dict:
        data = self.table.load()
        index = data["columns"].index("tags")
        found: set[str] = set()
        for row in data["rows"]:
            for sep in "|,;":
                row[index] = row[index].replace(sep, " ")
            found.update(row[index].lower().split())
        return {"tags": sorted(found)}

    def preview(self, body: dict) -> dict:
        """Render the editor's current (possibly unsaved) content for one recipient."""
        name = self._text(body, "template") or "untitled"
        html_body = self._text(body, "html")
        template = parse_template(
            compose_template_text(self._text(body, "subject"), self._text(body, "text")),
            html_body if html_body.strip() else None, "Message", "HTML version",
        )
        settings = load_settings(self.env_file, require_smtp=False)
        plan, list_error = None, None
        try:
            plan = self._plan(body, name)
        except (StoreError, RecipientError) as exc:
            list_error = str(exc)

        wanted = self._text(body, "preview_email").strip().lower()
        candidates = (plan.pending + plan.eligible) if plan else []
        recipient = next((r for r in candidates if r.email == wanted), None) \
            or sample_recipient(plan, "someone@example.com")
        msg = build_message(settings, recipient, render(template, recipient))
        html_part = msg.get_body(("html",))
        return {
            "campaign": plan.campaign if plan else self._campaign(body, name),
            "list_error": list_error,
            "summary": {"eligible": len(plan.eligible) if plan else 0,
                        "already_sent": plan.already_sent if plan else 0,
                        "to_send": len(plan.pending) if plan else 0},
            "skipped": plan.skipped if plan else [],
            "pending": [{"email": r.email, "name": r.name} for r in (plan.pending if plan else [])],
            "message": {
                "recipient": recipient.email, "from": str(msg["From"]), "to": str(msg["To"]),
                "subject": str(msg["Subject"]), "text": msg.get_body(("plain",)).get_content(),
                "html": html_part.get_content() if html_part is not None else None,
            },
        }

    def send_test(self, body: dict) -> dict:
        to = self._text(body, "to").strip()
        if not is_valid_email(to.lower()):
            raise StoreError("Enter a valid address to send the test to.")
        name = self._text(body, "template")
        template = self.templates.load(name)
        settings = load_settings(self.env_file, require_smtp=True)
        try:
            plan = self._plan(body, name)
        except (StoreError, RecipientError):
            plan = None
        sample = sample_recipient(plan, to)
        send_test(settings, build_test_message(settings, template, sample, to), connect=self.connect)
        return {"message": f"Test sent to {to} (written as if for {sample.email}). Check your inbox and spam folder."}

    def start_send(self, body: dict) -> dict:
        name = self._text(body, "template")
        expected = body.get("expected")
        with self.job_start_lock:
            if self.job.state == "running":
                raise StoreError("A send is already running.", status=409)
            template = self.templates.load(name)
            settings = load_settings(self.env_file, require_smtp=True)
            plan = self._plan(body, name)
            if not plan.pending:
                raise StoreError("Everyone in this group has already received this campaign.")
            if expected != len(plan.pending):
                raise StoreError("The list changed since the preview. Check the preview and try again.", status=409)
            messages = build_messages(settings, template, plan.pending)

            job = Job(plan.campaign, len(messages))
            self.job = job

            def worker() -> None:
                try:
                    report = send_all(settings, messages, campaign=plan.campaign, log=self.log, delay=self.delay,
                                      connect=self.connect, progress=job.add_line, on_result=job.on_result,
                                      should_stop=lambda: job.stop_requested)
                    if report.stopped:
                        job.finish("stopped", f"Stopped after {report.sent} sent. Press Send again to continue.")
                    else:
                        refused = f", {len(report.failed)} refused" if report.failed else ""
                        job.finish("done", f"Finished: {report.sent} sent{refused}.")
                except smtplib.SMTPAuthenticationError:
                    job.finish("error", AUTH_HINT)
                except (smtplib.SMTPException, OSError) as exc:
                    job.finish("error", f"Sending stopped: {exc}. Press Send again to continue with "
                                        "the people not yet emailed.")
                except Exception as exc:  # never leave the job stuck in "running"
                    traceback.print_exc()
                    job.finish("error", f"Unexpected error: {exc}")

            job.thread = threading.Thread(target=worker, name="email-sender-job", daemon=True)
            job.thread.start()
        return job.snapshot()

    def stop_send(self) -> dict:
        self.job.stop_requested = True
        return self.job.snapshot()


class Handler(BaseHTTPRequestHandler):
    server_version = "email-sender"
    app: App  # set on the bound subclass in make_server

    def log_message(self, format, *args):  # keep the terminal quiet
        pass

    # ---- plumbing ------------------------------------------------------
    def _allowed_hosts(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str, details: list | None = None) -> None:
        payload: dict = {"error": message}
        if details:
            payload["details"] = details
        self._json(status, payload)

    def _read_body(self) -> bytes | None:
        """Read the whole request body before replying.

        Replying with unread data still in the socket makes Windows reset the
        connection, and the browser then never sees the error message.
        Returns None if the body is too large or its length is invalid.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            return None
        return self.rfile.read(length) if length else b""

    def _parse_json(self, raw: bytes | None) -> dict:
        if raw is None:
            raise StoreError("Request too large", status=413)
        if self.headers.get_content_type() != "application/json":
            raise StoreError("Expected JSON", status=415)
        try:
            body = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise StoreError("Invalid JSON") from None
        if not isinstance(body, dict):
            raise StoreError("Expected a JSON object")
        return body

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def _handle(self, method: str) -> None:
        raw = self._read_body() if method in ("POST", "PUT") else b""
        # Rejecting unknown Host headers blocks DNS-rebinding attacks.
        if self.headers.get("Host", "") not in self._allowed_hosts():
            return self._error(HTTPStatus.FORBIDDEN, "Unexpected host")
        path = urlsplit(self.path).path
        if method == "GET" and path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            file = STATIC_DIR / filename
            if not file.is_file():
                return self._error(HTTPStatus.NOT_FOUND, f"{filename} is missing from the installation")
            return self._send(HTTPStatus.OK, file.read_bytes(), content_type)
        if not path.startswith("/api/"):
            return self._error(HTTPStatus.NOT_FOUND, "Not found")

        origin = self.headers.get("Origin")
        if origin is not None and origin not in {f"http://{h}" for h in self._allowed_hosts()}:
            return self._error(HTTPStatus.FORBIDDEN, "Cross-origin requests are not allowed")
        if not secrets.compare_digest(self.headers.get("X-Auth-Token", "").encode(), self.app.token.encode()):
            return self._error(HTTPStatus.UNAUTHORIZED,
                               "Missing or wrong access key. Open the page using the link shown in the terminal.")
        try:
            body = self._parse_json(raw) if method in ("POST", "PUT") else {}
            result = self._route(method, path, body)
            if result is None:
                return self._error(HTTPStatus.NOT_FOUND, "Not found")
            self._json(HTTPStatus.OK, result)
        except StoreError as exc:
            self._error(exc.status, str(exc), exc.details)
        except (ConfigError, RecipientError, TemplateError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except smtplib.SMTPAuthenticationError:
            self._error(HTTPStatus.BAD_GATEWAY, AUTH_HINT)
        except (smtplib.SMTPException, OSError) as exc:
            self._error(HTTPStatus.BAD_GATEWAY, f"Couldn't send: {exc}")
        except Exception as exc:
            traceback.print_exc()
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"Unexpected error: {exc}")

    def _route(self, method: str, path: str, body: dict) -> dict | None:
        app = self.app
        if path.startswith("/api/templates/"):
            name = unquote(path[len("/api/templates/"):])
            if method == "GET":
                return app.templates.get(name)
            if method == "PUT":
                return app.templates.save(name, body.get("subject"), body.get("text"), body.get("html", ""),
                                          create=bool(body.get("create")))
            return None
        routes = {
            ("GET", "/api/status"): app.status,
            ("GET", "/api/recipients"): app.table.load,
            ("PUT", "/api/recipients"): lambda: app.table.save(body.get("columns"), body.get("rows"),
                                                               body.get("version")),
            ("GET", "/api/tags"): app.tags,
            ("GET", "/api/templates"): lambda: {"templates": app.templates.list()},
            ("POST", "/api/preview"): lambda: app.preview(body),
            ("POST", "/api/test"): lambda: app.send_test(body),
            ("POST", "/api/send"): lambda: app.start_send(body),
            ("GET", "/api/job"): lambda: app.job.snapshot(),
            ("POST", "/api/job/stop"): app.stop_send,
            ("GET", "/api/history"): lambda: {"campaigns": app.log.summary()},
        }
        handler = routes.get((method, path))
        return handler() if handler else None


class LocalServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR would let two programs share the port; don't.
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True


def make_server(app: App, port: int) -> LocalServer:
    handler = type("BoundHandler", (Handler,), {"app": app})
    return LocalServer(("127.0.0.1", port), handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="email-sender ui",
                                     description="Open the email sender in your browser (runs only on this computer).")
    parser.add_argument("--recipients", type=Path, default=Path("data/recipients.csv"),
                        help="recipient list to edit and send to (default: data/recipients.csv)")
    parser.add_argument("--templates", type=Path, default=Path("templates"), help="templates folder (default: templates)")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="settings file (default: .env)")
    parser.add_argument("--log", type=Path, default=Path("state/sent_log.csv"), help="delivery log")
    parser.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: 8765)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between emails (default: 1)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    args = parser.parse_args(argv)

    app = App(recipients_path=args.recipients, templates_dir=args.templates, env_file=args.env_file,
              log_path=args.log, delay=max(args.delay, 0.0))
    try:
        httpd = make_server(app, args.port)
    except OSError:
        httpd = make_server(app, 0)  # port busy: let the OS pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/#token={app.token}"
    print("Email sender is running. Open this link if the browser doesn't open by itself:")
    print(f"  {url}")
    print("Keep this window open while you use it. Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if app.job.state == "running":
            print("\nStopping the send in progress...")
            app.job.stop_requested = True
            if app.job.thread is not None:
                app.job.thread.join(timeout=10)
        httpd.server_close()
        print("Stopped.")
    return 0
