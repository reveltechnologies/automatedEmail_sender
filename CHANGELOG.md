# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--- To add private notes or comments in this changelog that won't show in the rendered release, use markdown comments like this. -->

## [Unreleased]
<!-- Rename to "## [1.1.0] - YYYY-MM-DD" when merging to main. Pushing a version heading from any branch creates that GitHub release. -->

### Added
- `email-sender` command-line tool (`src/email_sender/`) for emailing testers and subscribers. Each person gets their own personalised copy, so recipients never see each other's addresses.
- Subscriber list from CSV (comma or semicolon) with `status` and `tags`. Unsubscribed addresses are blocked everywhere in the file, duplicates and invalid addresses are skipped, and `--tag` picks a group.
- Plain-text templates with an optional HTML version, using `$first_name`, `$name` and `$email` placeholders. Unknown placeholders stop the run before anything is sent.
- Preview by default, `--test-to` for a single test copy, and `--send` with a typed confirmation.
- Resumable delivery log (`state/sent_log.csv`) per campaign, plus `--limit` and `--delay` for working within provider sending limits.
- Automatic unsubscribe footer and `List-Unsubscribe` header.
- Encrypted SMTP only (STARTTLS or SSL), with settings read from `.env` or environment variables (`.env.example` provided).
- Example recipient list and welcome template, unit tests, and `pyproject.toml`.
- Wiki pages `docs/Usage.md` and `docs/Privacy-and-Security.md`.
- Web page (`email-sender ui`) that runs only on your own computer, with three tabs:
  - **Recipients:** edit the list in a table, with validation, duplicate highlighting, a backup copy on every save, and protection against overwriting changes made in Excel.
  - **Compose & send:** template editor with placeholder buttons, group picker, live preview as any recipient, a test send, and sending with live progress and Stop.
  - **History:** per-campaign totals.
- The page is protected by a per-start access key, host and origin checks, and a strict Content-Security-Policy, and it never receives the SMTP password.

### Fixed
- The docs sync workflow no longer wipes other branches (`rsync --delete` on the repository root), and it skips Dependabot branches.

### Changed
- `README.md` now describes the email sender instead of the repository template.
- `.gitignore` now excludes subscriber data (`data/*`), the delivery log and Python build artifacts.

## [1.0.0] - 2026-10-24

### Added
- Universal CodeQL security workflow (`codeql.yml`) using `codeql-action@v4` with dynamic multi-language detection.
- Automated repository visibility check skipping CodeQL on private repositories to avoid Advanced Security license errors.
- Automated release workflow (`release-from-changelog.yml`) syncing GitHub releases and comparison links.
- Automated `SECURITY.md` management tracking the latest major release.
- Wiki synchronization workflow (`wiki-sync.yml`) mirroring `docs/` to GitHub Wiki.
- Multi-branch documentation, workflow, and metadata sync (`sync-documentation.yml`).
- Centralized configuration file (`config.yaml`).
- Default documentation landing page (`docs/Home.md`) and navigation (`docs/_Sidebar.md`).
- Issue templates for bug reports and feature requests (`.github/ISSUE_TEMPLATE/`).
- Pull request template (`.github/pull_request_template.md`).
- Dependabot configuration for GitHub Actions (`.github/dependabot.yml`).
- Contributor Covenant Code of Conduct (`CODE_OF_CONDUCT.md`).
- Universal contribution guide (`CONTRIBUTING.md`).
- Template license guide (`LICENSE`).
- Universal `.gitattributes` and expanded `.gitignore`.
- Template setup and quickstart guide (`README.md`).
- test

## [1.0.0-rc.1] - 2026-10-20
<!-- EXAMPLE: Use '-rc.X' for Release Candidates. The release action will automatically mark it as a Pre-release on GitHub. -->

### Added
- Example testing notes for documentation synchronization.
- Example entry showing how to document new configuration additions.

### Changed
- Standardized file paths across workflow triggers.

## [1.0.0-beta.1] - 2026-10-15
<!-- EXAMPLE: Use '-beta.X' for Beta builds. You can add sections like Added, Changed, Fixed, or Removed. -->

### Added
- Example beta features and testing notes.

### Fixed
- Example bugfix note describing resolved issues.

## [1.0.0-alpha.1] - 2026-10-10
<!-- EXAMPLE: Use '-alpha.X' for early preview builds. You can replace, edit, or delete these example sections at any time. -->

### Added
- Prototype notes and initial experimental features.
