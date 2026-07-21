"""
core/data_io.py

File I/O for the Brookfield DV1 Viscosity Logger: exporting logged readings
to Excel/CSV, and importing previously-exported CSV sessions back in.
No Qt imports here.
"""

from __future__ import annotations
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd

from core.analysis import Reading


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
]


def readings_to_dataframe(readings: List[Reading]) -> pd.DataFrame:
    rows = []
    for r in readings:
        rows.append({
            "timestamp": r.timestamp.isoformat(sep=" ", timespec="seconds"),
            "product": r.product,
            "batch": r.batch,
            "viscosity_cp": r.viscosity_cp,
            "percent_torque": r.percent_torque,
            "torque_status": r.torque_status(),
            "temperature_c": r.temperature_c,
            "rpm": r.rpm,
            "spindle": r.spindle,
            "model": r.model,
            "shear_rate_1_per_s": r.shear_rate(),
            "shear_stress_dyn_cm2": r.shear_stress(),
            "full_scale_range_cp": r.fsr(),
            "source": r.source,
            "notes": r.notes,
        })
    return pd.DataFrame(rows, columns=READING_COLUMNS)


def export_to_excel(readings: List[Reading], path: str) -> None:
    """Requires openpyxl to be installed (pip install openpyxl)."""
    df = readings_to_dataframe(readings)
    df.to_excel(path, index=False, sheet_name="DV1 Readings")


def export_to_csv(readings: List[Reading], path: str) -> None:
    df = readings_to_dataframe(readings)
    df.to_csv(path, index=False)


def import_from_csv(path: str) -> pd.DataFrame:
    """
    Import a previously-exported CSV (or a compatible one) as a raw DataFrame
    for viewing/plotting. Does not reconstruct Reading objects since imported
    data is treated as read-only reference data, not an editable session.
    """
    return pd.read_csv(path)


def save_session_json(readings: List[Reading], path: str) -> None:
    """
    Save the in-progress session (full Reading objects, editable/resumable)
    as JSON -- unlike the CSV/Excel export, this round-trips exactly via
    load_session_json() so you can close the app and pick a session back up.
    """
    payload = []
    for r in readings:
        payload.append({
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
        })
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def load_session_json(path: str) -> List[Reading]:
    """Load a session previously saved with save_session_json()."""
    with open(path, "r") as f:
        payload = json.load(f)
    readings = []
    for row in payload:
        readings.append(Reading(
            timestamp=datetime.fromisoformat(row["timestamp"]),
            viscosity_cp=row.get("viscosity_cp"),
            percent_torque=row.get("percent_torque"),
            temperature_c=row.get("temperature_c"),
            rpm=row.get("rpm"),
            spindle=row.get("spindle"),
            model=row.get("model"),
            source=row.get("source", "manual"),
            notes=row.get("notes", ""),
            product=row.get("product", ""),
            batch=row.get("batch", ""),
        ))
    return readings
