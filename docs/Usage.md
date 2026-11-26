# Usage

## 1. Settings (`.env`)

Copy `.env.example` to `.env` and fill it in. Any of these can also be set as real environment variables, which take priority over the file.

| Setting | Required | Notes |
| --- | --- | --- |
| `SENDER_EMAIL` | yes | The From address. |
| `SENDER_NAME` | no | Shown as the sender name, for example `Example App Team`. |
| `REPLY_TO` | no | Where replies go. |
| `UNSUBSCRIBE_EMAIL` | no | Where unsubscribe requests go (defaults to `SENDER_EMAIL`). |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD` | to send | Not needed for previews. |
| `SMTP_PORT` | no | Defaults to 587 (`starttls`) or 465 (`ssl`). |
| `SMTP_SECURITY` | no | `starttls` (default) or `ssl`. Unencrypted connections are refused. |

**Gmail / Google Workspace:** turn on 2-step verification, create an [App Password](https://myaccount.google.com/apppasswords), and use it as `SMTP_PASSWORD`. Gmail allows about 500 recipients a day (Workspace about 2,000). For bigger lists, use `--limit` to spread sending over several days, or switch to a transactional email provider.

## Using the web page

On Windows, double-click `start.bat` in the project folder (no install needed). Otherwise run `email-sender ui` from the project folder. Your browser opens the page. If it doesn't, copy the link printed in the terminal, which includes a one-time access key. Keep the terminal window open while you use the page.

| Tab | What you do there |
| --- | --- |
| **Recipients** | Add people (**+ Add person**, or **Import…** for many at once, see below), edit any cell, and set the status to *unsubscribed* when someone opts out. Invalid or duplicate addresses are highlighted. Click **Save list**, or press Ctrl+S. A copy of the previous version is kept as `data/recipients.csv.bak`. |
| **Compose & send** | Choose a template or create one with **New template**. Insert personal details with the *First name / Full name / Email address* buttons, and click **Save template**. Pick a group, check the preview (you can choose who to preview it as), click **Send test to me**, then **Send to N people**. |
| **History** | Each campaign: how many people received it, how many addresses were refused, and when it last ran. |

Good to know:

- **What's saved is what gets sent.** The send buttons stay disabled until the template and the list are saved.
- If the list changes between the preview and clicking Send, the send is refused, so you can check the new numbers first.
- If you edit the CSV in Excel while the page is open, the page won't overwrite those changes. It asks you to reload instead. If saving fails because the file is open in Excel, close the file in Excel and save again.
- **Stop** finishes the email in progress and then stops. Click Send again later to continue with the people who haven't had it yet.
- Options: `email-sender ui --port 8765 --delay 1 --no-browser --recipients data/recipients.csv --templates templates`.

### Importing sign-ups (Google Forms, spreadsheets, pasted lists)

On the **Recipients** tab, click **Import…** and choose a file, or paste addresses.

- **Google Forms:** on the form's **Responses** tab, click **⋮** and then **Download responses (.csv)**. You can choose the downloaded `.zip` directly.
- **Google Sheets:** File > Download > Comma-separated values. **Excel:** File > Save As > CSV UTF-8. Excel `.xlsx` files can't be imported directly.
- **Pasting:** one address per line, or several separated by `,` or `;`. `Name <address>` also works.

The page guesses which column holds the email address, the name (or first and last name), the sign-up date and a consent question such as "I agree to receive emails". Check its choices and change them if needed. Then choose the tags the new people get (default `tester`) and where they signed up. The window shows what will happen before anything is saved:

| Shown as | What happens |
| --- | --- |
| **New people** | Added as *subscribed*, with your tags, `signed_up` (the form's timestamp, or today) and `source`. |
| **Get updated** | Already on the list. They get any of your tags they don't have yet, and a name if theirs was empty. Their status is never changed. |
| **Already on the list** | Nothing changes. This includes people who unsubscribed or bounced: **importing never subscribes them again.** |
| **Skipped** | Invalid addresses, people who appear twice in the file, and, if you picked a consent column, people who left it empty or answered no. |

The import is saved straight to the list file, and the previous version is kept as `recipients.csv.bak`.

## 2. Recipient list (`data/recipients.csv`)

```csv
email,name,status,tags
ana.tester@example.com,Ana Rossi,subscribed,tester beta
dana@example.com,Dana Smith,unsubscribed,tester
```

- `email` is the only required column. Comma- or semicolon-separated files both work, so you can export straight from Excel or Google Sheets.
- `status`: blank or `subscribed` means the person can be emailed. Any other value (`unsubscribed`, `bounced`, `pending`...) blocks that address, **even if it appears in another row as subscribed**.
- `tags`: labels separated by spaces or `|`. Pick a group with `--tag tester` (repeat `--tag` to include several groups).
- Duplicates and invalid addresses are skipped and listed in the output.
- When someone asks to unsubscribe, change their `status` to `unsubscribed`. Keep the row rather than deleting it, so they can't be re-added by accident.

## 3. Templates (`templates/`)

```text
Subject: Welcome to the beta, $first_name!

Hi $first_name,
...
```

- Placeholders: `$first_name`, `$name` (full name) and `$email`. If a person has no name, it becomes "there" ("Hi there,").
- Write `$$` for a literal dollar sign.
- A typo such as `$frist_name` stops the run **before anything is sent**.
- Optionally add an HTML version and pass it with `--html templates/welcome-testers.html`. The plain-text file still provides the subject and the plain-text fallback.
- The unsubscribe footer is added for you. Don't write your own.

## 4. Sending

| Option | What it does |
| --- | --- |
| *(no option)* | Preview only: shows the first email and the recipient list. |
| `--test-to ADDRESS` | Sends one copy, marked `[TEST]`, to `ADDRESS` only. It isn't logged. |
| `--send` | Sends for real, after you type `yes`. Add `--yes` to skip the prompt (for scripts). |
| `--tag TAG` | Only people with this tag. |
| `--limit N` | At most N people in this run. Run again for the next batch. |
| `--delay SECONDS` | Pause between emails (default 1). Helps avoid provider rate limits. |
| `--campaign NAME` | Name used for the "already sent" check. Defaults to the template file name. |

### Campaigns and resuming

Each successful delivery is written to `state/sent_log.csv` as soon as it happens. Re-running the same command skips everyone already emailed in that campaign. This means:

- If a run is interrupted (network drop, Ctrl+C, provider limit), run the same command again to continue.
- New people added to the CSV later get the email the next time you run it.
- To send the same template again as a new mailing, give it a new name, for example `--campaign welcome-testers-2027-01`.
- Addresses the server refused are logged as `failed` and retried on the next run.
