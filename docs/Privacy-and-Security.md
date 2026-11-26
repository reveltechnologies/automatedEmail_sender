# Privacy and Security

This tool handles people's personal data (names and email addresses) and an email account password. These rules apply to everyone working on or running it.

## Never commit

| File | Why | Protected by |
| --- | --- | --- |
| `.env` | SMTP password | `.gitignore` |
| `data/*.csv` (except the example) | Subscriber names and addresses | `.gitignore` |
| `state/` | Delivery log containing addresses | `.gitignore` |

If one of these is ever committed or pushed, **change the SMTP password straight away** and remove the file from git history. Deleting the file in a new commit is not enough.

Use only made-up `@example.com` addresses in tests, examples, issues and pull requests. Don't paste real subscriber data or `sent_log.csv` contents into an issue.

## Built-in protections

- **One message per recipient.** Addresses are never grouped in To, Cc or Bcc, so no subscriber sees another subscriber's address.
- **Encrypted SMTP only** (STARTTLS or SSL, with certificate verification). The tool refuses to connect without encryption.
- **Header-injection safe.** Line breaks are removed from CSV values, addresses are validated, and Python's email library rejects headers containing line breaks.
- **HTML-escaped placeholders.** A name like `<script>` is shown as text, not run as markup.
- **The password is hidden from logs.** It is never printed and is left out of any debug output of the settings.
- **Preview by default.** On the command line, sending needs `--send` and a typed `yes`. On the page, it needs a confirmation click.

## The web page (`email-sender ui`)

- It listens only on `127.0.0.1`, so other computers on your network can't reach it.
- Every data request needs a random access key that is created each time the page is started. The key is in the link the terminal prints. It sits after the `#`, so browsers never send it to any server or save it in logs.
- Requests from other websites are refused (the server checks where each request comes from), and the page is protected by a strict Content-Security-Policy. Email HTML previews are shown in a fully sandboxed frame.
- The page never receives the SMTP password. It only learns whether sending is configured.
- Anyone who can use your Windows account while the page is running could use it, just as they could open your files. Stop it with Ctrl+C when you're done.

## Consent and unsubscribing

Only email people who **signed up** to test or to receive updates. Laws such as GDPR (EU/UK) and CAN-SPAM (US) require consent and a working way to opt out:

- Every email includes an unsubscribe footer and a `List-Unsubscribe` header pointing to `UNSUBSCRIBE_EMAIL`. Someone must read that inbox.
- When someone unsubscribes, set their `status` to `unsubscribed` before the next mailing.
- Keep a note of when and how each person signed up. **Import…** on the web page does this for you: it fills the `signed_up` and `source` columns. If your form asks for consent, pick that question in the import window so people who didn't agree are skipped.
- Importing never re-subscribes anyone whose status is `unsubscribed`, `bounced` or anything else that blocks them.
- The import file stays on your computer. The page reads it and passes it to the local server only.

## Reporting a vulnerability

Follow [SECURITY.md](https://github.com/reveltechnologies/automatedEmail_sender/blob/main/SECURITY.md): use GitHub Private Vulnerability Reporting, not a public issue.
