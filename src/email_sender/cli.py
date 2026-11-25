"""Command-line interface.

Without ``--send`` nothing is delivered: the command prints a preview of
the first message and the list of people who would receive it.
"""

from __future__ import annotations

import argparse
import smtplib
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, Settings, load_settings
from .recipients import Recipient, RecipientError, is_valid_email, load_recipients
from .sender import SendLog, build_message, open_smtp, send_all, send_test
from .templates import TemplateError, load_template, render

PREVIEW_LIST_LIMIT = 20


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="email-sender",
        description="Send a personalised email to each subscriber in a CSV list, one message per person.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-t", "--template", required=True, type=Path,
                        help="plain-text template: a 'Subject: ...' line, a blank line, then the body")
    parser.add_argument("--html", type=Path, help="optional HTML version of the body")
    parser.add_argument("-r", "--recipients", required=True, type=Path, help="CSV file with an 'email' column")
    parser.add_argument("--tag", action="append", default=[],
                        help="only include recipients with this tag (repeat for several)")
    parser.add_argument("--campaign",
                        help="name used to remember who already got this email (default: template file name)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="actually send (otherwise only a preview is shown)")
    mode.add_argument("--test-to", metavar="ADDRESS",
                      help="send one test copy, rendered for the first recipient, to this address only")
    parser.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation with --send")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds to wait between emails (default: 1)")
    parser.add_argument("--limit", type=int, help="send to at most this many people in this run")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="settings file (default: .env)")
    parser.add_argument("--log", type=Path, default=Path("state/sent_log.csv"),
                        help="delivery log used to skip people already emailed (default: state/sent_log.csv)")
    return parser


def _print_preview(settings: Settings, recipients: list[Recipient], first_message) -> None:
    body = first_message.get_body(("plain",)).get_content()
    print("\n--- Preview (first recipient) " + "-" * 30)
    for header in ("From", "To", "Reply-To", "Subject"):
        if first_message[header]:
            print(f"{header}: {first_message[header]}")
    if first_message.get_body(("html",)) is not None:
        print("(an HTML version is included too)")
    print()
    print(body)
    print("-" * 60)
    print("Recipients:")
    for recipient in recipients[:PREVIEW_LIST_LIMIT]:
        print(f"  {recipient.email}" + (f"  ({recipient.name})" if recipient.name else ""))
    if len(recipients) > PREVIEW_LIST_LIMIT:
        print(f"  ... and {len(recipients) - PREVIEW_LIST_LIMIT} more")


def _confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() == "yes"
    except EOFError:
        return False


def run(args: argparse.Namespace) -> int:
    if args.delay < 0:
        raise ConfigError("--delay cannot be negative")
    if args.limit is not None and args.limit < 1:
        raise ConfigError("--limit must be at least 1")
    if args.test_to and not is_valid_email(args.test_to):
        raise ConfigError(f"--test-to is not a valid email address: {args.test_to!r}")

    settings = load_settings(args.env_file, require_smtp=bool(args.send or args.test_to))
    template = load_template(args.template, args.html)
    loaded = load_recipients(args.recipients, set(args.tag) or None)
    for reason in loaded.skipped:
        print(f"skipped {reason}")

    campaign = args.campaign or args.template.stem
    log = SendLog(args.log)
    already = log.sent_to(campaign)
    pending = [r for r in loaded.recipients if r.email not in already]
    if args.limit is not None:
        pending = pending[: args.limit]

    if args.test_to:
        sample = (pending or loaded.recipients or [Recipient(email=args.test_to)])[0]
        rendered = render(template, sample)
        msg = build_message(settings, sample, rendered)
        msg.replace_header("To", args.test_to)
        msg.replace_header("Subject", f"[TEST] {rendered.subject}")
        send_test(settings, msg, connect=open_smtp)
        print(f"Test email (rendered for {sample.email}) sent to {args.test_to}. Nothing was logged.")
        return 0

    # Render every message up front so a template problem stops the run before the first send.
    messages = [(r, build_message(settings, r, render(template, r))) for r in pending]
    done = len(already & {r.email for r in loaded.recipients})
    print(f"Campaign '{campaign}': {len(loaded.recipients)} eligible, {done} already sent, "
          f"{len(messages)} to send in this run.")
    if not messages:
        print("Nothing to send.")
        return 0

    if not args.send:
        _print_preview(settings, pending, messages[0][1])
        print("\nPreview only - nothing was sent. Add --send to deliver, or --test-to YOUR@ADDRESS to try it first.")
        return 0

    if not args.yes and not _confirm(
        f"Send {len(messages)} email(s) from {settings.sender_email}? Type 'yes' to continue: "
    ):
        print("Cancelled - nothing was sent.")
        return 1

    report = send_all(settings, messages, campaign=campaign, log=log, delay=args.delay, connect=open_smtp)
    print(f"Done: {report.sent} sent, {len(report.failed)} refused.")
    if report.failed:
        print(f"Refused addresses are in {args.log}; re-running the same command will retry them.")
    return 1 if report.failed else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except smtplib.SMTPAuthenticationError:
        print("error: the SMTP server rejected the login. Check SMTP_USERNAME and SMTP_PASSWORD "
              "(Gmail and Outlook need an app password, not your normal password).", file=sys.stderr)
    except (ConfigError, RecipientError, TemplateError) as exc:
        print(f"error: {exc}", file=sys.stderr)
    except (smtplib.SMTPException, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if args.send:
            print("Sending stopped. Re-run the same command to continue with the people not yet emailed.",
                  file=sys.stderr)
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run the same command to continue where it stopped.", file=sys.stderr)
        return 130
    return 1
