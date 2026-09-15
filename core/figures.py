"""The logged readings as figures, an Origin workbook and an Excel report.

One place builds every plot the application shows, so the Plots page, the Dashboard's
live plot, the OriginLab export and the Excel charts are the same figures by construction.
No Qt imports: this module is exercised directly by the tests.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from core.analysis import Reading, power_law_fit, summarize
from core.data_io import READING_COLUMNS, readings_to_dataframe
from labkit.excel import ExcelAnalysis, ExcelReport
from labkit.figure import FigureSpec
from labkit.origin import OriginBook

APP_NAME = "Brookfield DV1 Viscosity Logger"

PLOT_KINDS = ("viscosity_time", "viscosity_shear", "torque_time", "temperature_time")
PLOT_TITLES = {
    "viscosity_time": "Viscosity vs Time",
    "viscosity_shear": "Viscosity vs Shear Rate",
    "torque_time": "% Torque vs Time",
    "temperature_time": "Temperature vs Time",
}


def _label(readings: Sequence[Reading]) -> str:
    """The trace label: the product and batch when they were recorded."""
    if not readings:
        return "Readings"
    first = readings[0]
    parts = [p for p in (first.product, first.batch) if p]
    return " · ".join(parts) if parts else "Readings"


def _elapsed_minutes(readings: Sequence[Reading]) -> np.ndarray:
    t0 = readings[0].timestamp
    return np.array([(r.timestamp - t0).total_seconds() / 60.0 for r in readings], dtype=float)


def _values(readings: Sequence[Reading], attr: str) -> np.ndarray:
    return np.array([np.nan if getattr(r, attr) is None else float(getattr(r, attr))
                     for r in readings], dtype=float)


def build_figure(kind: str, readings: Sequence[Reading]) -> FigureSpec:
    """One of the four plots. An empty FigureSpec (no drawable series) when there is no data."""
    title = PLOT_TITLES[kind]
    label = _label(readings)

    if kind == "viscosity_shear":
        spec = FigureSpec(title, "Shear rate", "Viscosity", x_unit="s⁻¹", y_unit="cP",
                          xscale="log", yscale="log", name=kind,
                          note="Only spindles with a Shear Rate Constant give a shear rate.")
        pts = sorted((r.shear_rate(), r.viscosity_cp) for r in readings
                     if r.shear_rate() is not None and r.viscosity_cp is not None)
        if pts:
            xs = np.array([p[0] for p in pts], dtype=float)
            ys = np.array([p[1] for p in pts], dtype=float)
            spec.add(label, xs, ys, style="scatter")
            fit = power_law_fit(list(readings))
            positive = xs[xs > 0]
            if fit is not None and positive.size >= 2:
                grid = np.logspace(np.log10(positive.min()), np.log10(positive.max()), 80)
                spec.add(f"Power law (n = {fit['n']:.3f})", grid, fit["k"] * grid ** (fit["n"] - 1.0),
                         role="fit", parent=label)
        return spec

    y_attr, y_label, y_unit = {
        "viscosity_time": ("viscosity_cp", "Viscosity", "cP"),
        "torque_time": ("percent_torque", "Torque", "%"),
        "temperature_time": ("temperature_c", "Temperature", "°C"),
    }[kind]
    spec = FigureSpec(title, "Elapsed time", y_label, x_unit="min", y_unit=y_unit, name=kind)
    if readings:
        spec.add(label, _elapsed_minutes(readings), _values(readings, y_attr), style="scatter+line")
    if kind == "torque_time" and readings:
        t = _elapsed_minutes(readings)
        span = np.array([t.min(), t.max()]) if t.size else np.array([0.0, 1.0])
        spec.add("10 % (lower limit)", span, [10, 10], role="guide")
        spec.add("100 % (upper limit)", span, [100, 100], role="guide")
    return spec


def all_figures(readings: Sequence[Reading]) -> list[FigureSpec]:
    return [build_figure(kind, readings) for kind in PLOT_KINDS]


def summary_results(readings: Sequence[Reading]) -> list[tuple]:
    """(quantity, value, unit, note) rows: descriptive statistics, torque flags, power-law fit."""
    summary = summarize(list(readings))
    rows: list[tuple] = [("Readings logged", summary["n_total"], "", "")]
    for attr, name, unit in (("viscosity_cp", "Viscosity", "cP"), ("percent_torque", "Torque", "%"),
                             ("temperature_c", "Temperature", "°C"), ("rpm", "Speed", "rpm")):
        s = summary[attr]
        if s is None:
            continue
        rows += [(f"{name} mean", s["mean"], unit, f"n = {s['n']}"),
                 (f"{name} standard deviation", s["stdev"], unit, "population"),
                 (f"{name} minimum", s["min"], unit, ""),
                 (f"{name} maximum", s["max"], unit, "")]
    rows += [("Readings below 10 % torque", summary["n_below_10pct_torque"], "",
              "accuracy not guaranteed below 10 %"),
             ("Readings above 100 % torque", summary["n_above_100pct_torque"], "", "out of range")]
    fit = power_law_fit(list(readings))
    if fit is not None:
        rows += [("Flow behaviour index n", fit["n"], "-", interpret_flow_index(fit["n"])),
                 ("Consistency index K", fit["k"], "cP·sⁿ⁻¹", "apparent viscosity = K·γ̇ⁿ⁻¹"),
                 ("Power-law fit R²", fit["r_squared"], "-", f"{fit['n_points']} points")]
    return rows


def interpret_flow_index(n: float) -> str:
    if n < 0.95:
        return "shear-thinning (pseudoplastic) — typical of polymer solutions and gels"
    if n > 1.05:
        return "shear-thickening (dilatant)"
    return "approximately Newtonian"


def origin_book(readings: Sequence[Reading], name: str = "DV1 readings") -> OriginBook:
    frame = readings_to_dataframe(list(readings))
    table = {col: frame[col].tolist() for col in READING_COLUMNS}
    return OriginBook(name, figures=[f for f in all_figures(readings) if not f.is_empty],
                      table=table, results=[r[:3] for r in summary_results(readings)],
                      note=f"{APP_NAME} — {len(readings)} reading(s)")


def excel_report(readings: Sequence[Reading], *, version: str, project: str = "DV1 session",
                 author: str = "", settings: dict | None = None) -> ExcelReport:
    frame = readings_to_dataframe(list(readings))
    analysis = ExcelAnalysis(
        title=project, group="Viscosity readings", results=summary_results(readings),
        figures=[f for f in all_figures(readings) if not f.is_empty],
        table={col: frame[col].tolist() for col in READING_COLUMNS},
        settings=settings or {})
    return ExcelReport(APP_NAME, version, project=project, author=author, analyses=[analysis],
                       extra_provenance={"Method": "Brookfield DV1 Operating Instructions "
                                                   "M14-023-A0416, Appendix D"})
