"""Add sign-ups from another file (for example a Google Form export) to the recipient list.

Merge rules:

* Nobody is added twice. People already on the list can get extra tags, and
  an empty name is filled in, but their status is never changed.
* An address that is blocked anywhere in the list (``unsubscribed``,
  ``bounced``...) stays blocked. Importing it again does nothing.
* If a consent column is chosen, only rows where it was answered/ticked are
  imported.
* New people get ``status=subscribed``, the chosen tags, and a ``signed_up``
  date and ``source`` so there is a record of how they joined.

Files with a header row (CSV from Google Forms, Sheets or Excel, also the
``.zip`` Google Forms downloads) let you pick which column is which. A file or
pasted text without a header is read as a plain list of addresses, one or
more per line, optionally written as ``Name <address>``.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date

from .recipients import SENDABLE_STATUSES, is_valid_email, sniff_dialect

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_UNZIPPED_BYTES = 20 * 1024 * 1024
MAX_SOURCE_LENGTH = 100

_ANGLE_RE = re.compile(r"^(.*?)<\s*([^<>\s]+)\s*>$")
_TAG_SPLIT_RE = re.compile(r"[|,;\s]+")
# Answers that mean "no consent". Google Forms leaves an unticked checkbox empty.
_NO = frozenset({"", "no", "n", "false", "0", "off", "unchecked", "nee", "nein", "non", "nej"})

_FULL_NAME = {"name", "full name", "your name", "your full name", "first and last name", "name and surname"}
_FIRST_NAME = {"first name", "firstname", "given name", "first", "voornaam"}
_LAST_NAME = {"last name", "lastname", "surname", "family name", "last", "achternaam"}
_NOT_A_PERSON = ("user", "company", "team", "app", "file", "business", "organisation", "organization",
                 "project", "product", "pet", "first", "last", "surname", "given", "family")
_DATE_PHRASES = ("timestamp", "submitted", "signed up", "sign up", "signup", "tijdstempel")
_DATE_WORDS = frozenset({"date", "datum", "time"})
_CONSENT_WORDS = ("consent", "agree", "permission", "opt in", "optin", "subscribe", "newsletter", "gdpr")


class ImportFileError(Exception):
    """The file can't be read as a list of people."""


def _clean(value: str | None) -> str:
    # Collapsing whitespace also removes line breaks (no header injection).
    return " ".join((value or "").split())


def _norm(header: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", header.lower()).split())


def split_address(cell: str) -> tuple[str, str]:
    """``"Ana <ana@x.com>"`` -> ``("Ana", "ana@x.com")``. The address is "" if it isn't valid."""
    match = _ANGLE_RE.match(cell)
    name, address = (match.group(1).strip().strip('"').strip(), match.group(2)) if match else ("", cell)
    address = address.strip().lower()
    if address.startswith("mailto:"):
        address = address[len("mailto:"):]
    return name, (address if is_valid_email(address) else "")


def parse_tags(values) -> list[str]:
    """Tags from a list of strings or one string, lower-case, de-duplicated, order kept."""
    if isinstance(values, str):
        values = [values]
    tags: list[str] = []
    for value in values:
        for tag in _TAG_SPLIT_RE.split(value.lower()):
            if tag and tag not in tags:
                tags.append(tag)
    return tags


# ---------------------------------------------------------------- reading the file
def decode_upload(data: bytes) -> str:
    """Bytes of an uploaded .csv/.txt (or a .zip holding one) -> text."""
    if len(data) > MAX_FILE_BYTES:
        raise ImportFileError("The file is too big to import (the limit is 3 MB).")
    if data[:4] == b"PK\x03\x04":
        data = _from_zip(data)
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")  # never fails


def _from_zip(data: bytes) -> bytes:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFileError("This file looks damaged. Save it again as CSV and import that.") from None
    with archive:
        names = archive.namelist()
        if any(name.startswith("xl/") for name in names):
            raise ImportFileError("This is an Excel workbook (.xlsx). In Excel choose File > Save As > "
                                  "CSV UTF-8, then import that file.")
        files = [info for info in archive.infolist()
                 if not info.is_dir() and info.filename.lower().endswith((".csv", ".txt"))
                 and not info.filename.startswith("__MACOSX/")]
        if not files:
            raise ImportFileError("This .zip file has no .csv file in it.")
        info = files[0]
        if info.file_size > MAX_UNZIPPED_BYTES:
            raise ImportFileError("The file inside the .zip is too big to import.")
        with archive.open(info) as fh:
            content = fh.read(MAX_UNZIPPED_BYTES + 1)
        if len(content) > MAX_UNZIPPED_BYTES:
            raise ImportFileError("The file inside the .zip is too big to import.")
        return content


@dataclass
class SourceTable:
    """The imported file. ``rows`` holds ``(spreadsheet row number, cells)``; ``header`` is None for plain lists."""

    header: list[str] | None
    rows: list[tuple[int, list[str]]]

    @property
    def width(self) -> int:
        return max([len(self.header or []), *(len(cells) for _, cells in self.rows)])

    def column_names(self) -> list[str]:
        header = self.header or []
        return [(header[i] if i < len(header) else "") or f"Column {i + 1}" for i in range(self.width)]


def read_table(text: str) -> SourceTable:
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text, newline=""), sniff_dialect(text[:4096]))
    numbered = [(n, cells) for n, cells in
                ((n, [_clean(c) for c in row]) for n, row in enumerate(reader, start=1)) if any(cells)]
    if not numbered:
        raise ImportFileError("There is nothing to import: the file or text is empty.")
    _, first = numbered[0]
    if any(_addresses_in(cell)[0] for cell in first):
        return SourceTable(None, numbered)  # the first line already has addresses: no header
    if len(numbered) == 1:
        raise ImportFileError("The file only has a header row and nobody in it.")
    return SourceTable(first, numbered[1:])


