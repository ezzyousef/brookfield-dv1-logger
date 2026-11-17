"""Regression tests for the independent Codex review of the 2.1.0 upgrade
(AI_Engineering_Knowledge_Base/reports/codex/05-brookfield-upgrade-review.md).
Each test uses the reviewer's concrete input."""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import openpyxl
import pytest

from core.analysis import Reading
from core.data_io import (ImportError_, SessionError, export_to_csv, guard_text, load_session, readings_from_csv,
                          readings_to_dataframe, unguard_text)
from core.figures import excel_report, model_rows
from core.rheology import FlowData, fit_model
from core.serial_interface import RawSerialLink, WriteNotAuthorized
from labkit.excel import write_workbook

from conftest import make_readings, pump
from test_instruments import FakeSerial


# ----------------------------------------------------------------------------- 1 (medium): DV1 sending refused
@pytest.mark.parametrize("instrument,reason,description", [
    ("Brookfield DV1", "my notes", "USB Serial Port"),
    ("thermometer", "DV1 manual section 3", "USB Serial Port"),
    ("thermometer", "manual rev B", "Brookfield DV1 USB"),
    ("", "manual rev B", "USB Serial Port"),                      # no instrument named: refused too
])
def test_sending_to_a_dv1_connection_is_refused(instrument, reason, description):
    link = RawSerialLink("COM7", serial_factory=FakeSerial, description=description)
    link.open()
    with pytest.raises(WriteNotAuthorized):
        link.authorize_writes(reason, instrument=instrument)
    with pytest.raises(WriteNotAuthorized):
        link.write_raw(b"R\r\n")
    assert FakeSerial.instances[-1].written == b""


def test_sending_to_a_named_non_dv1_instrument_still_works():
    link = RawSerialLink("COM7", serial_factory=FakeSerial, description="USB Serial Port")
    link.open()
    link.authorize_writes("Bath manual rev B, section 4", instrument="Example bath controller")
    link.write_raw(b"T?\r\n")
    assert FakeSerial.instances[-1].written == b"T?\r\n"


def test_terminal_refuses_dv1_in_the_window(window, qapp, monkeypatch):
    import ui.main_window as mw
    from core.serial_interface import RawSerialLink as Real
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(mw, "RawSerialLink", lambda port, baudrate=9600, timeout=1.0, description="":
                        Real(port, baudrate, timeout, serial_factory=FakeSerial, description=description))
    window.port_combo.clear()
    window.port_combo.addItem("COM9 - USB Serial Port", userData="COM9")
    window._toggle_serial_connection()
    window.go_to("serial")
    pump(qapp)
    answers = iter([("Brookfield DV1", True), ("anything", True)])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: next(answers)))
    window._authorize_sending()
    assert not window.serial_link.writes_authorized
    window.terminal_input.setText("R")
    window._send_terminal_line()
    assert FakeSerial.instances[-1].written == b""


# ----------------------------------------------------------------------------- 2 (high): HB intervals
def test_ill_conditioned_herschel_bulkley_does_not_crash():
    g = np.geomspace(1, 100, 8)
    eta = 1000 / g * np.array([1, 1.01, .99, 1.01, .99, 1, 1.01, .99])
    fit = fit_model("herschel_bulkley", FlowData(g, eta))
    assert fit.supported
    unresolved = [p for p in fit.params if p.ci_low is None]
    assert unresolved and all(p.note for p in unresolved)
    rows = model_rows([])                                   # the export path must not crash either
    assert isinstance(rows, list)


def test_ill_conditioned_fit_survives_the_excel_report(tmp_path):
    g = np.geomspace(1, 100, 8)
    eta = 1000 / g * np.array([1, 1.01, .99, 1.01, .99, 1, 1.01, .99])
    t0 = datetime(2026, 1, 1)
    # SC4-18: shear rate = 1.32 * rpm, so rpm = g / 1.32
    rs = [Reading(t0, float(e), 50.0, rpm=float(x / 1.32), spindle="SC4-18", model="DV1MLV") for x, e in zip(g, eta)]
    write_workbook(excel_report(rs, version="t"), tmp_path / "x.xlsx")


