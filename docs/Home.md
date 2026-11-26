# Automated Email Sender

A command-line tool for emailing our app's testers and subscribers. Each person gets their own personalised copy, so nobody sees anyone else's address.

## Pages

- [Usage](Usage): settings, the recipient list, templates, and sending.
- [Privacy and Security](Privacy-and-Security): handling subscriber data, consent, and reporting vulnerabilities.

## The usual workflow

The easiest way is the web page: run `email-sender ui`, then use the **Recipients** tab, then **Compose & send**. See [Usage](Usage).

From the command line:

1. Update `data/recipients.csv` with new sign-ups and unsubscribes.
2. Write or reuse a template in `templates/`.
3. Preview: `email-sender -t templates/<file>.txt -r data/recipients.csv --tag tester`
4. Send a test to yourself with `--test-to you@yourdomain.com`.
5. Send for real with `--send`.

---

*These pages live in the repository's `docs/` folder and are mirrored to the GitHub Wiki automatically. Edit them there, not in the Wiki.*