# ---------------------------------------------------------------- columns
@dataclass
class Mapping:
    email: int
    name: list[int] = field(default_factory=list)
    date: int | None = None
    consent: int | None = None

    def to_dict(self) -> dict:
        return {"email": self.email, "name": self.name, "date": self.date, "consent": self.consent}

    @classmethod
    def from_dict(cls, raw: object, width: int) -> "Mapping":
        if not isinstance(raw, dict):
            raise ImportFileError("mapping must be an object")

        def index(value: object, label: str) -> int | None:
            if value is None:
                return None
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < width:
                raise ImportFileError(f"The {label} column doesn't exist in this file.")
            return value

        email = index(raw.get("email"), "email")
        if email is None:
            raise ImportFileError("Choose which column holds the email addresses.")
        names = raw.get("name") or []
        if not isinstance(names, list) or len(names) > 3:
            raise ImportFileError("name must be a list of columns")
        return cls(email, [index(n, "name") for n in names], index(raw.get("date"), "date"),
                   index(raw.get("consent"), "consent"))


def guess_mapping(table: SourceTable) -> Mapping:
    """Pick the likely email, name, date and consent columns from the header and the values."""
    width = table.width
    headers = [_norm(h) for h in (table.header or [])] + [""] * width
    headers = headers[:width]

    def addresses_in(i: int) -> int:
        return sum(1 for _, cells in table.rows if i < len(cells) and split_address(cells[i])[1])

    def email_score(h: str) -> int:
        if h in {"email", "email address", "e mail", "e mail address", "mail", "emailadres"}:
            return 2
        return 1 if ("email" in h or "e mail" in h) else 0

    counts = [addresses_in(i) for i in range(width)]
    email = max(range(width), key=lambda i: (counts[i] > 0, email_score(headers[i]), counts[i], -i))
    taken = {email}

    def first(test) -> int | None:
        return next((i for i in range(width) if i not in taken and test(headers[i])), None)

    name: list[int] = []
    full = first(lambda h: h in _FULL_NAME)
    if full is not None:
        name = [full]
    else:
        given, family = first(lambda h: h in _FIRST_NAME), first(lambda h: h in _LAST_NAME)
        if given is not None or family is not None:
            name = [i for i in (given, family) if i is not None]
        else:
            other = first(lambda h: "name" in h.split() and not any(w in h for w in _NOT_A_PERSON))
            name = [other] if other is not None else []
    taken.update(name)

    when = first(lambda h: any(w in h for w in _DATE_PHRASES) or bool(_DATE_WORDS & set(h.split())))
    if when is not None:
        taken.add(when)
    consent = first(lambda h: "unsubscribe" not in h and any(w in h for w in _CONSENT_WORDS))
    return Mapping(email, name, when, consent)


# ---------------------------------------------------------------- the merge
@dataclass
class ImportPlan:
    add: list[dict] = field(default_factory=list)        # {email, name, signed_up}
    update: list[dict] = field(default_factory=list)     # {email, row, tags, name}
    unchanged: list[str] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)    # {email, status}
    skipped: list[dict] = field(default_factory=list)    # {row, reason}

    def to_dict(self) -> dict:
        return {"add": self.add, "update": self.update, "unchanged": self.unchanged,
                "blocked": self.blocked, "skipped": self.skipped}


