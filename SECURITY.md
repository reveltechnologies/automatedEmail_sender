# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Please report vulnerabilities through GitHub Private Vulnerability Reporting or contact the maintainers directly.

Do not include real subscriber data, SMTP passwords or `.env` contents in a report. Use `@example.com` addresses to show the problem.

## Credentials and Subscriber Data

This project handles personal data. `.env`, `data/*.csv` and `state/` are git-ignored and must never be committed. If credentials are ever exposed, change the SMTP password immediately. See [docs/Privacy-and-Security.md](docs/Privacy-and-Security.md).
