"""
ui/main_window.py

MainWindow for the Brookfield DV1 Viscosity Logger, built on the lab's shared labkit
shell: a navigation rail, light and dark themes, a Ctrl+K command palette, undo/redo
and styled OriginLab / Excel export.

Pages:
  Measure     Dashboard     live-style readouts, viscometer connection, timed test
                            controls, manual reading entry, spindle/speed advisor,
                            data table and live plot. Manual entry is still the primary
                            path; see README and core/serial_interface.py for why serial
                            auto-capture is not wired to real DV1 commands.
              Data table    every logged reading, row deletion, sessions, exports
  Analyse     Plots         viscosity vs time/shear rate (with power-law fit), torque
                            and temperature vs time
              Statistics    summary statistics, torque flags, power-law fit
  Instrument  Serial        raw terminal and auto-capture for protocol discovery.
                            Connect and disconnect from the Dashboard; this page shares
                            that connection.
  Help        About
"""

from __future__ import annotations

import csv
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QSettings, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.analysis import (
    MODEL_TABLE, SPINDLE_TABLE, VALID_SPEEDS_RPM, Reading, percent_torque_status,
    power_law_fit, recommend_spindle_speed, summarize,
)
from core.data_io import export_to_csv, load_session_json, save_session_json
from core.figures import PLOT_KINDS, PLOT_TITLES, build_figure, excel_report, interpret_flow_index, origin_book
from core.serial_interface import (
    PYSERIAL_AVAILABLE, RawSerialLink, SerialConnectionError, list_available_ports_detailed,
)
from labkit.qt.about import AboutPage
from labkit.qt.exporting import ExportBar
from labkit.qt.history import History
from labkit.qt.origin_worker import OriginWorker
from labkit.qt.shell import AppInfo, AppShell
from labkit.qt.widgets import Card, EmptyState, MetricTile, Pill, PlotCanvas, ResultTable, scrollable
from ui.resources import APP_VERSION, AUTHOR_EMAIL, AUTHOR_NAME, asset_path
from ui.widgets import CollapsibleSection

APP_INFO = AppInfo(
    name="Brookfield DV1 Viscosity Logger",
    short_name="DV1 Viscosity Logger",
    version=APP_VERSION,
    app_id="EML.DV1Logger.ViscosityLogger.1",
    description="Logging, plotting and analysis for viscosity readings from a Brookfield "
                "AMETEK DV1 digital viscometer, with publication figures sent straight to "
                "OriginLab and a formatted Excel workbook.",
    author=AUTHOR_NAME,
    email=AUTHOR_EMAIL,
    lab="EML",
    lab_full="Energy Materials Laboratory",
    icon_path=asset_path("app_icon_256.png"),
    logo_path=asset_path("eml_logo.png"),
    sources=[
        "Full-scale range and shear-rate formulas and spindle constants: Brookfield AMETEK, "
        "<i>DV1 Digital Viscometer Operating Instructions</i>, M14-023-A0416, Appendix D.",
        "Recommended 10–100 % torque window: Brookfield AMETEK, DV1 Operating Instructions.",
        "Power-law (Ostwald–de Waele) model: Steffe, J. F. <i>Rheological Methods in Food "
        "Process Engineering</i>, 2nd ed., ch. 2.",
        "The DV1's live serial command set is not publicly documented — see the Serial page.",
    ],
)


class ReadingsTableModel(QAbstractTableModel):
    COLUMNS = [
        "Time", "Product", "Batch", "Viscosity (cP)", "% Torque", "Status", "Temp (C)",
        "RPM", "Spindle", "Model", "Shear Rate (1/s)", "Shear Stress (dyn/cm2)",
        "FSR (cP)", "Source", "Notes",
    ]

    def __init__(self, readings: list[Reading]):
        super().__init__()
        self._readings = readings

    def rowCount(self, parent=None):  # noqa: N802 - Qt naming
        return len(self._readings)

    def columnCount(self, parent=None):  # noqa: N802 - Qt naming
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if role not in (Qt.DisplayRole, Qt.TextAlignmentRole):
            return None
        r = self._readings[index.row()]
        values = [
            r.timestamp.strftime("%Y-%m-%d %H:%M:%S"), r.product, r.batch, r.viscosity_cp,
            r.percent_torque, r.torque_status(), r.temperature_c, r.rpm, r.spindle, r.model,
            r.shear_rate(), r.shear_stress(), r.fsr(), r.source, r.notes,
        ]
        v = values[index.column()]
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignRight | Qt.AlignVCenter) if isinstance(v, (int, float)) else None
        return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802 - Qt naming
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return str(section + 1)

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()


def _table_view(model) -> QTableView:
    view = QTableView()
    view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.verticalHeader().setDefaultSectionSize(28)
    view.horizontalHeader().setStretchLastSection(True)
    view.setSelectionBehavior(QAbstractItemView.SelectRows)
    return view


def _form_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    return label


