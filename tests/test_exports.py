"""The shared figures, the Origin workbook and the Excel report — no display, no Origin."""
from __future__ import annotations

import openpyxl
import pytest

from core.figures import (PLOT_KINDS, build_figure, excel_report, interpret_flow_index, origin_book,
                          summary_results)
from labkit.excel import write_workbook
from labkit.figure import render, resolve_styles
from labkit.origin import _book_columns, write_labtalk_package

from conftest import make_readings


def test_every_plot_kind_has_data(readings):
    for kind in PLOT_KINDS:
        spec = build_figure(kind, readings)
        assert not spec.is_empty, kind
        for theme in ("light", "dark"):
            assert render(spec, theme=theme).axes


def test_no_readings_gives_empty_figures():
    assert all(build_figure(kind, []).is_empty for kind in PLOT_KINDS)


def test_shear_plot_is_log_log_with_a_fit_in_the_data_colour(readings):
    spec = build_figure("viscosity_shear", readings)
    assert spec.effective_scale("x") == "log" and spec.effective_scale("y") == "log"
    assert [s.role for s in spec.series] == ["data", "fit"]
    styles = resolve_styles(spec)
    assert styles[0].colour == styles[1].colour
    assert "n = 0.620" in spec.series[1].label


def test_shear_plot_is_empty_without_a_shear_rate_constant():
    assert build_figure("viscosity_shear", make_readings(spindle="RV1")).is_empty


def test_torque_plot_marks_the_recommended_window(readings):
    guides = [s for s in build_figure("torque_time", readings).series if s.role == "guide"]
    assert sorted(float(g.y[0]) for g in guides) == [10.0, 100.0]


def test_summary_results_carry_the_fit_and_its_meaning(readings):
    rows = {r[0]: r for r in summary_results(readings)}
    assert rows["Flow behaviour index n"][1] == pytest.approx(0.62)
    assert "shear-thinning" in rows["Flow behaviour index n"][3]
    assert rows["Readings logged"][1] == 6
    assert interpret_flow_index(1.0) == "approximately Newtonian"
    assert interpret_flow_index(1.3).startswith("shear-thickening")


def test_origin_book_has_a_column_pair_per_trace_and_the_readings_table(readings):
    book = origin_book(readings)
    assert len(book.figures) == 4
    columns, plots = _book_columns(book)
    traces = sum(len(f.drawable) for f in book.figures)
    assert sum(len(p) for p in plots) == traces
    assert sum(c.kind == "n" for c in columns) >= len(book.table)


def test_labtalk_package_writes_every_graph(readings, tmp_path):
    result = write_labtalk_package([origin_book(readings)], tmp_path, project_name="DV1")
    assert result.graphs == 4
    script = (tmp_path / "AeroLab_build.ogs").read_text(encoding="utf-8")
    assert "Torque (%)" in script and "%%" not in script


def test_excel_report_has_charts_results_and_readings(readings, tmp_path):
    path = write_workbook(excel_report(readings, version="2.0.0", project="Gel B1",
                                       author="Ezzeldien Yousef", settings={"Spindle": "SC4-18"}),
                          tmp_path / "gel.xlsx")
    book = openpyxl.load_workbook(path)
    assert {"Summary", "Charts", "Provenance"} <= set(book.sheetnames)
    assert len(book["Charts"]._charts) == 4
    text = " ".join(str(c.value) for ws in book for row in ws.iter_rows() for c in row if c.value is not None)
    for needle in ("Flow behaviour index n", "SC4-18", "Ezzeldien Yousef", "M14-023-A0416"):
        assert needle in text, needle
