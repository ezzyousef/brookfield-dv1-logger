"""
core/data_io.py

File I/O for the Brookfield DV1 Viscosity Logger: sessions (JSON), CSV export and re-import,
and the readings table shared by the Excel and Origin exports. No Qt imports here.

Every importer validates the whole file before anything reaches the session: it either loads
the values exactly as written or refuses the file with a sentence naming the line (CSV) or the
reading (session) at fault. It never loads shifted or guessed numbers.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from core.analysis import Reading
from core.session import AuditEntry, ExperimentNotebook, Session
from labkit.io import atomic_save

MAX_IMPORT_BYTES = 50 * 1024 * 1024     # sessions and CSVs larger than this are refused
SESSION_FORMAT = "brookfield-dv1-logger-session"
SESSION_VERSION = 2

READING_COLUMNS = [
    "timestamp",
    "product",
    "batch",
    "viscosity_cp",
    "percent_torque",
    "torque_status",
    "temperature_c",
    "rpm",
    "spindle",
    "model",
    "shear_rate_1_per_s",
    "shear_stress_dyn_cm2",
    "full_scale_range_cp",
    "source",
    "notes",
    # added in 2.1.0, appended so older column positions do not move
    "sample_id",
    "operator",
    "source_label",
    "qc_flags",
]

NUMERIC_FIELDS = ("viscosity_cp", "percent_torque", "temperature_c", "rpm")
OPTIONAL_TEXT_FIELDS = ("spindle", "model")                  # may be null
TEXT_FIELDS = ("source", "notes", "product", "batch", "sample_id", "operator")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")


class ImportError_(ValueError):
    """A CSV file cannot be imported (the message is a sentence for the user)."""


class SessionError(ValueError):
    """A session file cannot be loaded (the message is a sentence for the user)."""


# ------------------------------------------------------------------ export text guard
def guard_text(text: str) -> str:
    """Stop a spreadsheet from running a text cell as a formula (CSV/formula injection).

    Escaping convention (reversible): a text cell gets ONE leading apostrophe when it starts
    with = + - @ tab or CR, unless the whole cell is a plain number such as -5 or +3.5e2, or when
    it already starts with an apostrophe. unguard_text() removes exactly one leading apostrophe,
    so every text, including one that really starts with ', comes back unchanged.
    """
    if not text:
        return text
    if text[0] == "'" or (text[0] in _FORMULA_START and not _NUMBER.fullmatch(text)):
        return "'" + text
    return text


def unguard_text(text: str) -> str:
    return text[1:] if text.startswith("'") else text


def readings_to_dataframe(readings: List[Reading]) -> pd.DataFrame:
    rows = []
    for r in readings:
        rows.append({
            "timestamp": r.timestamp.isoformat(sep=" ", timespec="seconds"),
            "product": guard_text(r.product),
            "batch": guard_text(r.batch),
            "viscosity_cp": r.viscosity_cp,
            "percent_torque": r.percent_torque,
            "torque_status": guard_text(r.torque_status()),
            "temperature_c": r.temperature_c,
            "rpm": r.rpm,
            "spindle": guard_text(r.spindle) if r.spindle else r.spindle,
            "model": guard_text(r.model) if r.model else r.model,
            "shear_rate_1_per_s": r.shear_rate(),
            "shear_stress_dyn_cm2": r.shear_stress(),
            "full_scale_range_cp": r.fsr(),
            "source": guard_text(r.source),
            "notes": guard_text(r.notes),
            "sample_id": guard_text(r.sample_id),
            "operator": guard_text(r.operator),
            "source_label": guard_text(r.source_label()),
            "qc_flags": guard_text("; ".join(r.qc_flags)),
        })
    return pd.DataFrame(rows, columns=READING_COLUMNS)


def export_to_excel(readings: List[Reading], path: str) -> None:
    """Requires openpyxl to be installed (pip install openpyxl)."""
    df = readings_to_dataframe(readings)
    df.to_excel(path, index=False, sheet_name="DV1 Readings")


def export_to_csv(readings: List[Reading], path: str) -> None:
    df = readings_to_dataframe(readings)
    atomic_save(path, lambda tmp: df.to_csv(tmp, index=False, encoding="utf-8"))


# ------------------------------------------------------------------ reading files safely
def _read_text(path: str | Path, error=ImportError_) -> tuple[str, list[str]]:
    p = Path(path)
    try:
        size = p.stat().st_size
        if size > MAX_IMPORT_BYTES:
            raise error(f"The file is too large ({size / 1e6:.1f} MB; the limit is "
                        f"{MAX_IMPORT_BYTES / 1e6:.0f} MB).")
        raw = p.read_bytes()
    except OSError as e:
        raise error(f"The file could not be opened: {e.strerror or e}") from e
    if not raw.strip():
        raise error("The file is empty.")
    bom16 = raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    if b"\x00" in raw[:4096] and not bom16:
        raise error("This looks like a binary file, not a text file.")
    for enc in (("utf-16",) if bom16 else ()) + ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
        except UnicodeError:
            continue
        notes = ["The file is not UTF-8; it was read as Windows-1252. Check accented characters."] \
            if enc == "cp1252" else []
        return text, notes
    raise error("The file's text encoding could not be read.")


def _clean_records(text: str) -> tuple[list[str], list[tuple[int, list[str]]], list[str]]:
    """Header and data records of a CSV, validated record by record BEFORE pandas sees them.

    - The header is the first record with a 'timestamp' cell (within the first 20 records), or
      else the first record. Records above it are title lines and are dropped, with a warning.
    - Empty trailing fields ("1,2,") are a trailing delimiter, not data, and are removed.
    - Any record still wider than the header is refused with its line number: pandas would
      otherwise use the extra leading values as row labels and shift every value.
    - Shorter records are padded with empty cells (missing values).
    """
    try:
        records = [(n, row) for n, row in enumerate(csv.reader(io.StringIO(text)), start=1)
                   if any(c.strip() for c in row)]
    except csv.Error as e:
        raise ImportError_(f"The file is not valid CSV: {e}") from e
    if not records:
        raise ImportError_("The file is empty.")

    def norm(row):
        row = list(row)
        while len(row) > 1 and not row[-1].strip():
            row.pop()
        return row

    header_at = 0
    for i, (_, r) in enumerate(records[:20]):
        if any(c.strip().lower() == "timestamp" for c in r):
            header_at = i
            break
    warnings = []
    if header_at:
        warnings.append(f"{header_at} title line(s) above the column names were skipped.")
    header = [c.strip() for c in norm(records[header_at][1])]
    data = records[header_at + 1:]
    if not data:
        raise ImportError_("The file has column names but no data rows.")
    width = len(header)
    seen: dict[str, int] = {}
    for name in header:
        key = name.lower()
        if key:
            seen[key] = seen.get(key, 0) + 1
    duplicates = [name for name in header if name and seen[name.lower()] > 1]
    if duplicates:
        raise ImportError_(f"The column name '{duplicates[0]}' appears more than once, so its values are "
                           "ambiguous. The file was not imported.")
    rows = []
    for n, raw in data:
        if len(raw) < width:
            raise ImportError_(f"Line {n} has {len(raw)} values but the header has {width}. A missing value must "
                               "be an empty field (two commas in a row), otherwise it is not clear which column "
                               "is missing. The file was not imported.")
        row = list(raw)
        while len(row) > width and not row[-1].strip():     # trailing delimiters only
            row.pop()
        if len(row) > width:
            raise ImportError_(f"Line {n} has {len(row)} values but the header has {width}. The file was not "
                               "imported, because the values could not be assigned to columns reliably.")
        rows.append((n, row))
    return header, rows, warnings


def import_from_csv(path: str) -> pd.DataFrame:
    """
    Import a previously-exported CSV (or a compatible one) as a raw DataFrame for viewing.
    Records are validated before pandas parses them (see _clean_records).
    """
    text, _ = _read_text(path)
    header, rows, _ = _clean_records(text)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for _, r in rows:
        writer.writerow(r)
    out.seek(0)
    return pd.read_csv(out, index_col=False, on_bad_lines="error")


def readings_from_csv(path: str) -> tuple[List[Reading], list[str]]:
    """Rebuild Readings from a CSV exported by this app (or one with the same column names).

    Derived columns (torque status, shear rate, shear stress, full-scale range, source label)
    are recomputed from the readings, never trusted from the file. Returns (readings, warnings).
    """
    text, warnings = _read_text(path)
    header, rows, more = _clean_records(text)
    warnings += more
    index = {name: i for i, name in enumerate(header)}
    if "timestamp" not in index:
        raise ImportError_("The file has no 'timestamp' column, so it is not a DV1 Logger CSV export.")
    readings = []
    for line, cells in rows:
        def cell(name):          # numbers, timestamps and codes: surrounding spaces ignored
            i = index.get(name)
            return cells[i].strip() if i is not None else ""

        def text(name):          # free text: kept exactly, then the export guard is removed
            i = index.get(name)
            return unguard_text(cells[i]) if i is not None else ""
        try:
            ts = datetime.fromisoformat(cell("timestamp"))
        except ValueError:
            raise ImportError_(f"Line {line}: timestamp '{cell('timestamp')}' is not a date and time.") from None
        values = {}
        for name in NUMERIC_FIELDS:
            raw = cell(name)
            if not raw or raw.lower() == "nan":
                values[name] = None
                continue
            try:
                v = float(raw)
            except ValueError:
                raise ImportError_(f"Line {line}: {name} '{raw}' is not a number.") from None
            if not math.isfinite(v):
                raise ImportError_(f"Line {line}: {name} '{raw}' is not a finite number.")
            values[name] = v
        flags = [f.strip() for f in text("qc_flags").split(";") if f.strip()]
        readings.append(Reading(
            timestamp=ts, spindle=unguard_text(cell("spindle")) or None, model=unguard_text(cell("model")) or None,
            source=unguard_text(cell("source")) or "manual", notes=text("notes"),
            product=text("product"), batch=text("batch"),
            sample_id=text("sample_id"), operator=text("operator"),
            qc_flags=flags, **values))
    return readings, warnings


# ------------------------------------------------------------------ sessions
def _reading_to_dict(r: Reading) -> dict:
    return {
        "timestamp": r.timestamp.isoformat(),
        "viscosity_cp": r.viscosity_cp,
        "percent_torque": r.percent_torque,
        "temperature_c": r.temperature_c,
        "rpm": r.rpm,
        "spindle": r.spindle,
        "model": r.model,
        "source": r.source,
        "notes": r.notes,
        "product": r.product,
        "batch": r.batch,
        "sample_id": r.sample_id,
        "operator": r.operator,
        "qc_flags": list(r.qc_flags),
    }


def session_to_dict(session: Session, app_version: str = "") -> dict:
    return {
        "format": SESSION_FORMAT,
        "format_version": SESSION_VERSION,
        "app_version": app_version,
        "saved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "export_revision": session.export_revision,
        "notebook": session.notebook.to_dict(),
        "audit": [{"time": a.time, "action": a.action, "detail": a.detail} for a in session.audit],
        "readings": [_reading_to_dict(r) for r in session.readings],
    }


def save_session(session: Session, path: str, app_version: str = "") -> None:
    """Save atomically: a failure leaves an existing file exactly as it was."""
    text = json.dumps(session_to_dict(session, app_version), indent=2, ensure_ascii=False, allow_nan=False)
    atomic_save(path, lambda tmp: tmp.write_text(text + "\n", encoding="utf-8"))


def save_session_json(readings: List[Reading], path: str) -> None:
    """
    Save the in-progress session (full Reading objects, editable/resumable) -- unlike the
    CSV/Excel export, this round-trips exactly via load_session_json().
    """
    save_session(Session(readings=list(readings)), path)


def _reading_from_dict(row, k: int, warnings: list[str]) -> Reading:
    where = f"reading {k}"
    if not isinstance(row, dict):
        raise SessionError(f"The session is damaged: {where} is not a record.")
    ts = row.get("timestamp")
    if not isinstance(ts, str):
        raise SessionError(f"The session is damaged: {where} has no timestamp.")
    try:
        timestamp = datetime.fromisoformat(ts)
    except ValueError:
        raise SessionError(f"The session is damaged: {where} has an invalid timestamp '{ts[:40]}'.") from None
    kwargs = {}
    for name in NUMERIC_FIELDS:
        v = row.get(name)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
            raise SessionError(f"The session is damaged: {where} has a non-numeric {name} ({str(v)[:40]!r}).")
        if v is not None and not math.isfinite(v):
            warnings.append(f"{where}: {name} was not a number ({v}) and was left empty.")
            v = None
        kwargs[name] = None if v is None else float(v)
    for name in OPTIONAL_TEXT_FIELDS:
        v = row.get(name)
        if v is not None and not isinstance(v, str):
            raise SessionError(f"The session is damaged: {where} has a non-text {name}.")
        kwargs[name] = v
    for name in TEXT_FIELDS:
        v = row.get(name)
        if v is None:
            v = "manual" if name == "source" else ""
        if not isinstance(v, str):
            raise SessionError(f"The session is damaged: {where} has a non-text {name}.")
        kwargs[name] = v
    flags = row.get("qc_flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise SessionError(f"The session is damaged: {where} has invalid qc_flags.")
    return Reading(timestamp=timestamp, qc_flags=list(flags), **kwargs)


_NOTEBOOK_TEXT = ("title", "instrument_id", "instrument_serial", "calibration_date", "calibration_reference",
                  "operator", "protocol", "sample_preparation", "notes")


def _finite_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _notebook_from_dict(nb: dict) -> ExperimentNotebook:
    """Validate every notebook field before it reaches the app (types, finite numbers, ranges)."""
    def bad(field, why):
        return SessionError(f"The session is damaged: notebook field '{field}' {why}.")
    for key in _NOTEBOOK_TEXT:
        if key in nb and not isinstance(nb[key], str):
            raise bad(key, "is not text")
    if "calibration_interval_months" in nb:
        v = nb["calibration_interval_months"]
        if not (isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 1200):
            raise bad("calibration_interval_months", "must be a whole number of months from 0 to 1200")
    if nb.get("target_temperature_c") is not None:
        v = nb["target_temperature_c"]
        if not (_finite_number(v) and -273.15 <= v <= 1000):
            raise bad("target_temperature_c", "must be a finite temperature in °C or empty")
    if "temperature_tolerance_c" in nb:
        v = nb["temperature_tolerance_c"]
        if not (_finite_number(v) and 0 < v <= 100):
            raise bad("temperature_tolerance_c", "must be a positive number of °C")
    if "checklist" in nb:
        c = nb["checklist"]
        if not isinstance(c, dict) or not all(isinstance(k, str) and isinstance(x, bool) for k, x in c.items()):
            raise bad("checklist", "must map each item to true or false")
    try:
        return ExperimentNotebook.from_dict(nb)
    except TypeError:
        raise SessionError("The session is damaged: the notebook is not readable.") from None


def load_session(path: str) -> Session:
    """Load a session saved by any released version (format 1 = 2.0.0's bare list, format 2)."""
    text, _ = _read_text(path, error=SessionError)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        raise SessionError(f"The session file is not valid JSON (line {e.lineno}, column {e.colno}): "
                           "it may be truncated or edited by hand.") from None
    except RecursionError:
        raise SessionError("The session file is nested too deeply to be a DV1 Logger session.") from None
    warnings: list[str] = []
    if isinstance(payload, list):
        version, rows, nb, audit, revision = 1, payload, {}, [], 0
        warnings.append("This session was saved in format version 1 (DV1 Logger 2.0); "
                        "saving it again writes version 2, which also keeps the notebook and audit trail.")
    elif isinstance(payload, dict) and payload.get("format") == SESSION_FORMAT:
        version = payload.get("format_version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise SessionError("The session file has no valid format version.")
        if version > SESSION_VERSION:
            raise SessionError(f"This session was saved by a newer DV1 Logger (format {version}); "
                               "update the app to open it.")
        rows = payload.get("readings")
        if not isinstance(rows, list):
            raise SessionError("The session is damaged: 'readings' is not a list.")
        nb = payload.get("notebook") or {}
        audit = payload.get("audit") or []
        revision = payload.get("export_revision", 0)
        if not isinstance(nb, dict) or not isinstance(audit, list):
            raise SessionError("The session is damaged: the notebook or audit trail is not readable.")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            revision = 0
    else:
        raise SessionError("This file is not a DV1 Logger session.")
    readings = [_reading_from_dict(row, k, warnings) for k, row in enumerate(rows, start=1)]
    notebook = _notebook_from_dict(nb)
    entries = []
    for a in audit:
        if isinstance(a, dict) and all(isinstance(a.get(k, ""), str) for k in ("time", "action", "detail")):
            entries.append(AuditEntry(a.get("time", ""), a.get("action", ""), a.get("detail", "")))
    return Session(readings=readings, notebook=notebook, audit=entries, export_revision=revision,
                   format_version=version, warnings=warnings)


def load_session_json(path: str) -> List[Reading]:
    """Load the readings of a session saved by any released version."""
    return load_session(path).readings
