# Source Directory

The `email_sender` package. Standard library only.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Command-line options, preview / test / send flow, confirmation prompt. |
| `config.py` | Loads sender and SMTP settings from the environment or `.env`. |
| `recipients.py` | Reads the subscriber CSV; validates addresses, honours unsubscribes, removes duplicates, filters by tag. |
| `templates.py` | Loads templates, rejects unknown placeholders, renders per recipient (values are HTML-escaped in HTML bodies). |
| `sender.py` | Builds one message per recipient (with unsubscribe footer and header), sends over an encrypted SMTP session, and keeps the resumable delivery log. |
| `importer.py` | Reads sign-up files (CSV, Google Forms .zip, pasted lists), guesses the columns, and merges them into the list without duplicates or re-subscribing anyone who opted out. |
| `campaign.py` | Works out who a campaign goes to and builds the messages. Shared by the command line and the web page. |
| `web/server.py` | `email-sender ui`: local-only HTTP server with a token-protected JSON API and the background send job. |
| `web/store.py` | Reads and saves the recipient CSV (keeps extra columns and the delimiter, makes a `.bak`, detects edits made elsewhere) and the templates folder. |
| `web/static/` | The page itself (`index.html`, `app.css`, `app.js`). No build step and no external resources. |

Tests are in `../tests` and use a fake SMTP server, so they never send real email.