def _addresses_in(cell: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Addresses in one cell of a plain list, which may hold several ("a@x.com; b@y.com")."""
    if not cell:
        return [], []
    name, email = split_address(cell)
    if email:
        return [(name, email)], []
    found, rest = [], []
    for part in (p.strip() for p in re.split(r"[;,]", cell)):
        name, email = split_address(part)
        if email:
            found.append((name, email))
            continue
        words = part.split()
        hits = [split_address(w)[1] for w in words]
        if any(hits):
            found += [("", e) for e in hits if e]
            rest += [w for w, e in zip(words, hits) if not e]
        elif part:
            rest.append(part)
    return found, rest


def _entries(table: SourceTable, mapping: Mapping | None, plan: ImportPlan):
    """Yield ``(row number, email, name, signed_up)`` for each person in the file."""
    for number, cells in table.rows:
        def get(i: int | None) -> str:
            return cells[i] if i is not None and i < len(cells) else ""

        if mapping is None:  # a plain list: every address in the line is a person
            people, others = [], []
            for cell in cells:
                found, rest = _addresses_in(cell)
                people += found
                others += rest
            if not people:
                plan.skipped.append({"row": number, "reason": f"no email address in “{' '.join(cells)}”"})
                continue
            if len(people) == 1 and not people[0][0] and others:
                people = [(" ".join(others), people[0][1])]  # "ana@x.com, Ana Rossi"
            for name, email in people:
                yield number, email, name, ""
            continue

        raw = get(mapping.email)
        if not raw:
            plan.skipped.append({"row": number, "reason": "no email address"})
            continue
        angle_name, email = split_address(raw)
        if not email:
            plan.skipped.append({"row": number, "reason": f"“{raw}” isn't a valid email address"})
            continue
        if mapping.consent is not None and get(mapping.consent).lower() in _NO:
            question = table.column_names()[mapping.consent]
            plan.skipped.append({"row": number, "reason": f"{email} didn't agree (“{question}” is empty or no)"})
            continue
        name = " ".join(v for v in (get(i) for i in mapping.name) if v) or angle_name
        yield number, email, name, get(mapping.date)


def plan_import(table: SourceTable, mapping: Mapping | None, columns: list[str], rows: list[list[str]],
                *, tags: list[str], today: date | None = None) -> ImportPlan:
    """Work out what importing ``table`` into the list (``columns``/``rows``) would change."""
    ec, nc, sc, tc = (columns.index(c) for c in ("email", "name", "status", "tags"))
    existing: dict[str, int] = {}
    blocked: dict[str, str] = {}
    for index, row in enumerate(rows):
        email = row[ec].strip().lower()
        if not email:
            continue
        existing.setdefault(email, index)
        status = row[sc].strip().lower()
        if status not in SENDABLE_STATUSES:
            blocked.setdefault(email, status)

    stamp = (today or date.today()).isoformat()
    plan = ImportPlan()
    seen: set[str] = set()
    for number, email, name, signed_up in _entries(table, mapping, plan):
        if email in seen:
            plan.skipped.append({"row": number, "reason": f"{email} is in the file more than once (the first is used)"})
            continue
        seen.add(email)
        if email in blocked:
            plan.blocked.append({"email": email, "status": blocked[email]})
        elif email in existing:
            index = existing[email]
            have = set(parse_tags(rows[index][tc]))
            new_tags = [t for t in tags if t not in have]
            fill_name = name if name and not rows[index][nc].strip() else ""
            if new_tags or fill_name:
                plan.update.append({"email": email, "row": index, "tags": new_tags, "name": fill_name})
            else:
                plan.unchanged.append(email)
        else:
            plan.add.append({"email": email, "name": name, "signed_up": signed_up or stamp})
    return plan


def apply_import(plan: ImportPlan, columns: list[str], rows: list[list[str]], *, tags: list[str],
                 source: str) -> tuple[list[str], list[list[str]]]:
    """Return new columns/rows with ``plan`` applied. The inputs are not modified."""
    columns = list(columns)
    rows = [list(row) for row in rows]

    def ensure(name: str) -> int:
        for i, existing in enumerate(columns):
            if existing.lower() == name:
                return i
        columns.append(name)
        for row in rows:
            row.append("")
        return len(columns) - 1

    ec, nc, sc, tc = (columns.index(c) for c in ("email", "name", "status", "tags"))
    for change in plan.update:
        row = rows[change["row"]]
        if change["tags"]:
            row[tc] = " ".join(v for v in (row[tc].strip(), *change["tags"]) if v)
        if change["name"]:
            row[nc] = change["name"]
    if plan.add:
        dc, src = ensure("signed_up"), ensure("source")
        for person in plan.add:
            row = [""] * len(columns)
            row[ec], row[nc], row[sc], row[tc] = person["email"], person["name"], "subscribed", " ".join(tags)
            row[dc], row[src] = person["signed_up"], source
            rows.append(row)
    return columns, rows
