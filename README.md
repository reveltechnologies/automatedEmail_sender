# Automated Email Sender

Send one email to many people at once: testers, beta users and subscribers of our app. You can use it to welcome new sign-ups, announce test builds, or get back in touch with people later.

Each person gets **their own copy**, personalised with their name and addressed only to them. Recipients never see each other's addresses.

It's a small Python tool with no third-party dependencies. You can use it from a web page that runs only on your computer, or from the command line. It works with any SMTP provider, such as Gmail, Google Workspace or Microsoft 365.

---

## Quick start

Requires **Python 3.11+**.

```bash
pip install -e .                     # installs the `email-sender` command
cp .env.example .env                 # then fill in your SMTP details
```

### Using the web page (easiest)

```bash
email-sender ui
```

Your browser opens the page. Keep the terminal window open while you use it, and press Ctrl+C there to stop.

- **Recipients:** add people, edit names and tags, and mark people as unsubscribed. Then click **Save list**, which saves to `data/recipients.csv`.
- **Compose & send:** pick or write a template, choose a group (for example *tester*), and check the live preview. Then click **Send test to me**, and finally **Send to N people**. Progress shows on the page, and you can stop partway.
- **History:** see each campaign and how many people received it.

The page only works on your own computer, and only through the link printed in the terminal.

### Using the command line

```bash
cp data/recipients.example.csv data/recipients.csv   # then add your real list
```

1. **Preview.** Nothing is sent. It shows the first email and who would get it:
   ```bash
   email-sender -t templates/welcome-testers.txt -r data/recipients.csv --tag tester
   ```
2. **Send a test copy to yourself:**
   ```bash
   email-sender -t templates/welcome-testers.txt -r data/recipients.csv --tag tester --test-to you@yourdomain.com
   ```
3. **Send for real.** It asks you to type `yes` first:
   ```bash
   email-sender -t templates/welcome-testers.txt -r data/recipients.csv --tag tester --send
   ```

Without installing, you can run `python -m email_sender ...` with `PYTHONPATH=src`.

## How it works

| Piece | What it is |
| --- | --- |
| `data/recipients.csv` | Your list. Columns: `email` (required), `name`, `status`, `tags`. People whose `status` is anything other than blank or `subscribed` (for example `unsubscribed`) are never emailed. |
| `templates/*.txt` | A `Subject: ...` line, a blank line, then the body. Use `$first_name`, `$name` or `$email` for personal details. Add an optional `.html` version with `--html`. |
| `.env` | Sender address and SMTP login. See [`.env.example`](.env.example). |
| `state/sent_log.csv` | A record of who already received each campaign. If a run stops partway, run the same command again and it continues with the people who haven't been emailed yet. |

Every email gets an unsubscribe footer and a `List-Unsubscribe` header automatically.

Full guide: [docs/Usage.md](docs/Usage.md). Data and security rules: [docs/Privacy-and-Security.md](docs/Privacy-and-Security.md).

## Development

```bash
python -m unittest discover -s tests -t .
```

Code lives in [`src/email_sender/`](src/README.md). See [CONTRIBUTING.md](CONTRIBUTING.md) for how to propose changes, and [SECURITY.md](SECURITY.md) for how to report vulnerabilities.

## Repository automation

This repo was created from a template that runs the following on every push. Each can be switched off in [`config.yaml`](config.yaml).

- **CodeQL** security analysis (public repositories only).
- **GitHub Releases** created from the version headings in `CHANGELOG.md`. Keep new work under `## [Unreleased]` until you merge, because pushing a version heading from any branch creates that release.
- **`SECURITY.md`** supported-versions table kept up to date.
- **Docs sync** across branches, and **`docs/` mirrored to the GitHub Wiki** (create a `Home` page in the Wiki tab once to enable this).
