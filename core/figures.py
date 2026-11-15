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
from core.rheology import compare_models
from core.session import ExperimentNotebook
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


def source_counts(readings: Sequence[Reading]) -> dict[str, int]:
    """How many readings came from each source, by their plain-language label."""
    out: dict[str, int] = {}
    for r in readings:
        out[r.source_label()] = out.get(r.source_label(), 0) + 1
    return out


def model_rows(readings: Sequence[Reading]) -> list[tuple]:
    """(quantity, value, unit, note) rows for every model the data support, ranked by AICc."""
    comparison = compare_models(list(readings))
    rows: list[tuple] = []
    for fit in sorted(comparison.fits, key=lambda f: (not f.supported, f.aicc if f.supported else 0)):
        if not fit.supported:
            rows.append((f"{fit.model.title}: not fitted", "", "", fit.reason))
            continue
        rows.append((f"{fit.model.title} ΔAICc", fit.delta_aicc, "-",
                     f"{fit.model.equation}; RMS misfit {fit.rms_pct:.3g} %; {fit.n_points} points"))
        for p in fit.params:
            ci = (f"95 % CI {p.ci_low:.4g} … {p.ci_high:.4g}" if p.ci_low is not None else (p.note or "no interval"))
            rows.append((f"{fit.model.title} {p.name}", p.value, p.unit, ci))
    for w in comparison.warnings:
        rows.append(("Note", "", "", w))
    return rows


def provenance_fields(notebook: ExperimentNotebook | None, readings: Sequence[Reading],
                      revision: int | None = None) -> dict[str, str]:
    nb = notebook or ExperimentNotebook()
    out = {"Method": "Brookfield DV1 Operating Instructions M14-023-A0416, Appendix D",
           "Readings by source": "; ".join(f"{k}: {v}" for k, v in source_counts(readings).items()) or "none",
           "Standards note": "Traceability fields are recorded as entered; no standards compliance is claimed."}
    for label, value in (("Experiment", nb.title), ("Instrument ID", nb.instrument_id),
                         ("Instrument serial", nb.instrument_serial), ("Calibration date", nb.calibration_date),
                         ("Calibration reference", nb.calibration_reference), ("Operator", nb.operator),
                         ("Protocol", nb.protocol), ("Sample preparation", nb.sample_preparation),
                         ("Target temperature (°C)", "" if nb.target_temperature_c is None
                          else f"{nb.target_temperature_c:g} ± {nb.temperature_tolerance_c:g}"),
                         ("Notebook notes", nb.notes)):
        if value:
            out[label] = str(value)
    if nb.checklist:
        done = sum(1 for v in nb.checklist.values() if v)
        out["Measurement checklist"] = f"{done} of {len(nb.checklist)} items ticked"
    if revision is not None:
        out["Export revision"] = str(revision)
    return out


def origin_book(readings: Sequence[Reading], name: str = "DV1 readings") -> OriginBook:
    frame = readings_to_dataframe(list(readings))
    table = {col: frame[col].tolist() for col in READING_COLUMNS}
    return OriginBook(name, figures=[f for f in all_figures(readings) if not f.is_empty],
                      table=table, results=[r[:3] for r in summary_results(readings)],
                      note=f"{APP_NAME} — {len(readings)} reading(s)")


def excel_report(readings: Sequence[Reading], *, version: str, project: str = "DV1 session",
                 author: str = "", settings: dict | None = None,
                 notebook: ExperimentNotebook | None = None, revision: int | None = None) -> ExcelReport:
    frame = readings_to_dataframe(list(readings))
    analysis = ExcelAnalysis(
        title=project, group="Viscosity readings", results=summary_results(readings) + model_rows(readings),
        figures=[f for f in all_figures(readings) if not f.is_empty],
        table={col: frame[col].tolist() for col in READING_COLUMNS},
        settings=settings or {})
    return ExcelReport(APP_NAME, version, project=project, author=author, analyses=[analysis],
                       extra_provenance=provenance_fields(notebook, readings, revision))


def comparison_figure(readings: Sequence[Reading]) -> FigureSpec:
    """Flow curves of every sample on one log-log plot (mean viscosity at each shear rate)."""
    from core.compare import samples
    spec = FigureSpec("Flow curves by sample", "Shear rate", "Viscosity", x_unit="s⁻¹", y_unit="cP",
                      xscale="log", yscale="log", name="compare_flow",
                      note="Mean of replicates at each speed; spindles with a shear-rate constant only.")
    for label, rs in samples(readings).items():
        by_rate: dict[float, list[float]] = {}
        for r in rs:
            rate = r.shear_rate()
            if rate and r.viscosity_cp:
                by_rate.setdefault(rate, []).append(r.viscosity_cp)
        if len(by_rate) >= 1:
            xs = np.array(sorted(by_rate), dtype=float)
            ys = np.array([float(np.mean(by_rate[x])) for x in xs], dtype=float)
            spec.add(label, xs, ys, style="scatter+line")
    return spec
