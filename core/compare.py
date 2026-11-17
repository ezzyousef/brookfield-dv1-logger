"""Sample comparison: replicate statistics, flow curves per sample, and hysteresis loops. No Qt.

Replicates are readings of the same sample at the same spindle and speed. Their spread is
reported as the sample standard deviation (n - 1), the coefficient of variation, the standard
uncertainty of the mean u = s / sqrt(n), and an expanded 95 % interval t(0.975, n - 1) * u.
This is the Type A (statistical) component only; calibration and instrument uncertainty are
not included.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from statistics import mean, stdev
from typing import Optional, Sequence

import numpy as np

from core.analysis import Reading
from core.rheology import PA_S_TO_CP, t_ppf


def sample_label(r: Reading) -> str:
    if r.sample_id:
        return r.sample_id
    parts = [p for p in (r.product, r.batch) if p]
    return " · ".join(parts) if parts else "(unnamed sample)"


@dataclass
class ReplicateRow:
    sample: str
    spindle: Optional[str]
    rpm: Optional[float]
    n: int
    mean_cp: float
    sd_cp: Optional[float]
    cv_pct: Optional[float]
    u_mean_cp: Optional[float]
    u95_cp: Optional[float]
    mean_temperature_c: Optional[float]


def replicate_table(readings: Sequence[Reading]) -> list[ReplicateRow]:
    groups: "OrderedDict[tuple, list[Reading]]" = OrderedDict()
    for r in readings:
        if r.viscosity_cp is None:
            continue
        groups.setdefault((sample_label(r), r.spindle, r.rpm), []).append(r)
    rows = []
    for (sample, spindle, rpm), rs in groups.items():
        v = [r.viscosity_cp for r in rs]
        temps = [r.temperature_c for r in rs if r.temperature_c is not None]
        t_mean = mean(temps) if temps else None
        n, m = len(v), mean(v)
        if n >= 2:
            sd = stdev(v)
            u = sd / math.sqrt(n)
            rows.append(ReplicateRow(sample, spindle, rpm, n, m, sd, (100.0 * sd / m) if m else None, u,
                                     t_ppf(0.975, n - 1) * u, t_mean))
        else:
            rows.append(ReplicateRow(sample, spindle, rpm, n, m, None, None, None, None, t_mean))
    return rows


def samples(readings: Sequence[Reading]) -> "OrderedDict[str, list[Reading]]":
    out: "OrderedDict[str, list[Reading]]" = OrderedDict()
    for r in readings:
        out.setdefault(sample_label(r), []).append(r)
    return out


@dataclass
class Hysteresis:
    sample: str
    up_rpm: list
    down_rpm: list
    per_speed: list                      # (rpm, eta_up, eta_down, (up - down) as % of up)
    loop_area_pa_s: Optional[float]      # integral of (tau_up - tau_down) d(gamma), Pa/s
    relative_area_pct: Optional[float]   # loop area / integral of tau_up over the same range
    note: str = ""


def _trapz(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    return float(np.sum((x[1:] - x[:-1]) * (y[1:] + y[:-1]) / 2.0))


def hysteresis(readings: Sequence[Reading], sample: str = "") -> Optional[Hysteresis]:
    """Up/down speed sweep of one sample, in time order. None when there is no down leg.

    The up leg runs to the (first) highest speed, which is the turning point shared by both legs;
    the down leg is every later reading. Speeds measured on both legs are compared. The loop area
    integrates shear stress over shear rate (trapezoid rule) on those speeds, so it needs a
    spindle with a shear-rate constant.
    """
    rs = sorted((r for r in readings if r.rpm and r.viscosity_cp is not None), key=lambda r: r.timestamp)
    if len(rs) < 3:
        return None
    top_rpm = max(r.rpm for r in rs)
    top = next(i for i, r in enumerate(rs) if r.rpm == top_rpm)
    up, down = rs[:top + 1], rs[top + 1:]
    if not down:
        return None
    up_by = {r.rpm: r for r in up}
    down_by: dict = {}
    for r in down:
        down_by.setdefault(r.rpm, r)
    common = sorted(set(up_by) & set(down_by))
    per_speed = [(rpm, up_by[rpm].viscosity_cp, down_by[rpm].viscosity_cp,
                  100.0 * (up_by[rpm].viscosity_cp - down_by[rpm].viscosity_cp) / up_by[rpm].viscosity_cp)
                 for rpm in common]
    if not per_speed:
        return None
    area = rel = None
    note = ""
    legs = sorted(set(common) | {top_rpm})   # the turning point closes the loop
    if all(up_by[c].shear_rate() for c in legs):
        g = [up_by[c].shear_rate() for c in legs]
        tau_up = [up_by[c].viscosity_cp / PA_S_TO_CP * up_by[c].shear_rate() for c in legs]
        tau_dn = [down_by.get(c, up_by[c]).viscosity_cp / PA_S_TO_CP
                  * up_by[c].shear_rate() for c in legs]
        area = _trapz(g, tau_up) - _trapz(g, tau_dn)
        base = _trapz(g, tau_up)
        rel = 100.0 * area / base if base else None
    else:
        note = "No shear-rate constant for this spindle: only the per-speed viscosity differences are given."
    return Hysteresis(sample or sample_label(rs[0]), [r.rpm for r in up], [r.rpm for r in down],
                      per_speed, area, rel, note)
