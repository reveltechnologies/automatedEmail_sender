"""Load and filter the subscriber list from a CSV file.

Expected columns (header names are case-insensitive, only ``email`` is
required)::

    email,name,status,tags
    ana@example.com,Ana Rossi,subscribed,tester beta

* ``status`` - blank or ``subscribed`` means the person may be emailed.
  Anything else (``unsubscribed``, ``bounced``, ``pending``...) blocks that
  address everywhere in the file, even if another row says ``subscribed``.
* ``tags`` - free-form labels separated by spaces, ``|``, ``,`` or ``;``.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

SENDABLE_STATUSES = frozenset({"", "subscribed"})

_EMAIL_RE = re.compile(r"[^@\s<>()\[\],;:\"]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")
_TAG_SPLIT_RE = re.compile(r"[|,;\s]+")


class RecipientError(Exception):
    """Raised when the recipient file cannot be used at all."""


@dataclass(frozen=True)
class Recipient:
    email: str
    name: str = ""
    tags: frozenset[str] = frozenset()


@dataclass
class LoadResult:
    recipients: list[Recipient] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL_RE.fullmatch(value))


def _clean(value: str | None) -> str:
    # Collapsing all whitespace also removes CR/LF, so a name can never
    # smuggle extra headers into the message.
    return " ".join((value or "").split())


def _sniff_dialect(sample: str) -> type[csv.Dialect] | csv.Dialect:
    # Excel saves CSV with ';' in many European locales.
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def load_recipients(path: Path, tags: set[str] | None = None) -> LoadResult:
    """Read ``path`` and return the people who may receive an email.

    If ``tags`` is given, only recipients carrying at least one of those
    tags are returned. Invalid, blocked and duplicate rows are listed in
    ``LoadResult.skipped`` with the reason.
    """
    with path.open(newline="", encoding="utf-8-sig") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        reader = csv.DictReader(fh, dialect=_sniff_dialect(sample))
        if not reader.fieldnames:
            raise RecipientError(f"{path} is empty")
        columns = {name.strip().lower(): name for name in reader.fieldnames if name}
        if "email" not in columns:
            raise RecipientError(f"{path} has no 'email' column (found: {', '.join(reader.fieldnames)})")

        def col(row: dict, name: str) -> str:
            key = columns.get(name)
            return _clean(row.get(key)) if key else ""

        result = LoadResult()
        rows: list[tuple[int, str, str, str, frozenset[str]]] = []
        for row_no, row in enumerate(reader, start=2):
            email = col(row, "email").lower()
            if not email:
                result.skipped.append(f"row {row_no}: no email address")
                continue
            if not is_valid_email(email):
                result.skipped.append(f"row {row_no}: invalid email address {email!r}")
                continue
            row_tags = frozenset(t for t in _TAG_SPLIT_RE.split(col(row, "tags").lower()) if t)
            rows.append((row_no, email, col(row, "name"), col(row, "status").lower(), row_tags))

    blocked = {email for _, email, _, status, _ in rows if status not in SENDABLE_STATUSES}
    wanted = {t.lower() for t in tags} if tags else None
    seen: set[str] = set()

    for row_no, email, name, status, row_tags in rows:
        if email in blocked:
            if status not in SENDABLE_STATUSES:
                result.skipped.append(f"row {row_no}: {email} is '{status}'")
            continue
        if wanted is not None and not (row_tags & wanted):
            continue
        if email in seen:
            result.skipped.append(f"row {row_no}: duplicate of {email}")
            continue
        seen.add(email)
        result.recipients.append(Recipient(email=email, name=name, tags=row_tags))

    return result
