"""2.1.0 window features, offscreen: keyboard entry, QC flags, notebook and audit, comparison,
flow models, instrument sources, the serial write barrier, recovery and export preview."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from conftest import make_readings, pump
from test_instruments import FakeSerial

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_shear_sweep.json"


@pytest.fixture
def errors(monkeypatch):
    shown = []
    import ui.main_window as mw
    monkeypatch.setattr(mw, "show_error", lambda parent, summary, exc=None, **k: shown.append((summary, str(exc))))
    return shown


def _seed(window, readings):
    window.readings.extend(readings)
    window.history.record("seed")
    window._on_readings_changed()


def _type(window, viscosity="", torque="", temp=""):
    window.in_viscosity.setText(viscosity)
    window.in_torque.setText(torque)
    window.in_temp.setText(temp)
    window._add_manual_reading()


# ----------------------------------------------------------------------------- entry
@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "1e999"])
def test_non_finite_numbers_are_rejected(window, text):
    _type(window, viscosity=text, torque="40")
    assert window.readings == []
    assert "valid number" in window.dialogs[-1][1]


def test_negative_viscosity_and_empty_entry_are_rejected(window):
    _type(window, viscosity="-5", torque="40")
    _type(window)
    assert window.readings == []


def test_keyboard_first_entry_with_enter(window, qapp):
    window.go_to("dashboard")
    window.activateWindow()
    window.in_viscosity.setFocus()
    QTest.keyClicks(window.in_viscosity, "1500")
    moved = []
    window.in_viscosity.returnPressed.connect(lambda: moved.append("torque"))
    window.in_torque.returnPressed.connect(lambda: moved.append("temp"))
    QTest.keyClick(window.in_viscosity, Qt.Key_Enter, Qt.KeypadModifier)          # numpad Enter
    QTest.keyClicks(window.in_torque, "45")
    QTest.keyClick(window.in_torque, Qt.Key_Return)
    assert moved == ["torque", "temp"]          # (offscreen windows never hold real focus)
    QTest.keyClicks(window.in_temp, "23.5")
    QTest.keyClick(window.in_temp, Qt.Key_Enter, Qt.KeypadModifier)
    assert len(window.readings) == 1
    r = window.readings[0]
    assert (r.viscosity_cp, r.percent_torque, r.temperature_c) == (1500.0, 45.0, 23.5)
    assert r.source == "manual" and r.source_label() == "manually transcribed"


def test_transcription_mismatch_is_flagged_and_shown(window):
    window.in_model.setCurrentText("DV1MLV")
    window.in_spindle.setCurrentText("LV1")
    window.in_rpm.setCurrentText("60.0")
    _type(window, "55", "50", "25")                 # 50 % of FSR 100 cP is 50 cP, not 55
    r = window.readings[0]
    assert any("expected 50 cP" in f for f in r.qc_flags)
    col = window.table_model.COLUMNS.index("QC flags")
    assert "expected 50 cP" in window.table_model.data(window.table_model.index(0, col))
    src = window.table_model.COLUMNS.index("Source")
    assert window.table_model.data(window.table_model.index(0, src)) == "manually transcribed"
    assert any(a.action == "add" and "flags" in a.detail for a in window.audit)


def test_late_entry_after_a_due_reminder_is_flagged(window):
    from datetime import datetime, timedelta
    window.run_due_at = datetime.now() - timedelta(seconds=120)
    _type(window, "100", "40")
    assert any("after it was due" in f for f in window.readings[0].qc_flags)
    assert window.run_due_at is None


def test_sample_queue_advances(window):
    window.queue_edit.setPlainText("S-1\nS-2\n\nS-3\n")
    window._next_sample()
    assert window.in_sample_id.text() == "S-1"
    window._next_sample()
    window._next_sample()
    assert window.in_sample_id.text() == "S-3"
    window._next_sample()
    assert window.in_sample_id.text() == "S-1"
    _type(window, "100", "40")
    assert window.readings[0].sample_id == "S-1"


def test_large_controls_and_high_contrast(window):
    window._toggle_large_controls()
    assert window.act_large.isChecked() and "44px" in window.in_viscosity.styleSheet()
    window._toggle_high_contrast()
    assert window.act_contrast.isChecked() and "background" in window.big_readout.styleSheet()
    window._toggle_large_controls()
    assert window.in_viscosity.styleSheet() == ""
    assert window.shortcut_conflicts() == []


def test_constants_shown_for_the_selected_spindle(window):
    window.in_model.setCurrentText("DV1MLV")
    window.in_spindle.setCurrentText("SC4-18")
    text = window.constants_label.text()
    assert "TK 0.09375" in text and "SMC 3.2" in text and "SRC 1.32" in text and "M14-023-A0416" in text


# ----------------------------------------------------------------------------- notebook, sessions
def test_notebook_checklist_and_audit_round_trip_through_a_session(window, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    window.go_to("notebook")
    pump(qapp)
    window.nb_fields["instrument_id"].setText("DV1-EML-01")
    window.nb_fields["instrument_id"].editingFinished.emit()
    window.nb_fields["calibration_date"].setText("2020-01-01")
    window.nb_fields["calibration_date"].editingFinished.emit()
    window.nb_target.setText("25")
    window.nb_target.editingFinished.emit()
    first = next(iter(window.nb_checks))
    window.nb_checks[first].setChecked(True)
    assert window.nb_calibration.text() == "Calibration overdue"
    _type(window, "100", "40", "27")
    flags = window.readings[0].qc_flags
    assert "instrument calibration overdue" in flags and any("outside 25" in f for f in flags)
    assert window.audit_table.rowCount() >= 4
    path = tmp_path / "s.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), "")))
    window._save_session()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format_version"] == 2 and data["notebook"]["instrument_id"] == "DV1-EML-01"
    window._clear_session()
    window.notebook.instrument_id = "changed"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    window._load_session()
    assert window.notebook.instrument_id == "DV1-EML-01"
    assert window.nb_fields["instrument_id"].text() == "DV1-EML-01"
    assert window.notebook.checklist[first] is True
    assert any(a.action == "checklist" for a in window.audit)


def test_loading_a_2_0_0_session_shows_its_note(window, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    fixture = Path(__file__).resolve().parent / "fixtures" / "session_v1_app_2_0_0.json"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(fixture), "")))
    window._load_session()
    assert len(window.readings) == 3
    assert any("version 1" in text for _title, text in window.dialogs)


def test_corrupt_session_is_refused_and_nothing_changes(window, tmp_path, monkeypatch, errors):
    from PySide6.QtWidgets import QFileDialog
    _seed(window, make_readings())
    bad = tmp_path / "bad.json"
    bad.write_text('[{"timestamp": "2026-01-01T12:00:00", "viscosity_cp": "ten"}]', encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    window._load_session()
    assert len(window.readings) == 6
    assert errors and "viscosity_cp" in errors[-1][1]


def test_csv_import_and_ragged_csv_refusal(window, tmp_path, monkeypatch, errors):
    from PySide6.QtWidgets import QFileDialog
    from core.data_io import export_to_csv
    good = tmp_path / "g.csv"
    export_to_csv(make_readings(), str(good))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(good), "")))
    window._import_csv()
    assert len(window.readings) == 6
    bad = tmp_path / "b.csv"
    bad.write_text("timestamp,viscosity_cp\n2026-01-01 12:00:00,1,2\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    window._import_csv()
    assert len(window.readings) == 6 and "Line 2" in errors[-1][1]


def test_csv_export_preview_provenance_and_revision(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog
    from ui.pages import ExportPreviewDialog
    _seed(window, make_readings())
    seen = {}

    def accept(dialog):
        seen["rows"] = dialog.table.rowCount()
        seen["summary"] = dialog.summary.text()
        return QDialog.Accepted
    monkeypatch.setattr(ExportPreviewDialog, "exec", accept)
    path = tmp_path / "out.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(path), "")))
    window._export_csv()
    assert seen["rows"] == 6 and "revision 1" in seen["summary"]
    prov = json.loads(Path(str(path) + ".provenance.json").read_text(encoding="utf-8"))
    assert prov["parameters"]["Export revision"] == "1"
    assert "manually transcribed: 6" in prov["parameters"]["Readings by source"]
    assert window.export_revision == 1


def test_cancelled_preview_writes_nothing(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog
    from ui.pages import ExportPreviewDialog
    _seed(window, make_readings())
    monkeypatch.setattr(ExportPreviewDialog, "exec", lambda d: QDialog.Rejected)
    called = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: called.append(1) or ("", "")))
    window._export_csv()
    assert called == [] and window.export_revision == 0


def test_excel_export_is_a_new_revision_with_the_notebook(window):
    _seed(window, make_readings())
    window.notebook.instrument_id = "DV1-EML-01"
    report = window._excel_report_for_export()
    assert report.extra_provenance["Instrument ID"] == "DV1-EML-01"
    assert report.extra_provenance["Export revision"] == "1"
    assert window._excel_report_for_export().extra_provenance["Export revision"] == "2"


# ----------------------------------------------------------------------------- analysis pages
def test_compare_page_lists_replicates_and_hysteresis(window, qapp):
    from core.data_io import load_session
    _seed(window, load_session(str(EXAMPLE)).readings)
    window.go_to("compare")
    pump(qapp)
    assert window.compare_table.rowCount() == 5          # 5 speeds, 4 measured twice (up and down)
    assert window.hysteresis_table.rowCount() == 1
    assert window.compare_canvas.spec is not None


def test_statistics_page_ranks_the_flow_models(window, qapp):
    _seed(window, make_readings())
    window.go_to("stats")
    pump(qapp)
    texts = [window.models_table.item(r, 0).text() for r in range(window.models_table.rowCount())]
    assert window.models_table.rowCount() == 6
    assert texts[0].startswith("Power law")                         # exact power-law data
    status = [window.models_table.item(r, 1).text() for r in range(6)]
    assert "not fitted" in status                                   # Cross/Carreau: no plateau


# ----------------------------------------------------------------------------- instruments
@pytest.fixture
def fake_port(window, monkeypatch):
    import ui.main_window as mw
    FakeSerial.instances.clear()
    monkeypatch.setattr(mw, "RawSerialLink",
                        lambda port, baudrate=9600, timeout=1.0: mw.__dict__["_RealLink"](port, baudrate, timeout,
                                                                                         serial_factory=FakeSerial))
    from core.serial_interface import RawSerialLink
    mw._RealLink = RawSerialLink
    window.port_combo.clear()
    window.port_combo.addItem("COM99 - simulated", userData="COM99")
    window._toggle_serial_connection()
    assert window.serial_link is not None and window.serial_link.is_open
    return FakeSerial.instances[-1]


def test_terminal_is_read_only_until_sending_is_allowed(window, qapp, fake_port, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    window.go_to("serial")
    pump(qapp)
    assert not window.send_btn.isEnabled() and not window.terminal_input.isEnabled()
    window.terminal_input.setText("R")
    window._send_terminal_line()                                # called anyway: blocked
    assert fake_port.written == b""
    assert window.dialogs[-1][0] == "Sending is not allowed"
    fake_port.incoming = b"raw frame 1\rraw frame 2\r"
    window._toggle_auto_capture()
    window._on_capture_tick()
    window._read_terminal_now()
    assert len(window.raw_capture) == 2 and fake_port.written == b""
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Bath manual rev. B, section 4", True)))
    window._authorize_sending()
    assert window.send_btn.isEnabled()
    window.terminal_input.setText("T?")
    window._send_terminal_line()
    assert fake_port.written == b"T?\r\n"
    assert any(a.action == "serial" and "allowed" in a.detail for a in window.audit)
    window._toggle_serial_connection()                          # disconnect ends the permission
    assert not window.send_btn.isEnabled()


def test_cancelled_authorisation_keeps_the_port_read_only(window, qapp, fake_port, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    window.go_to("serial")
    pump(qapp)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", False)))
    window._authorize_sending()
    assert not window.serial_link.writes_authorized


def test_simulation_source_logs_labelled_readings_and_writes_nothing(window, qapp, fake_port):
    window.go_to("serial")
    pump(qapp)
    window.in_model.setCurrentText("DV1MLV")
    window.in_spindle.setCurrentText("SC4-18")
    window.adapter_kind.setCurrentIndex(window.adapter_kind.findData("simulation"))
    window.sim_rpms.setText("1, 5, 20")
    window._start_adapter()
    for _ in range(4):
        window._on_adapter_tick()
    assert window.adapter is None                                # finished after three speeds
    assert [r.source for r in window.readings] == ["simulated"] * 3
    assert "simulated" in window.big_readout.text()
    assert fake_port.written == b""


def test_replay_source_of_the_example(window, qapp):
    window.go_to("serial")
    pump(qapp)
    window.adapter_kind.setCurrentIndex(window.adapter_kind.findData("replay"))
    window.adapter_file.setText(str(EXAMPLE))
    window._start_adapter()
    while window.adapter is not None:
        window._on_adapter_tick()
    assert len(window.readings) == 9 and all(r.source == "replay" for r in window.readings)


def test_dv1_protocol_definition_is_refused_in_the_ui(window, qapp, fake_port, tmp_path, errors):
    window.go_to("serial")
    pump(qapp)
    p = tmp_path / "dv1.json"
    p.write_text(json.dumps({"name": "guess", "instrument": "Brookfield DV1", "document": "none",
                             "line_pattern": r"(?P<viscosity_cp>\d+)"}), encoding="utf-8")
    window.adapter_kind.setCurrentIndex(window.adapter_kind.findData("protocol"))
    window.adapter_file.setText(str(p))
    window._start_adapter()
    assert window.adapter is None and "Wingather" in errors[-1][1]
    assert fake_port.written == b""


# ----------------------------------------------------------------------------- recovery
def test_unsaved_session_is_offered_back_after_an_unexpected_exit(window, qapp):
    from core import recovery
    from ui.main_window import MainWindow
    _seed(window, make_readings())
    assert recovery.recovery_path().exists()
    again = MainWindow()                                         # as if the first one had crashed
    try:
        pump(qapp, 0.1)
        assert len(again.readings) == 6
        assert any(a.action == "load" and "recover" in a.detail for a in again.audit)
    finally:
        again.readings.clear()
        again.dirty = False
        again.close()


def test_saved_session_leaves_no_recovery_file_on_close(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from core import recovery
    _seed(window, make_readings())
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "s.json"), "")))
    window._save_session()
    window.close()
    assert not recovery.recovery_path().exists()


def test_close_with_unsaved_readings_can_be_cancelled(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    _seed(window, make_readings())
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    window.close()
    assert window.isVisible()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