# ----------------------------------------------------------------------------- 3 (high): formula guard
def test_every_exported_text_cell_is_guarded(tmp_path):
    r = make_readings()[0]
    r.source, r.spindle, r.model = "=1+1", "=SPINDLE()", "@MODEL"
    r.qc_flags = ["=FLAG()"]
    r.notes = "-1+2"
    frame = readings_to_dataframe([r])
    for col in ("source", "spindle", "model", "qc_flags", "notes", "source_label"):
        value = str(frame[col][0])
        assert not value.startswith(("=", "+", "@", "-")), (col, value)
    path = write_workbook(excel_report([r], version="t"), tmp_path / "g.xlsx")
    book = openpyxl.load_workbook(path)
    assert not [c.coordinate for ws in book for row in ws.iter_rows() for c in row if c.data_type == "f"]


@pytest.mark.parametrize("text,guarded", [("-1+2", True), ("-5", False), ("+3.5e2", False), ("-.5", False),
                                          ("-5 °C start", True), ("=A1", True), ("plain", False)])
def test_only_complete_numbers_skip_the_guard(text, guarded):
    assert (guard_text(text) != text) is guarded
    assert unguard_text(guard_text(text)) == text


# ----------------------------------------------------------------------------- medium: short rows, duplicates
def test_short_rows_are_refused(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("timestamp,viscosity_cp,percent_torque,rpm\n2026-01-01,50,10\n", encoding="utf-8")
    with pytest.raises(ImportError_, match="(?i)line 2"):
        readings_from_csv(str(p))


def test_explicit_empty_fields_are_accepted(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("timestamp,viscosity_cp,percent_torque,rpm\n2026-01-01,50,10,\n", encoding="utf-8")
    assert readings_from_csv(str(p))[0][0].rpm is None


def test_duplicate_column_names_are_refused(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("timestamp,viscosity_cp,viscosity_cp\n2026-01-01,100,200\n", encoding="utf-8")
    with pytest.raises(ImportError_, match="viscosity_cp"):
        readings_from_csv(str(p))


# ----------------------------------------------------------------------------- medium: reversible text
@pytest.mark.parametrize("note", ["  sample  ", "'=1+1", "'quoted", "''", "=1+1", "-cmd"])
def test_note_text_round_trips_exactly(tmp_path, note):
    readings = make_readings()
    readings[0].notes = note
    p = tmp_path / "n.csv"
    export_to_csv(readings, str(p))
    assert readings_from_csv(str(p))[0][0].notes == note


# ----------------------------------------------------------------------------- medium: fit warnings exported
def test_fit_warnings_are_exported_with_the_parameters():
    rows = model_rows(make_readings())                    # pure power law: HB yield stress unresolved
    texts = " ".join(str(c) for row in rows for c in row)
    assert "not resolved" in texts and "Herschel" in texts


# ----------------------------------------------------------------------------- medium: notebook validation
@pytest.mark.parametrize("notebook,needle", [
    ({"checklist": []}, "checklist"),
    ({"checklist": {"a": "yes"}}, "checklist"),
    ({"calibration_interval_months": "12"}, "calibration_interval_months"),
    ({"calibration_interval_months": -1}, "calibration_interval_months"),
    ({"target_temperature_c": "25"}, "target_temperature_c"),
    ({"target_temperature_c": float("nan")}, "target_temperature_c"),
    ({"temperature_tolerance_c": 0}, "temperature_tolerance_c"),
    ({"operator": 5}, "operator"),
])
def test_bad_notebook_values_are_refused(tmp_path, notebook, needle):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"format": "brookfield-dv1-logger-session", "format_version": 2,
                             "readings": [], "notebook": notebook}), encoding="utf-8")
    with pytest.raises(SessionError, match=needle):
        load_session(str(p))


# ----------------------------------------------------------------------------- low: untraceable constant
def test_untraceable_torque_constant_is_withheld():
    import core.analysis as A
    assert not hasattr(A, "torque_dyne_cm") and not hasattr(A, "RV_FULL_SCALE_TORQUE_DYNE_CM")
