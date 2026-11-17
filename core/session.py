"""A measurement session: readings plus the experiment notebook, an audit trail and the
export revision. No Qt, no file I/O (see core/data_io.py for loading and saving).

The notebook holds traceability fields in the spirit of ISO-style lab records (instrument ID,
calibration date, protocol, operator, sample preparation, temperature set point). Recording
them does not make a measurement compliant with any standard; the app makes no such claim.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime
from typing import Optional

from core.analysis import Reading

# The questions asked before a measurement. Every item comes from docs/MANUAL.md
# (sections 1-3 and 6); none is an instrument requirement invented here.
CHECKLIST_ITEMS = (
    "Sample at the target temperature and held there",
    "Spindle immersed to the groove on its shaft",
    "No air bubbles near the spindle",
    "Container wide enough (about one spindle diameter of clearance)",
    "Guard leg fitted, if available",
    "Model and spindle selected in the app match the instrument",
    "Speed chosen so % torque will be between 10 and 100 %",
)


@dataclass
class ExperimentNotebook:
    title: str = ""
    instrument_id: str = ""
    instrument_serial: str = ""
    calibration_date: str = ""            # ISO date, as written on the calibration certificate
    calibration_reference: str = ""       # certificate number or fluid lot
    calibration_interval_months: int = 12  # the lab's own policy; not a Brookfield requirement
    operator: str = ""
    protocol: str = ""
    sample_preparation: str = ""
    target_temperature_c: Optional[float] = None
    temperature_tolerance_c: float = 1.0   # the lab's own tolerance for the QC flag
    notes: str = ""
    checklist: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentNotebook":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict:
        return asdict(self)

    def calibration_status(self, today: date | None = None) -> tuple[str, str]:
        """('ok' | 'due' | 'unknown', sentence). 'due' once the lab's interval has passed."""
        if not self.calibration_date:
            return "unknown", "No calibration date recorded."
        try:
            when = date.fromisoformat(self.calibration_date)
        except ValueError:
            return "unknown", f"Calibration date '{self.calibration_date}' is not a date (YYYY-MM-DD)."
        today = today or date.today()
        months = (today.year - when.year) * 12 + (today.month - when.month) - (today.day < when.day)
        if when > today:
            return "unknown", "The calibration date is in the future; check it."
        if self.calibration_interval_months and months >= self.calibration_interval_months:
            return "due", (f"Last calibration {self.calibration_date} is {months} month(s) ago, past the "
                           f"lab's {self.calibration_interval_months}-month interval.")
        return "ok", f"Calibrated {self.calibration_date} ({months} month(s) ago)."

    def checklist_complete(self) -> bool:
        return all(self.checklist.get(item) for item in CHECKLIST_ITEMS)


@dataclass
class AuditEntry:
    time: str        # ISO local time with offset
    action: str      # add, delete, edit, load, clear, export, notebook, undo, redo, import, recover
    detail: str = ""

    @classmethod
    def now(cls, action: str, detail: str = "") -> "AuditEntry":
        return cls(datetime.now().astimezone().isoformat(timespec="seconds"), action, detail)


@dataclass
class Session:
    readings: list[Reading] = field(default_factory=list)
    notebook: ExperimentNotebook = field(default_factory=ExperimentNotebook)
    audit: list[AuditEntry] = field(default_factory=list)
    export_revision: int = 0
    format_version: int = 2
    warnings: list[str] = field(default_factory=list)   # set when loading; never saved
