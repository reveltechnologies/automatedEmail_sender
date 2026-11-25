# Source Directory

The `email_sender` package. Standard library only.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Command-line options, preview / test / send flow, confirmation prompt. |
| `config.py` | Loads sender and SMTP settings from the environment or `.env`. |
| `recipients.py` | Reads the subscriber CSV; validates addresses, honours unsubscribes, removes duplicates, filters by tag. |
| `templates.py` | Loads templates, rejects unknown placeholders, renders per recipient (values are HTML-escaped in HTML bodies). |
| `sender.py` | Builds one message per recipient (with unsubscribe footer and header), sends over an encrypted SMTP session, and keeps the resumable delivery log. |

Tests are in `../tests` and use a fake SMTP server, so they never send real email.
