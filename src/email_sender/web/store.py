"""The files the web page edits: the recipient CSV and the templates folder."""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
from pathlib import Path

from ..recipients import sniff_dialect, is_valid_email
from ..templates import EmailTemplate, compose_template_text, load_template, parse_template, split_template_text

CORE_COLUMNS = ("email", "name", "status", "tags")
TEMPLATE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


class StoreError(Exception):
    def __init__(self, message: str, *, status: int = 400, details: list | None = None):
        super().__init__(message)
        self.status = status
        self.details = details


def _version(data: bytes | None) -> str:
    return "missing" if data is None else hashlib.sha256(data).hexdigest()[:16]


def _one_line(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def _write_atomic(path: Path, data: bytes, *, backup: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        if backup and path.is_file():
            path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise StoreError(f"Couldn't write {path.name}. Is it open in Excel or another program? "
                         "Close it and try again.", status=409) from None


class RecipientTable:
    """The recipient CSV as columns + rows of strings.

    Rows are lists (not dicts) so unusual files with repeated or blank
    column names survive a round trip, and columns this tool doesn't know
    about (e.g. a sign-up date) are kept as they are.
    """

    def __init__(self, path: Path):
        self.path = path

    def _read(self) -> bytes | None:
        return self.path.read_bytes() if self.path.is_file() else None

    def load(self) -> dict:
        data = self._read()
        if data is None:
            return {"columns": list(CORE_COLUMNS), "rows": [], "version": "missing", "exists": False}
        text = data.decode("utf-8-sig")
        parsed = list(csv.reader(io.StringIO(text, newline=""), sniff_dialect(text[:4096])))
        header = parsed[0] if parsed else []
        rows = [raw for raw in parsed[1:] if any(cell.strip() for cell in raw)]
        width = max([len(header), *map(len, rows)])

        columns: list[str] = []
        taken: set[str] = set()

        def add(name: str) -> None:
            # Column names must be unique (case-insensitive) or the file couldn't be saved again.
            candidate, n = name, 2
            while candidate.lower() in taken:
                candidate, n = f"{name}_{n}", n + 1
            taken.add(candidate.lower())
            columns.append(candidate)

        for index in range(width):
            name = _one_line(header[index]) if index < len(header) else ""
            add(name.lower() if name.lower() in CORE_COLUMNS else (name or f"column_{index + 1}"))
        for core in CORE_COLUMNS:
            if core not in columns:
                add(core)
        rows = [row + [""] * (len(columns) - len(row)) for row in rows]
        return {"columns": columns, "rows": rows, "version": _version(data), "exists": True}

    def save(self, columns: object, rows: object, version: object) -> dict:
        current = self._read()
        if version != _version(current):
            raise StoreError("The recipient list was changed outside this page (for example in Excel). "
                             "Reload to get the latest version.", status=409)

        if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
            raise StoreError("columns must be a list of names")
        columns = [_one_line(c) for c in columns]
        lowered = [c.lower() for c in columns]
        if "" in columns or len(set(lowered)) != len(lowered):
            raise StoreError("Column names must be non-empty and unique.")
        if "email" not in lowered:
            raise StoreError("The list needs an 'email' column.")
        columns = [c.lower() if c.lower() in CORE_COLUMNS else c for c in columns]
        email_col = columns.index("email")

        if not isinstance(rows, list):
            raise StoreError("rows must be a list")
        clean_rows: list[list[str]] = []
        errors = []
        seen: dict[str, int] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != len(columns):
                raise StoreError(f"row {index + 1} doesn't match the columns")
            values = [_one_line(v) for v in row]
            if not any(values):
                continue
            email = values[email_col]
            if not email:
                errors.append({"row": index, "message": "Email address is missing."})
            elif not is_valid_email(email.lower()):
                errors.append({"row": index, "message": f"'{email}' isn't a valid email address."})
            elif email.lower() in seen:
                errors.append({"row": index, "message": f"{email} is already on the list (row {seen[email.lower()] + 1})."})
            else:
                seen[email.lower()] = index
            clean_rows.append(values)
        if errors:
            raise StoreError("Some rows need fixing before the list can be saved.", details=errors)

        delimiter = ","
        if current is not None:
            text = current.decode("utf-8-sig")
            delimiter = getattr(sniff_dialect(text[:4096]), "delimiter", ",")
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
        writer.writerow(columns)
        writer.writerows(clean_rows)
        # utf-8 with BOM so Excel shows accented names correctly; the loader accepts both.
        _write_atomic(self.path, buffer.getvalue().encode("utf-8-sig"), backup=True)
        return self.load()


class TemplateStore:
    """Templates are ``<name>.txt`` (subject + text) with an optional ``<name>.html``."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _paths(self, name: str) -> tuple[Path, Path]:
        if not isinstance(name, str) or not TEMPLATE_NAME_RE.fullmatch(name):
            raise StoreError("Template names can only use letters, numbers, '-' and '_' (max 64).")
        return self.directory / f"{name}.txt", self.directory / f"{name}.html"

    def list(self) -> list[dict]:
        if not self.directory.is_dir():
            return []
        return [
            {"name": p.stem, "has_html": p.with_suffix(".html").is_file()}
            for p in sorted(self.directory.glob("*.txt"), key=lambda p: p.stem.lower())
            if TEMPLATE_NAME_RE.fullmatch(p.stem)
        ]

    def get(self, name: str) -> dict:
        text_path, html_path = self._paths(name)
        if not text_path.is_file():
            raise StoreError(f"There is no template called '{name}'.", status=404)
        raw = text_path.read_text(encoding="utf-8-sig")
        # Open even a broken file, so it can be fixed here.
        subject, body = split_template_text(raw) or ("", raw)
        html_body = html_path.read_text(encoding="utf-8-sig") if html_path.is_file() else ""
        return {"name": name, "subject": subject, "text": body, "html": html_body}

    def load(self, name: str) -> EmailTemplate:
        """The saved template, strictly validated (used for sending)."""
        text_path, html_path = self._paths(name)
        if not text_path.is_file():
            raise StoreError(f"There is no template called '{name}'. Save it first.", status=404)
        return load_template(text_path, html_path if html_path.is_file() else None)

    def save(self, name: str, subject: object, text: object, html_body: object, *, create: bool) -> dict:
        text_path, html_path = self._paths(name)
        if create and text_path.exists():
            raise StoreError(f"A template called '{name}' already exists. Pick another name.", status=409)
        if not all(isinstance(v, str) for v in (subject, text, html_body)):
            raise StoreError("subject, text and html must be text")
        raw = compose_template_text(subject, text)
        html_body = html_body if html_body.strip() else None
        parse_template(raw, html_body, "Message", "HTML version")  # raises TemplateError
        _write_atomic(text_path, raw.encode("utf-8"), backup=False)
        if html_body is not None:
            _write_atomic(html_path, html_body.encode("utf-8"), backup=False)
        elif html_path.is_file():
            html_path.unlink()
        return self.get(name)
