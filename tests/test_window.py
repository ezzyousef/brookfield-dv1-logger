"""The main window, offscreen: pages, manual entry, undo/redo, sessions, plots and closing."""
from __future__ import annotations

from core.data_io import save_session_json

from conftest import make_readings, pump


def _type_reading(window, viscosity="1500", torque="45", temp="23.5"):
    window.in_viscosity.setText(viscosity)
    window.in_torque.setText(torque)
    window.in_temp.setText(temp)
    window._add_manual_reading()


def _seed(window, readings):
    window.readings.extend(readings)
    window.history.record("seed")
    window._on_readings_changed()


def test_every_page_builds_in_both_themes(window, qapp):
    for key in window.page_keys:
        window.go_to(key)
        pump(qapp)
        assert window.is_page_built(key), key
    start = window.theme
    window.toggle_theme()
    pump(qapp)
    assert window.theme != start
    window.toggle_theme()


def test_no_keyboard_shortcut_is_bound_twice(window):
    assert window.shortcut_conflicts() == []
    bound = window.bound_sequences()
    for key in ("Ctrl+Z", "Ctrl+Y", "Ctrl+O", "Ctrl+S", "Ctrl+E", "F5"):
        assert key in bound, key


def test_manual_reading_undo_and_redo(window):
    _type_reading(window)
    assert len(window.readings) == 1 and window.readings[0].viscosity_cp == 1500.0
    assert window.table_model.rowCount() == 1
    assert window.in_viscosity.text() == ""
    _type_reading(window, "1600", "50")
    window.undo()
    assert [r.viscosity_cp for r in window.readings] == [1500.0]
    window.redo()
    assert [r.viscosity_cp for r in window.readings] == [1500.0, 1600.0]
    window.undo()
    window.undo()
    assert window.readings == [] and window.table_model.rowCount() == 0


def test_invalid_number_is_rejected_without_adding(window):
    _type_reading(window, viscosity="12,5x")
    assert window.readings == []
    assert window.dialogs and "not a valid number" in window.dialogs[-1][1]


def test_out_of_range_torque_warns_but_keeps_the_reading(window):
    _type_reading(window, torque="4")
    assert len(window.readings) == 1
    assert window.dialogs[-1][0] == "Torque out of recommended range"


def test_load_session_replaces_and_can_be_undone(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    _type_reading(window)
    path = tmp_path / "s.json"
    save_session_json(make_readings(), str(path))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    window._load_session()
    assert len(window.readings) == 6
    window.undo()
    assert len(window.readings) == 1


def test_delete_selected_rows_is_undoable(window, qapp):
    _seed(window, make_readings())
    window.go_to("table")
    pump(qapp)
    window.table_view.selectRow(2)
    window._delete_selected_rows()
    assert len(window.readings) == 5
    window.undo()
    assert len(window.readings) == 6


def test_clear_session_is_undoable(window):
    _seed(window, make_readings())
    window._clear_session()
    assert window.readings == []
    window.undo()
    assert len(window.readings) == 6


def test_plots_page_shows_the_power_law_fit(window, qapp):
    _seed(window, make_readings())
    window.go_to("plots")
    pump(qapp)
    window.plot_type.setCurrentIndex(window.plot_type.findData("viscosity_shear"))
    pump(qapp)
    assert window.plot_canvas.spec is not None
    assert window.plot_canvas.spec.series[1].role == "fit"


def test_plots_page_explains_a_missing_shear_rate(window, qapp):
    _seed(window, make_readings(spindle="RV1"))
    window.go_to("plots")
    pump(qapp)
    window.plot_type.setCurrentIndex(window.plot_type.findData("viscosity_shear"))
    pump(qapp)
    assert window.plot_canvas.spec is None                  # a message, not an empty plot


def test_statistics_page_lists_the_fit(window, qapp):
    _seed(window, make_readings())
    window.go_to("stats")
    pump(qapp)
    from PySide6.QtWidgets import QLabel, QTableWidget
    page = window.page("stats")
    cells = [t.item(r, c).text() for t in page.findChildren(QTableWidget)
             for r in range(t.rowCount()) for c in range(t.columnCount()) if t.item(r, c)]
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert any("Flow behaviour index" in text or "shear-thinning" in text for text in cells + labels)


def test_export_actions_warn_when_there_is_nothing_to_export(window):
    messages = []
    bar = window._export_bar()
    bar._notify = lambda text, level: messages.append(level)
    bar.export_excel()
    bar.send_to_origin()
    assert messages == ["warning", "warning"]


def test_project_name_comes_from_product_and_batch(window):
    window.in_product.setText("Alginate gel")
    window.in_batch.setText("B7")
    assert window._project_name() == "Alginate_gel_B7"


def test_settings_survive_a_restart(qapp, window):
    from ui.main_window import MainWindow

    choice = window.in_spindle.itemText(window.in_spindle.count() - 1)
    window.in_spindle.setCurrentText(choice)
    window.close()
    again = MainWindow()
    try:
        assert again.in_spindle.currentText() == choice
    finally:
        again.close()


def test_closing_stops_the_origin_thread(window):
    window.close()
    assert not window.isVisible()
    assert not window.origin.session_active