class MainWindow(AppShell):
    def __init__(self):
        # Nothing may be set on self before the Qt base class is initialised, so the
        # readings list is created locally and shared with the history by reference.
        readings: list[Reading] = []
        history = History(lambda: tuple(readings), lambda state: self._restore_readings(state),
                          initial_label="empty session")
        super().__init__(APP_INFO, history=history)
        self.readings = readings
        self.table_model = ReadingsTableModel(self.readings)

        self.serial_link: RawSerialLink | None = None
        self.raw_capture: list[tuple[datetime, str]] = []
        self._raw_rx_buffer = ""
        # The Dashboard's Connect button (always built first) can log to the terminal
        # before the Serial page exists — buffered here and replayed when it is built.
        self._terminal_log: list[str] = []
        self.capture_active = False
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(200)
        self.capture_timer.timeout.connect(self._on_capture_tick)

        self.run_timer = QTimer(self)
        self.run_timer.setInterval(1000)
        self.run_timer.timeout.connect(self._on_run_tick)
        self.run_active = False
        self.run_elapsed_s = 0
        self.run_next_in_s = 0
        self.run_interval_s = 5
        self.run_target_points = 0

        self.origin = OriginWorker(visible=True, parent=self)

        self.add_page("dashboard", "Dashboard", self._build_dashboard_tab, section="Measure", glyph="◉",
                      subtitle="Readouts, connection, timed test, manual entry and the live plot.",
                      framed=True, lazy=False)
        self.add_page("table", "Data table", self._build_table_tab, section="Measure", glyph="▤",
                      subtitle="Every reading logged this session.")
        self.add_page("plots", "Plots", self._build_plots_tab, section="Analyse", glyph="◭",
                      subtitle="Viscosity, torque and temperature — the same figures sent to Origin.")
        self.add_page("stats", "Statistics", self._build_stats_tab, section="Analyse", glyph="∑",
                      subtitle="Summary statistics, torque flags and the power-law fit.")
        self.add_page("serial", "Serial", self._build_serial_tab, section="Instrument", glyph="⇄",
                      heading="Serial (discovery)",
                      subtitle="A raw terminal for protocol discovery, sharing the Dashboard's connection.")
        self.add_page("about", "About", lambda: AboutPage(APP_INFO, tiles=self._about_tiles(),
                                                          notify=self.notify),
                      section="Help", glyph="ⓘ")

        self._build_file_menu()
        self.add_command("Add reading", "Measure", self._add_manual_reading)
        self.add_command("Save session", "File", self._save_session)
        self.add_command("Load session", "File", self._load_session)
        self.add_command("Export to Excel", "Export", self.export_bar_excel)
        self.add_command("Send to Origin", "Export", self.export_bar_origin)
        self.add_command("Export to CSV", "Export", self._export_csv)
        self.add_command("Clear session", "Session", self._clear_session)
        self.on_close(self._on_close)

        self.finalize(start_page="dashboard")
        self._restore_settings()
        self._update_counts()

    # ------------------------------------------------------------------ menus
    def _build_file_menu(self) -> None:
        self.add_menu_action("&File", "&Load session…", self._load_session, "Ctrl+O")
        self.add_menu_action("&File", "&Save session…", self._save_session, "Ctrl+S")
        self.add_menu_separator("&File")
        self.add_menu_action("&File", "Export to &Excel…", self.export_bar_excel, "Ctrl+E")
        self.add_menu_action("&File", "Export to &CSV…", self._export_csv)
        self.add_menu_action("&File", "Send to &Origin", self.export_bar_origin, "Ctrl+Shift+O")
        self.add_menu_separator("&File")
        self.add_menu_action("&File", "E&xit", self.close, "Ctrl+Q")
        self.add_menu_action("&Measure", "&Add reading", self._add_manual_reading, "Ctrl+Return")
        self.add_menu_action("&Measure", "Start &run", self._start_run, "F5")
        self.add_menu_action("&Measure", "S&top run", self._stop_run, "Shift+F5")

    def _about_tiles(self):
        return [("Spindles", str(len(SPINDLE_TABLE))), ("Models", str(len(MODEL_TABLE))),
                ("Speeds", str(len([v for v in VALID_SPEEDS_RPM if v > 0]))),
                ("Readings this session", str(len(self.readings)))]

    # ------------------------------------------------------------------ export plumbing
    def _export_bar(self) -> ExportBar:
        return ExportBar(
            worker=self.origin,
            books=lambda: [origin_book(self.readings)] if self.readings else [],
            report=lambda: (excel_report(self.readings, version=APP_VERSION, author=AUTHOR_NAME,
                                         project=self._project_name(), settings=self._settings_snapshot())
                            if self.readings else None),
            figures=lambda: [build_figure(k, self.readings) for k in PLOT_KINDS],
            notify=self.notify, project_name=self._project_name)

    def export_bar_excel(self) -> None:
        self._shared_export_bar().export_excel()

    def export_bar_origin(self) -> None:
        self._shared_export_bar().send_to_origin()

    def _shared_export_bar(self) -> ExportBar:
        """An invisible export bar behind the File menu and command palette actions."""
        if not hasattr(self, "_menu_export_bar"):
            self._menu_export_bar = self._export_bar()
            self._menu_export_bar.setParent(self)
            self._menu_export_bar.hide()
        return self._menu_export_bar

    def _project_name(self) -> str:
        product = self.in_product.text().strip() if hasattr(self, "in_product") else ""
        batch = self.in_batch.text().strip() if hasattr(self, "in_batch") else ""
        name = "_".join(p for p in (product, batch) if p) or "dv1_readings"
        return name.replace(" ", "_")

    def _settings_snapshot(self) -> dict:
        return {"Model": self.in_model.currentText(), "Spindle": self.in_spindle.currentText(),
                "Product": self.in_product.text().strip(), "Batch": self.in_batch.text().strip()}

    # ------------------------------------------------------------------ undo / redo
    def _restore_readings(self, state) -> None:
        self.readings[:] = list(state)          # keep the list object the table model holds
        self._on_readings_changed()

    def _on_readings_changed(self) -> None:
        self.table_model.refresh()
        self._fit_table_columns()
        self._update_dashboard_status_labels()
        self._refresh_dashboard_plot()
        if self.readings:
            self._update_dashboard_readouts(self.readings[-1])
        else:
            self._clear_dashboard_readouts()
        if self.is_page_built("plots"):
            self._refresh_plot(quiet=True)
        if self.is_page_built("stats"):
            self._refresh_stats()
        self._update_counts()

    def _fit_table_columns(self) -> None:
        """Size columns to their contents so timestamps and torque status are not cut off."""
        for view in (getattr(self, "dash_table_view", None), getattr(self, "table_view", None)):
            if view is not None:
                view.resizeColumnsToContents()

    def _update_counts(self) -> None:
        self.set_status(self.status_text.text(), f"{len(self.readings)} reading(s)")

    # ------------------------------------------------------------------ Dashboard
    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.setSpacing(12)

        note = QLabel(
            "Live serial auto-capture isn't wired up to real DV1 commands yet — enter the "
            "reading currently shown on the DV1 display below. See the Serial page and "
            "README for why.")
        note.setObjectName("Hint")
        note.setWordWrap(True)
        outer.addWidget(note)

        # --- readouts (left) + viscometer connection (right)
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        readouts = Card("Current reading")
        grid = QGridLayout()
        grid.setSpacing(10)
        self.dash_visc_out = MetricTile("Viscosity", "—", "cP")
        self.dash_speed_out = MetricTile("Speed", "—", "RPM")
        self.dash_torque_out = MetricTile("Torque", "—", "%")
        self.dash_shear_stress_out = MetricTile("Shear stress", "—", "dyn/cm²")
        self.dash_shear_rate_out = MetricTile("Shear rate", "—", "1/s")
        self.dash_temp_out = MetricTile("Temperature", "—", "°C")
        for i, tile in enumerate((self.dash_visc_out, self.dash_speed_out, self.dash_torque_out,
                                  self.dash_shear_stress_out, self.dash_shear_rate_out, self.dash_temp_out)):
            grid.addWidget(tile, i // 3, i % 3)
        readouts.body.addLayout(grid)
        top_row.addWidget(readouts, 3)

        conn = Card("Viscometer")
        self.viscometer_status_label = Pill("No viscometer", "warn")
        conn.add_header_widget(self.viscometer_status_label)
        conn_form = QFormLayout()
        conn_form.setHorizontalSpacing(10)
        conn_form.setVerticalSpacing(8)
        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(search_btn)
        conn_form.addRow(_form_label("Port"), port_row)
        baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText("9600")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.clicked.connect(self._toggle_serial_connection)
        baud_row.addWidget(self.baud_combo, 1)
        baud_row.addWidget(self.connect_btn)
        conn_form.addRow(_form_label("Baud"), baud_row)
        self.in_model = QComboBox()
        self.in_model.addItems(sorted(MODEL_TABLE.keys()))
        conn_form.addRow(_form_label("Model"), self.in_model)
        self.in_spindle = QComboBox()
        self.in_spindle.addItems(sorted(SPINDLE_TABLE.keys()))
        conn_form.addRow(_form_label("Spindle"), self.in_spindle)
        conn.body.addLayout(conn_form)
        self._refresh_ports()
        top_row.addWidget(conn, 2)
        outer.addLayout(top_row)

        # --- test setup and status
        setup_box = QWidget()
        setup_layout = QHBoxLayout(setup_box)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(12)
        params = Card("Test parameters")
        params_form = QFormLayout()
        self.data_interval_edit = QLineEdit("00:05")
        self.data_interval_edit.setPlaceholderText("mm:ss")
        params_form.addRow(_form_label("Data interval (mm:ss)"), self.data_interval_edit)
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(1, 9999)
        self.num_points_spin.setValue(10)
        params_form.addRow(_form_label("Number of data points"), self.num_points_spin)
        params.body.addLayout(params_form)
        setup_layout.addWidget(params, 1)

        sample = Card("Sample")
        sample_form = QFormLayout()
        self.in_product = QLineEdit()
        self.in_product.setPlaceholderText("optional")
        sample_form.addRow(_form_label("Product name"), self.in_product)
        self.in_batch = QLineEdit()
        self.in_batch.setPlaceholderText("optional")
        sample_form.addRow(_form_label("Batch"), self.in_batch)
        self.in_notes = QLineEdit()
        self.in_notes.setPlaceholderText("optional")
        sample_form.addRow(_form_label("Sample notes"), self.in_notes)
        sample.body.addLayout(sample_form)
        setup_layout.addWidget(sample, 1)

        run = Card("Run")
        self.run_btn = QPushButton("▶  Run")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setToolTip("Start a timed reminder to take and enter a reading every Data interval (F5).")
        self.run_btn.clicked.connect(self._start_run)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setToolTip("Stop the timed run (Shift+F5).")
        self.stop_btn.clicked.connect(self._stop_run)
        run.body.addWidget(self.run_btn)
        run.body.addWidget(self.stop_btn)
        run.body.addStretch(1)
        setup_layout.addWidget(run)
        outer.addWidget(CollapsibleSection("Test setup and status", content_widget=setup_box, start_expanded=True))

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.elapsed_label = MetricTile("Elapsed time", "00:00")
        self.readings_taken_label = MetricTile("Readings taken", "0")
        self.time_until_next_label = MetricTile("Next reading in", "—")
        self.program_status_label = MetricTile("Program status", "Idle")
        for tile in (self.elapsed_label, self.readings_taken_label, self.time_until_next_label,
                     self.program_status_label):
            status_row.addWidget(tile)
        outer.addLayout(status_row)

        # --- manual reading entry
        entry = Card("Manual reading entry", "Read the values off the DV1 display, then Add reading (Ctrl+Enter).")
        entry_form = QFormLayout()
        entry_form.setVerticalSpacing(8)
        self.in_viscosity = QLineEdit()
        self.in_viscosity.setPlaceholderText("e.g. 1250.0")
        entry_form.addRow(_form_label("Viscosity (cP)"), self.in_viscosity)
        self.in_torque = QLineEdit()
        self.in_torque.setPlaceholderText("e.g. 45.2")
        entry_form.addRow(_form_label("% Torque"), self.in_torque)
        self.in_temp = QLineEdit()
        self.in_temp.setPlaceholderText("e.g. 23.5 (optional)")
        entry_form.addRow(_form_label("Temperature (°C)"), self.in_temp)
        self.in_rpm = QComboBox()
        self.in_rpm.addItems([str(v) for v in VALID_SPEEDS_RPM if v > 0])
        self.in_rpm.setEditable(True)
        entry_form.addRow(_form_label("Speed (RPM)"), self.in_rpm)
        self.calc_preview = QLabel("")
        self.calc_preview.setObjectName("Hint")
        entry_form.addRow("", self.calc_preview)
        for widget in (self.in_model, self.in_spindle, self.in_rpm):
            widget.currentTextChanged.connect(self._update_calc_preview)
        self.in_rpm.editTextChanged.connect(self._update_calc_preview)
        add_btn = QPushButton("Add reading")
        add_btn.setObjectName("Primary")
        add_btn.setToolTip("Ctrl+Enter")
        add_btn.clicked.connect(self._add_manual_reading)
        entry_form.addRow("", add_btn)
        entry.body.addLayout(entry_form)
        outer.addWidget(entry)

        # --- spindle advisor
        advisor_box = QWidget()
        advisor_layout = QVBoxLayout(advisor_box)
        advisor_layout.setContentsMargins(0, 0, 0, 0)
        advisor_intro = QLabel(
            "Enter a ballpark expected viscosity for your sample (spec sheet, prior batch, or a "
            "guess). Uses the Model selected above to suggest spindle/speed combinations "
            "predicted to land in Brookfield's recommended 10–100 % torque window, ranked "
            "closest to 50 %.")
        advisor_intro.setObjectName("Hint")
        advisor_intro.setWordWrap(True)
        advisor_layout.addWidget(advisor_intro)
        advisor_row = QHBoxLayout()
        self.advisor_viscosity = QLineEdit()
        self.advisor_viscosity.setPlaceholderText("Expected viscosity, e.g. 1200 (cP)")
        advisor_btn = QPushButton("Suggest spindle && speed")
        advisor_btn.clicked.connect(self._suggest_spindle_speed)
        advisor_row.addWidget(_form_label("Expected viscosity (cP)"))
        advisor_row.addWidget(self.advisor_viscosity, 1)
        advisor_row.addWidget(advisor_btn)
        advisor_layout.addLayout(advisor_row)
        self.advisor_table = QTableWidget(0, 3)
        self.advisor_table.setHorizontalHeaderLabels(["Spindle", "Speed (RPM)", "Predicted % torque"])
        self.advisor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.advisor_table.verticalHeader().setVisible(False)
        self.advisor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.advisor_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.advisor_table.setMaximumHeight(160)
        self.advisor_table.cellDoubleClicked.connect(self._apply_advisor_row)
        advisor_layout.addWidget(self.advisor_table)
        advisor_hint = QLabel("Double-click a row to apply it to Spindle and Speed above. Reference: "
                              "Brookfield DV1 Operating Instructions (M14-023-A0416), Appendix D. "
                              "Predicted values are estimates from your expected viscosity, not a "
                              "measurement — confirm against the actual % torque reading.")
        advisor_hint.setObjectName("Hint")
        advisor_hint.setWordWrap(True)
        advisor_layout.addWidget(advisor_hint)
        outer.addWidget(CollapsibleSection("Spindle / speed advisor (decide before taking a reading)",
                                           content_widget=advisor_box, start_expanded=True))

        # --- data: table + live plot in a resizable splitter
        data = Card("Data")
        splitter = QSplitter(Qt.Vertical)
        self.dash_table_view = _table_view(self.table_model)
        self.dash_table_view.setMinimumHeight(160)
        splitter.addWidget(self.dash_table_view)
        self.dash_plot_canvas = PlotCanvas()
        self.dash_plot_canvas.setMinimumHeight(300)
        splitter.addWidget(self.dash_plot_canvas)
        splitter.setSizes([200, 340])
        data.body.addWidget(splitter, 1)
        data.setMinimumHeight(560)
        outer.addWidget(data, 1)

        self._update_calc_preview()
        self._update_dashboard_status_labels()
        self._refresh_dashboard_plot()
        # The Dashboard packs a lot onto one page; on a normal display that is taller
        # than the window, which without scrolling forces every section toward its
        # minimum size. Scrolling keeps sections at their natural size.
        return scrollable(w)

    # ------------------------------------------------------------------ spindle / speed advisor
    def _suggest_spindle_speed(self):
        model = self.in_model.currentText()
        text = self.advisor_viscosity.text().strip()
        try:
            expected_viscosity = float(text)
        except ValueError:
            QMessageBox.warning(self, "Invalid input", f"'{text}' is not a valid expected viscosity.")
            return
        if expected_viscosity <= 0:
            QMessageBox.warning(self, "Invalid input", "Expected viscosity must be > 0.")
            return
        suggestions = recommend_spindle_speed(model, expected_viscosity)
        self.advisor_table.setRowCount(0)
        if not suggestions:
            QMessageBox.information(
                self, "No matches",
                "No spindle/speed combination for this model predicts a %torque in the "
                "recommended 10-100% window for that expected viscosity. Try a different "
                "model, or double-check the expected viscosity.")
            return
        self.advisor_table.setRowCount(len(suggestions))
        for row, s in enumerate(suggestions):
            self.advisor_table.setItem(row, 0, QTableWidgetItem(s["spindle"]))
            self.advisor_table.setItem(row, 1, QTableWidgetItem(str(s["rpm"])))
            self.advisor_table.setItem(row, 2, QTableWidgetItem(f"{s['predicted_torque_pct']:.1f}%"))

    def _apply_advisor_row(self, row, _col):
        spindle_item = self.advisor_table.item(row, 0)
        rpm_item = self.advisor_table.item(row, 1)
        if not spindle_item or not rpm_item:
            return
        self.in_spindle.setCurrentText(spindle_item.text())
        self.in_rpm.setCurrentText(rpm_item.text())
        self._update_calc_preview()

    def _current_spindle_rpm_model(self):
        model = self.in_model.currentText()
        spindle = self.in_spindle.currentText()
        try:
            rpm = float(self.in_rpm.currentText())
        except ValueError:
            rpm = None
        return model, spindle, rpm

    def _update_calc_preview(self, *_):
        model, spindle, rpm = self._current_spindle_rpm_model()
        temp_reading = Reading(timestamp=datetime.now(), model=model, spindle=spindle, rpm=rpm)
        fsr = temp_reading.fsr()
        sr = temp_reading.shear_rate()
        parts = []
        if fsr is not None:
            parts.append(f"Full-scale range: {fsr:,.1f} cP")
        if sr is not None:
            parts.append(f"Shear rate: {sr:,.3f} 1/s")
        self.calc_preview.setText("  ·  ".join(parts) if parts else "")

    # ------------------------------------------------------------------ manual entry
    def _add_manual_reading(self):
        def parse_opt_float(text):
            text = text.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                raise ValueError(f"'{text}' is not a valid number")

        try:
            viscosity = parse_opt_float(self.in_viscosity.text())
            torque = parse_opt_float(self.in_torque.text())
            temp = parse_opt_float(self.in_temp.text())
        except ValueError as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return

        model, spindle, rpm = self._current_spindle_rpm_model()
        reading = Reading(
            timestamp=datetime.now(), viscosity_cp=viscosity, percent_torque=torque,
            temperature_c=temp, rpm=rpm, spindle=spindle, model=model, source="manual",
            notes=self.in_notes.text().strip(), product=self.in_product.text().strip(),
            batch=self.in_batch.text().strip(),
        )
        self.readings.append(reading)
        self.history.record(f"add reading {len(self.readings)}")
        self._on_readings_changed()
        self._update_dashboard_readouts(reading)

        status = percent_torque_status(torque)
        if status not in ("ok", "unknown"):
            # Kept as a dialog: an out-of-range torque means the reading itself is suspect.
            QMessageBox.information(self, "Torque out of recommended range", status)
        else:
            self.notify(f"Reading {len(self.readings)} added", "success")
        self.in_viscosity.clear()
        self.in_torque.clear()

    def _update_dashboard_readouts(self, reading: Reading):
        def fmt(v):
            return "—" if v is None else f"{v:.3f}"

        self.dash_visc_out.set_value(fmt(reading.viscosity_cp))
        self.dash_speed_out.set_value(fmt(reading.rpm))
        self.dash_torque_out.set_value(fmt(reading.percent_torque))
        self.dash_shear_stress_out.set_value(fmt(reading.shear_stress()))
        self.dash_shear_rate_out.set_value(fmt(reading.shear_rate()))
        self.dash_temp_out.set_value(fmt(reading.temperature_c))

    def _clear_dashboard_readouts(self):
        for tile in (self.dash_visc_out, self.dash_speed_out, self.dash_torque_out,
                     self.dash_shear_stress_out, self.dash_shear_rate_out, self.dash_temp_out):
            tile.set_value("—")

    def _update_dashboard_status_labels(self):
        self.readings_taken_label.set_value(str(len(self.readings)))

    def _refresh_dashboard_plot(self):
        if not hasattr(self, "dash_plot_canvas"):
            return
        spec = build_figure("viscosity_time", self.readings)
        if spec.is_empty:
            self.dash_plot_canvas.show_message("Add a reading to start the live plot.", self.theme)
        else:
            self.dash_plot_canvas.show_figure(spec, self.theme)

    # ------------------------------------------------------------------ run / stop
    @staticmethod
    def _parse_mmss(text: str) -> int:
        text = text.strip()
        if ":" in text:
            mm, ss = text.split(":", 1)
            return max(0, int(mm) * 60 + int(ss))
        return max(0, int(text))

    @staticmethod
    def _format_mmss(total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"

    def _start_run(self):
        try:
            interval_s = self._parse_mmss(self.data_interval_edit.text())
        except ValueError:
            QMessageBox.warning(self, "Invalid interval", "Data Interval must be mm:ss, e.g. 00:05.")
            return
        if interval_s <= 0:
            QMessageBox.warning(self, "Invalid interval", "Data Interval must be greater than 0.")
            return
        self.run_interval_s = interval_s
        self.run_target_points = self.num_points_spin.value()
        self.run_elapsed_s = 0
        self.run_next_in_s = interval_s
        self.run_active = True
        self.program_status_label.set_value("Running")
        self.run_timer.start()
        self.notify(f"Run started — a reading is due every {self._format_mmss(interval_s)}", "info")

    def _stop_run(self):
        self.run_active = False
        self.run_timer.stop()
        self.program_status_label.set_value("Stopped")

    def _on_run_tick(self):
        if not self.run_active:
            return
        self.run_elapsed_s += 1
        self.run_next_in_s -= 1
        self.elapsed_label.set_value(self._format_mmss(self.run_elapsed_s))
        if self.run_next_in_s <= 0:
            self.run_next_in_s = self.run_interval_s
            self._flash_reading_reminder()
            if self.run_target_points and len(self.readings) >= self.run_target_points:
                self._stop_run()
                self.program_status_label.set_value("Complete")
        self.time_until_next_label.set_value(self._format_mmss(self.run_next_in_s))

    def _flash_reading_reminder(self):
        # Non-blocking on purpose: a modal dialog here would steal focus and close any
        # dropdown the user has open at that instant, which looked like a combo-box bug
        # but was this reminder firing mid-interaction.
        QApplication.beep()
        self.program_status_label.set_value("Reading due")
        self.toasts.show_message("Reading due now — enter the value from the DV1 display", "warning", 1800)
        QTimer.singleShot(1500, self._clear_reading_reminder_flash)

    def _clear_reading_reminder_flash(self):
        if self.run_active:
            self.program_status_label.set_value("Running")

    # ------------------------------------------------------------------ data table + export
    def _build_table_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card("Readings")
        self.table_view = _table_view(self.table_model)
        card.body.addWidget(self.table_view, 1)

        btn_row = QHBoxLayout()
        delete_btn = QPushButton("Delete selected")
        delete_btn.setObjectName("Danger")
        delete_btn.clicked.connect(self._delete_selected_rows)
        save_session_btn = QPushButton("Save session…")
        save_session_btn.setToolTip("Save the in-progress session (Ctrl+S) to resume later.")
        save_session_btn.clicked.connect(self._save_session)
        load_session_btn = QPushButton("Load session…")
        load_session_btn.clicked.connect(self._load_session)
        export_csv_btn = QPushButton("Export to CSV…")
        export_csv_btn.clicked.connect(self._export_csv)
        clear_btn = QPushButton("Clear session")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self._clear_session)
        for b in (delete_btn, save_session_btn, load_session_btn, export_csv_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        card.body.addLayout(btn_row)
        layout.addWidget(card, 1)

        export = Card("Export", "A styled Origin project, a formatted Excel workbook with native "
                                "charts, or the figures at 300 dpi.")
        export.body.addWidget(self._export_bar())
        layout.addWidget(export)
        self._fit_table_columns()
        return w

    def _delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "No selection", "Select one or more rows in the table first.")
            return
        confirm = QMessageBox.question(self, "Delete rows", f"Delete {len(rows)} selected reading(s)?")
        if confirm != QMessageBox.Yes:
            return
        for row in rows:
            del self.readings[row]
        self.history.record(f"delete {len(rows)} reading(s)")
        self._on_readings_changed()
        self.notify(f"Deleted {len(rows)} reading(s) — Ctrl+Z to undo", "info")

    def _save_session(self):
        if not self.readings:
            QMessageBox.information(self, "No data", "No readings to save yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Session", "dv1_session.json", "JSON files (*.json)")
        if not path:
            return
        try:
            save_session_json(self.readings, path)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))
            return
        self.notify(f"Session saved to {path}", "success")

    def _load_session(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", "", "JSON files (*.json)")
        if not path:
            return
        try:
            loaded = load_session_json(path)
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))
            return
        if self.readings:
            confirm = QMessageBox.question(
                self, "Replace session",
                f"Loading will replace the {len(self.readings)} reading(s) currently in this "
                "session. You can undo this with Ctrl+Z. Continue?")
            if confirm != QMessageBox.Yes:
                return
        self.readings.clear()
        self.readings.extend(loaded)
        self.history.record(f"load {len(loaded)} reading(s)")
        self._on_readings_changed()
        self.notify(f"Loaded {len(loaded)} reading(s) from {path}", "success")

    def _clear_session(self):
        if not self.readings:
            return
        confirm = QMessageBox.question(
            self, "Clear session",
            f"Remove all {len(self.readings)} logged readings from this session? (Ctrl+Z undoes this.)")
        if confirm == QMessageBox.Yes:
            count = len(self.readings)
            self.readings.clear()
            self.history.record(f"clear {count} reading(s)")
            self._on_readings_changed()

    def _export_csv(self):
        if not self.readings:
            QMessageBox.information(self, "No data", "No readings to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to CSV", "dv1_readings.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            export_to_csv(self.readings, path)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.notify(f"Exported to {path}", "success")

    # ------------------------------------------------------------------ plots
    def _build_plots_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = Card("Figure")
        controls = QHBoxLayout()
        self.plot_type = QComboBox()
        for kind in PLOT_KINDS:
            self.plot_type.addItem(PLOT_TITLES[kind], kind)
        self.plot_type.currentIndexChanged.connect(lambda _i: self._refresh_plot(quiet=True))
        controls.addWidget(_form_label("Plot"))
        controls.addWidget(self.plot_type)
        controls.addStretch()
        card.body.addLayout(controls)
        self.plot_canvas = PlotCanvas()
        card.body.addWidget(self.plot_canvas, 1)
        card.body.addWidget(self._export_bar())
        layout.addWidget(card, 1)
        self._refresh_plot(quiet=True)
        return w

    def _refresh_plot(self, quiet: bool = False):
        kind = self.plot_type.currentData() if hasattr(self, "plot_type") else "viscosity_time"
        spec = build_figure(kind, self.readings)
        if not self.readings:
            if not quiet:
                QMessageBox.information(self, "No data", "No readings to plot yet.")
            self.plot_canvas.show_message("No readings to plot yet.", self.theme)
            return
        if spec.is_empty:
            message = ("None of the logged readings use a spindle with a defined Shear Rate "
                       "Constant (SRC), so shear rate can't be calculated."
                       if kind == "viscosity_shear" else "No values of this kind were logged.")
            if not quiet:
                QMessageBox.information(self, "Nothing to plot", message)
            self.plot_canvas.show_message(message, self.theme)
            return
        fit = power_law_fit(self.readings) if kind == "viscosity_shear" else None
        metrics = [("n", fit["n"], "-"), ("K", fit["k"], "cP·sⁿ⁻¹"), ("R²", fit["r_squared"], "-")] if fit else None
        self.plot_canvas.show_figure(spec, self.theme, metrics=metrics)

    # ------------------------------------------------------------------ statistics
    def _build_stats_tab(self) -> QWidget:
        self._stats_host = QWidget()
        layout = QVBoxLayout(self._stats_host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(12)
        tiles = QHBoxLayout()
        self.stat_count = MetricTile("Readings", "0")
        self.stat_mean = MetricTile("Mean viscosity", "—", "cP")
        self.stat_flow_index = MetricTile("Flow index n", "—")
        self.stat_flags = MetricTile("Out-of-range torque", "0")
        for tile in (self.stat_count, self.stat_mean, self.stat_flow_index, self.stat_flags):
            tiles.addWidget(tile)
        layout.addLayout(tiles)
        table_card = Card("Summary")
        self.stats_table = ResultTable(["Quantity", "Value", "Unit", "Note"])
        self.stats_table.setMinimumHeight(360)
        table_card.body.addWidget(self.stats_table, 1)
        layout.addWidget(table_card, 1)
        self.stats_note = QLabel()
        self.stats_note.setObjectName("Hint")
        self.stats_note.setWordWrap(True)
        layout.addWidget(self.stats_note)
        self._refresh_stats()
        return scrollable(self._stats_host)

    def _refresh_stats(self):
        from core.figures import summary_results

        summary = summarize(self.readings)
        rows = summary_results(self.readings)
        self.stats_table.fill([(q, v, u or "-", n) for q, v, u, n in rows])
        self.stat_count.set_value(str(summary["n_total"]))
        visc = summary["viscosity_cp"]
        self.stat_mean.set_value("—" if visc is None else f"{visc['mean']:.4g}")
        flags = summary["n_below_10pct_torque"] + summary["n_above_100pct_torque"]
        self.stat_flags.set_value(str(flags))
        fit = power_law_fit(self.readings)
        self.stat_flow_index.set_value("—" if fit is None else f"{fit['n']:.3f}")

        notes = []
        if flags:
            notes.append("Brookfield recommends collecting data between 10 and 100 % torque. "
                         "Consider a different spindle/speed combination for the flagged readings.")
        if fit is None:
            notes.append("Power-law fit: needs at least two readings with a spindle that has a defined "
                         "Shear Rate Constant (LV-2C/LV-3C/SA-70/ULA/DIN/SC4 — plain RV/HA/HB/T spindles "
                         "have no SRC on the DV1) and viscosity > 0.")
        else:
            notes.append(f"Power-law model: apparent viscosity = K·γ̇ⁿ⁻¹. {interpret_flow_index(fit['n'])}. "
                         "R² matters most when the points span a real range of shear rates — several "
                         "speeds on the same spindle and sample, not a single point.")
        self.stats_note.setText("\n\n".join(notes))

    # ------------------------------------------------------------------ serial discovery
    def _build_serial_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        warn = QLabel(
            "This page is a raw serial terminal for protocol discovery and testing only. It does "
            "NOT send or interpret DV1-specific commands, because no publicly documented DV1 "
            "serial command set could be found (the DV1 manual only documents talking to "
            "Brookfield's own Wingather SQ software). Contact Brookfield/AMETEK support for the "
            "official DV1 Interface Command Reference if one exists for your unit — real commands "
            "can then be added to core/serial_interface.py (see DV1Protocol). Connect and "
            "disconnect from the Viscometer card on the Dashboard; this page shares that connection.")
        warn.setWordWrap(True)
        warn.setObjectName("PillWarn")
        warn.setStyleSheet("padding: 10px 12px; border-radius: 10px; font-size: 12px;")
        layout.addWidget(warn)

        if not PYSERIAL_AVAILABLE:
            missing = Pill("pyserial is not installed. Run: pip install pyserial", "bad")
            layout.addWidget(missing)

        capture = Card("Auto-capture", "Records everything the instrument sends, unattended.")
        capture_intro = QLabel(
            "The DV1 streams continuous raw frames on its own (no query needed). This does NOT "
            "decode those frames into viscosity/torque yet — the field meanings aren't confirmed — "
            "it timestamps and records every raw line so nothing is missed while you correlate it "
            "against the DV1's display.")
        capture_intro.setObjectName("Hint")
        capture_intro.setWordWrap(True)
        capture.body.addWidget(capture_intro)
        capture_btn_row = QHBoxLayout()
        self.capture_toggle_btn = QPushButton("Start auto-capture")
        self.capture_toggle_btn.setObjectName("Primary")
        self.capture_toggle_btn.clicked.connect(self._toggle_auto_capture)
        self.capture_count_label = QLabel("0 lines captured")
        self.capture_count_label.setObjectName("Hint")
        export_capture_btn = QPushButton("Export raw capture to CSV…")
        export_capture_btn.clicked.connect(self._export_raw_capture)
        capture_btn_row.addWidget(self.capture_toggle_btn)
        capture_btn_row.addWidget(self.capture_count_label)
        capture_btn_row.addStretch()
        capture_btn_row.addWidget(export_capture_btn)
        capture.body.addLayout(capture_btn_row)
        layout.addWidget(capture)

        term = Card("Terminal")
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setObjectName("Mono")
        self.terminal_output.setReadOnly(True)
        if self._terminal_log:
            self.terminal_output.appendPlainText("\n".join(self._terminal_log))
        term.body.addWidget(self.terminal_output, 1)
        send_row = QHBoxLayout()
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Bytes to send (as text; sent as UTF-8 + \\r\\n)")
        self.terminal_input.returnPressed.connect(self._send_terminal_line)
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_terminal_line)
        read_btn = QPushButton("Read now")
        read_btn.clicked.connect(self._read_terminal_now)
        send_row.addWidget(self.terminal_input, 1)
        send_row.addWidget(send_btn)
        send_row.addWidget(read_btn)
        term.body.addLayout(send_row)
        layout.addWidget(term, 1)
        return w

    def _toggle_auto_capture(self):
        if self.capture_active:
            self.capture_active = False
            self.capture_timer.stop()
            if hasattr(self, "capture_toggle_btn"):
                self.capture_toggle_btn.setText("Start auto-capture")
            return
        if not self.serial_link or not self.serial_link.is_open:
            QMessageBox.information(self, "Not connected", "Connect to a serial port first (Dashboard).")
            return
        self.capture_active = True
        self._raw_rx_buffer = ""
        self.capture_timer.start()
        self.capture_toggle_btn.setText("Stop auto-capture")

    def _on_capture_tick(self):
        if not self.serial_link or not self.serial_link.is_open:
            self._toggle_auto_capture()
            return
        try:
            data = self.serial_link.read_all_available()
        except SerialConnectionError:
            self._toggle_auto_capture()
            return
        if not data:
            return
        self._raw_rx_buffer += data
        while "\r" in self._raw_rx_buffer:
            line, self._raw_rx_buffer = self._raw_rx_buffer.split("\r", 1)
            line = line.strip("\n")
            if not line:
                continue
            ts = datetime.now()
            self.raw_capture.append((ts, line))
            self._log_terminal(f"[{ts.strftime('%H:%M:%S.%f')[:-3]}] {line}")
        if hasattr(self, "capture_count_label"):
            self.capture_count_label.setText(f"{len(self.raw_capture)} lines captured")

    def _export_raw_capture(self):
        if not self.raw_capture:
            QMessageBox.information(self, "No data", "No raw capture data yet -- start Auto-Capture first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Raw Capture to CSV", "dv1_raw_capture.csv",
                                              "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "raw_line"])
                for ts, line in self.raw_capture:
                    writer.writerow([ts.isoformat(sep=" ", timespec="milliseconds"), line])
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        self.notify(f"Saved {len(self.raw_capture)} lines to {path}", "success")

    def _log_terminal(self, text: str) -> None:
        self._terminal_log.append(text)
        if hasattr(self, "terminal_output"):
            self.terminal_output.appendPlainText(text)

    def _refresh_ports(self):
        self.port_combo.clear()
        ports = list_available_ports_detailed()
        if ports:
            for device, desc in ports:
                label = f"{device} - {desc}" if desc else device
                self.port_combo.addItem(label, userData=device)
        else:
            self.port_combo.addItem("(no ports found)", userData=None)

    def _set_connection_pill(self, text: str, kind: str) -> None:
        pill = self.viscometer_status_label
        pill.setText(text)
        pill.setObjectName({"good": "PillGood", "warn": "PillWarn", "bad": "PillBad"}[kind])
        pill.style().unpolish(pill)
        pill.style().polish(pill)

    def _toggle_serial_connection(self):
        if self.serial_link and self.serial_link.is_open:
            if self.capture_active:
                self._toggle_auto_capture()
            self.serial_link.close()
            self.serial_link = None
            self.connect_btn.setText("Connect")
            self._set_connection_pill("No viscometer", "warn")
            self._log_terminal("[disconnected]")
            return
        port = self.port_combo.currentData()
        if not port:
            QMessageBox.warning(self, "No port selected", "No serial port available to connect to.")
            return
        baud = int(self.baud_combo.currentText())
        try:
            self.serial_link = RawSerialLink(port, baudrate=baud, timeout=1.0)
            self.serial_link.open()
        except SerialConnectionError as e:
            QMessageBox.critical(self, "Connection failed", str(e))
            self.serial_link = None
            return
        self.connect_btn.setText("Disconnect")
        self._set_connection_pill(f"Connected: {port} @ {baud}", "good")
        self._log_terminal(f"[connected to {port} @ {baud} baud]")
        self.notify(f"Connected to {port} at {baud} baud", "success")

    def _send_terminal_line(self):
        if not self.serial_link or not self.serial_link.is_open:
            QMessageBox.information(self, "Not connected", "Connect to a serial port first (Dashboard).")
            return
        text = self.terminal_input.text()
        try:
            self.serial_link.write_raw((text + "\r\n").encode())
            self._log_terminal(f">> {text}")
        except SerialConnectionError as e:
            QMessageBox.critical(self, "Send failed", str(e))
        self.terminal_input.clear()

    def _read_terminal_now(self):
        if not self.serial_link or not self.serial_link.is_open:
            QMessageBox.information(self, "Not connected", "Connect to a serial port first (Dashboard).")
            return
        try:
            data = self.serial_link.read_all_available()
        except SerialConnectionError as e:
            QMessageBox.critical(self, "Read failed", str(e))
            return
        self._log_terminal(f"<< {data}" if data else "<< (no data available)")

    # ------------------------------------------------------------------ theme and lifecycle
    def apply_theme(self, theme: str) -> None:
        super().apply_theme(theme)
        if hasattr(self, "dash_plot_canvas"):
            self._refresh_dashboard_plot()
        if hasattr(self, "plot_canvas"):
            self._refresh_plot(quiet=True)

    def _on_close(self):
        self.run_timer.stop()
        self.capture_timer.stop()
        if self.serial_link and self.serial_link.is_open:
            self.serial_link.close()
        self._save_settings()
        # Joins the Origin thread; Qt aborts the process if a running QThread is destroyed.
        self.origin.shutdown(15_000)
        return None

    # ------------------------------------------------------------------ settings
    def _save_settings(self) -> None:
        settings = QSettings()
        settings.setValue("model", self.in_model.currentText())
        settings.setValue("spindle", self.in_spindle.currentText())
        settings.setValue("baud", self.baud_combo.currentText())
        port_data = self.port_combo.currentData()
        if port_data:
            settings.setValue("port", port_data)

    def _restore_settings(self) -> None:
        settings = QSettings()
        model = settings.value("model")
        if model and self.in_model.findText(model) >= 0:
            self.in_model.setCurrentText(model)
        spindle = settings.value("spindle")
        if spindle and self.in_spindle.findText(spindle) >= 0:
            self.in_spindle.setCurrentText(spindle)
        baud = settings.value("baud")
        if baud and self.baud_combo.findText(baud) >= 0:
            self.baud_combo.setCurrentText(baud)
        port = settings.value("port")
        if port:
            idx = self.port_combo.findData(port)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
