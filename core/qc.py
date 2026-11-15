"""Automatic quality-control flags for a reading. No Qt.

Each flag is a short sentence stored on the reading (Reading.qc_flags) at the moment it is
logged, so it travels with every export. The thresholds marked "app heuristic" are choices of
this application, not Brookfield specifications; the 10-100 % torque window is Brookfield's.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.analysis import VALID_SPEEDS_RPM, Reading, full_scale_range_cp, viscosity_from_torque_cp
from core.session import ExperimentNotebook

CONSISTENCY_REL_TOL = 0.02        # app heuristic: 2 % ...
CONSISTENCY_FSR_TOL = 0.001       # ... or 0.1 % of full scale (one torque display step), whichever is larger


def qc_flags(reading: Reading, previous: Optional[Reading] = None,
             notebook: Optional[ExperimentNotebook] = None, *, due_at: Optional[datetime] = None,
             late_after_s: float = 30.0) -> list[str]:
    flags = []
    t = reading.percent_torque
    if t is not None:
        if t < 10:
            flags.append("torque below 10 %")
        elif t > 100:
            flags.append("torque above 100 %")
    if reading.viscosity_cp is not None and t is not None and reading.model and reading.spindle and reading.rpm:
        expected = viscosity_from_torque_cp(reading.model, reading.spindle, reading.rpm, t)
        fsr = full_scale_range_cp(reading.model, reading.spindle, reading.rpm)
        if expected is not None and fsr:
            tol = max(CONSISTENCY_REL_TOL * abs(expected), CONSISTENCY_FSR_TOL * fsr)
            if abs(reading.viscosity_cp - expected) > tol:
                flags.append(f"viscosity does not match torque × full-scale range (expected {expected:.4g} cP); "
                             "check the transcription, model and spindle")
    if reading.rpm is not None and reading.rpm > 0 and not any(abs(reading.rpm - v) < 1e-9 for v in VALID_SPEEDS_RPM):
        flags.append(f"speed {reading.rpm:g} rpm is not in the DV1 speed list")
    if notebook is not None and notebook.target_temperature_c is not None:
        if reading.temperature_c is None:
            flags.append("temperature not recorded")
        elif abs(reading.temperature_c - notebook.target_temperature_c) > notebook.temperature_tolerance_c:
            flags.append(f"temperature {reading.temperature_c:g} °C outside {notebook.target_temperature_c:g} "
                         f"± {notebook.temperature_tolerance_c:g} °C")
    if notebook is not None and notebook.calibration_status(reading.timestamp.date())[0] == "due":
        flags.append("instrument calibration overdue")
    if due_at is not None:
        late = (reading.timestamp - due_at).total_seconds()
        if late > late_after_s:
            flags.append(f"entered {late:.0f} s after it was due")
    if previous is not None and reading.viscosity_cp is not None and all(
            getattr(previous, a) == getattr(reading, a)
            for a in ("viscosity_cp", "percent_torque", "temperature_c", "rpm", "spindle")):
        flags.append("identical to the previous reading (double entry?)")
    return flags
