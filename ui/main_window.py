"""
ui/main_window.py

MainWindow for the Brookfield DV1 Viscosity Logger.

Tabs:
  1. Dashboard     - live-style readout boxes, viscometer connection panel,
                      sample info, timed test controls, data table + live plot,
                      all on one screen (styled after Brookfield's own
                      Wingather SQ dashboard). Manual data entry is still the
                      primary path today; see README/serial module docstring
                      for why serial auto-capture isn't wired up to real DV1
                      commands yet.
  2. Data Table    - all logged readings this session, with export buttons
  3. Plots         - viscosity vs time, viscosity vs shear rate, torque vs time
  4. Statistics    - summary stats + out-of-range torque flags
  5. Serial (Discovery) - raw terminal for protocol testing once you have
     documentation from Brookfield, or for any instrument that already has a
     known ASCII protocol (DV-II+/DV2T/DV3T/DV2+Pro). Connect/disconnect is
     done from the Dashboard tab; this tab shares that same connection.
"""

from __future__ import annotations
from datetime import datetime

from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, QSettings
from PySide6.QtGui import QFont, QPixmap, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QTabWidget, QTableView,
    QTextEdit, QFileDialog, QMessageBox, QGroupBox, QPlainTextEdit, QSpinBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QSplitter,
    QApplication, QScrollArea,
)

from ui.widgets import PlotPanel, CollapsibleSection, show_toast

from core.analysis import (
    Reading, SPINDLE_TABLE, MODEL_TABLE, VALID_SPEEDS_RPM,
    summarize, percent_torque_status, recommend_spindle_speed, power_law_fit,
)
from core.data_io import (
    export_to_excel, export_to_csv, readings_to_dataframe,
    save_session_json, load_session_json,
)
from core.serial_interface import (
    list_available_ports_detailed, RawSerialLink, SerialConnectionError, PYSERIAL_AVAILABLE,
)
from ui.resources import asset_path, AUTHOR_NAME, AUTHOR_EMAIL, COPYRIGHT_YEAR

DASH_BLUE = "#1c4b8c"
DASH_BLUE_DARK = "#0f2f5c"
DASH_BG = "#eaf1fb"


def _readout_box(unit: str) -> QLineEdit:
    box = QLineEdit()
    box.setReadOnly(True)
    box.setAlignment(Qt.AlignRight)
    box.setPlaceholderText(unit)
    f = QFont()
    f.setPointSize(14)
    f.setBold(True)
    box.setFont(f)
    box.setStyleSheet(
        "QLineEdit { background: white; border: 1px solid #7d97bf; padding: 4px; color: #111; }"
    )
    return box


class ReadingsTableModel(QAbstractTableModel):
    COLUMNS = [
        "Time", "Product", "Batch", "Viscosity (cP)", "% Torque", "Status", "Temp (C)",
        "RPM", "Spindle", "Model", "Shear Rate (1/s)", "Shear Stress (dyn/cm2)",
        "FSR (cP)", "Source", "Notes",
    ]

    def __init__(self, readings: list[Reading]):
        super().__init__()
        self._readings = readings

    def rowCount(self, parent=None):
        return len(self._readings)

    def columnCount(self, parent=None):
        return len(self.COLUMNS)

    def data(self, index, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        r = self._readings[index.row()]
        col = index.column()
        values = [
            r.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            r.product,
            r.batch,
            r.viscosity_cp,
            r.percent_torque,
            r.torque_status(),
            r.temperature_c,
            r.rpm,
            r.spindle,
            r.model,
            r.shear_rate(),
            r.shear_stress(),
            r.fsr(),
            r.source,
            r.notes,
        ]
        v = values[col]
        return "" if v is None else (f"{v:.3f}" if isinstance(v, float) else str(v))

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section]
        return str(section + 1)

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()


class AboutTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        logo_row = QHBoxLayout()
        logo_label = QLabel()
        logo_pixmap = QPixmap(asset_path("eml_logo.png"))
        if not logo_pixmap.isNull():
            logo_label.setPixmap(logo_pixmap.scaledToHeight(90, Qt.TransformationMode.SmoothTransformation))
        logo_row.addWidget(logo_label)
        logo_row.addStretch()
        layout.addLayout(logo_row)

        text = QLabel(
            "<h2>Brookfield DV1 Viscosity Logger</h2>"
            "<p style='color:#666'>Built for the Energy Materials Laboratory (EML)</p>"
            "<p>Logging, plotting, and analysis for viscosity readings taken from a "
            "Brookfield AMETEK DV1 Digital Viscometer.</p>"
            "<ul>"
            "<li><b>Dashboard tab</b>: live-style readouts, viscometer connection, "
            "spindle/speed advisor, timed test controls, manual reading entry.</li>"
            "<li><b>Data Table tab</b>: all logged readings, row deletion, session "
            "save/load, Excel/CSV export.</li>"
            "<li><b>Plots tab</b>: viscosity vs time/shear rate, torque vs time, "
            "temperature vs time.</li>"
            "<li><b>Statistics tab</b>: summary stats, out-of-range torque flags, and a "
            "power-law (Ostwald-de Waele) fit for characterizing shear-thinning/"
            "thickening samples such as polymer gels.</li>"
            "<li><b>Serial (Discovery) tab</b>: raw terminal and auto-capture for "
            "protocol discovery, once you have documentation from Brookfield.</li>"
            "</ul>"
            "<p style='color:#666'><i>FSR/shear-rate formulas and spindle constants are "
            "transcribed from Brookfield's official DV1 Operating Instructions manual "
            "(M14-023-A0416), Appendix D. The DV1's live serial command set is not "
            "publicly documented -- see the Serial (Discovery) tab and README for what "
            "that does and doesn't mean for this app.</i></p>"
            f"<p style='color:#666'>&copy; {COPYRIGHT_YEAR} {AUTHOR_NAME}. "
            f"Created by {AUTHOR_NAME} "
            f"(<a href='mailto:{AUTHOR_EMAIL}'>{AUTHOR_EMAIL}</a>).</p>"
        )
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        layout.addWidget(text)
        layout.addStretch()


class _LazyTabContainer(QWidget):
    """Thin, cheap-to-construct stand-in for a tab's real content, built on
    first visit instead of eagerly at app startup. Only the Dashboard tab
    (shown at launch) is built eagerly; the rest are built the first time
    the user actually clicks their tab -- keeps startup to the one tab that
    matters instead of paying for all six up front."""

    def __init__(self, factory):
        super().__init__()
        self._factory = factory
        self.real_widget: QWidget | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        placeholder = QLabel("Loading…")
        placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder = placeholder
        self._layout.addWidget(placeholder)

    def ensure_built(self) -> QWidget:
        if self.real_widget is None:
            self.real_widget = self._factory()
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._layout.addWidget(self.real_widget)
        return self.real_widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Brookfield DV1 Viscosity Logger")
        self.resize(1280, 850)

        self.readings: list[Reading] = []
        self.serial_link: RawSerialLink | None = None
        self.table_model = ReadingsTableModel(self.readings)

        self.raw_capture: list[tuple[datetime, str]] = []
        self._raw_rx_buffer = ""
        # The Dashboard's Connect button (always built eagerly) can log to
        # the terminal before the Serial tab itself has been built (it's
        # lazy-loaded, see _LazyTabContainer) -- buffered here and replayed
        # into the real QPlainTextEdit once _build_serial_tab creates it.
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

        tabs = QTabWidget()
        tabs.addTab(self._build_dashboard_tab(), "Dashboard")
        self._lazy_tabs = [
            _LazyTabContainer(self._build_table_tab),
            _LazyTabContainer(self._build_plots_tab),
            _LazyTabContainer(self._build_stats_tab),
            _LazyTabContainer(self._build_serial_tab),
            _LazyTabContainer(AboutTab),
        ]
        for container, label in zip(
            self._lazy_tabs, ["Data Table", "Plots", "Statistics", "Serial (Discovery)", "About"]
        ):
            tabs.addTab(container, label)
        tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(tabs)
        self._tabs = tabs

        self._restore_settings()
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_session)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._export_excel)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._add_manual_reading)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._add_manual_reading)
        QShortcut(QKeySequence("Ctrl+O"), self, activated=self._load_session)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    # ------------------------------------------------------------------
    # Tab 1: Dashboard
    # ------------------------------------------------------------------
    def _on_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if isinstance(widget, _LazyTabContainer):
            widget.ensure_built()

    def _build_dashboard_tab(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setSpacing(8)

        title = QLabel("  DASHBOARD")
        title.setStyleSheet(
            f"background: {DASH_BLUE_DARK}; color: white; font-weight: bold; "
            "font-size: 14px; padding: 6px;"
        )
        outer.addWidget(title)

        note = QLabel(
            "Live serial auto-capture isn't wired up to real DV1 commands yet -- "
            "enter the reading currently shown on the DV1 display below. See the "
            "'Serial (Discovery)' tab and README for why."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-style: italic;")
        outer.addWidget(note)

        # --- Top row: live readouts (left) + viscometer connection (right) ---
        top_row = QHBoxLayout()

        readout_box = QGroupBox()
        readout_box.setStyleSheet(f"QGroupBox {{ background: {DASH_BG}; border: 1px solid #b9c9e3; }}")
        readout_grid = QGridLayout(readout_box)

        def add_readout(row, col, label_text, unit):
            lbl = QLabel(f"{label_text} ({unit})")
            lbl.setStyleSheet("font-weight: bold; color: #234;")
            box = _readout_box(unit)
            cell = QVBoxLayout()
            cell.addWidget(lbl)
            cell.addWidget(box)
            readout_grid.addLayout(cell, row, col)
            return box

        self.dash_visc_out = add_readout(0, 0, "Viscosity", "cP")
        self.dash_speed_out = add_readout(0, 1, "Speed", "RPM")
        self.dash_torque_out = add_readout(0, 2, "Torque", "%")
        self.dash_shear_stress_out = add_readout(1, 0, "Shear Stress", "dyn/cm²")
        self.dash_shear_rate_out = add_readout(1, 1, "Shear Rate", "1/s")
        self.dash_temp_out = add_readout(1, 2, "Temperature", "°C")

        top_row.addWidget(readout_box, stretch=3)

        conn_box = QGroupBox("Viscometer")
        conn_box.setStyleSheet("QGroupBox { font-weight: bold; }")
        conn_layout = QVBoxLayout(conn_box)

        self.viscometer_status_label = QLabel("No Viscometer")
        self.viscometer_status_label.setStyleSheet(
            "background: #ddd; padding: 4px; font-weight: bold; color: #333;"
        )
        conn_layout.addWidget(self.viscometer_status_label)

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._refresh_ports)
        port_row.addWidget(QLabel("Port:"))
        port_row.addWidget(self.port_combo)
        port_row.addWidget(search_btn)
        conn_layout.addLayout(port_row)

        baud_row = QHBoxLayout()
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"])
        self.baud_combo.setCurrentText("9600")
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._toggle_serial_connection)
        baud_row.addWidget(QLabel("Baud:"))
        baud_row.addWidget(self.baud_combo)
        baud_row.addWidget(self.connect_btn)
        conn_layout.addLayout(baud_row)

        model_row = QHBoxLayout()
        self.in_model = QComboBox()
        self.in_model.addItems(sorted(MODEL_TABLE.keys()))
        model_row.addWidget(QLabel("Model:"))
        model_row.addWidget(self.in_model)
        conn_layout.addLayout(model_row)

        spindle_row = QHBoxLayout()
        self.in_spindle = QComboBox()
        self.in_spindle.addItems(sorted(SPINDLE_TABLE.keys()))
        spindle_row.addWidget(QLabel("Spindle:"))
        spindle_row.addWidget(self.in_spindle)
        conn_layout.addLayout(spindle_row)

        self._refresh_ports()
        top_row.addWidget(conn_box, stretch=2)
        outer.addLayout(top_row)

        # --- Test setup and status ---
        setup_box = QWidget()
        setup_layout = QHBoxLayout(setup_box)

        params_box = QGroupBox("Test Parameters")
        params_form = QFormLayout(params_box)
        self.data_interval_edit = QLineEdit("00:05")
        self.data_interval_edit.setPlaceholderText("mm:ss")
        params_form.addRow("Data Interval (mm:ss):", self.data_interval_edit)
        self.num_points_spin = QSpinBox()
        self.num_points_spin.setRange(1, 9999)
        self.num_points_spin.setValue(10)
        params_form.addRow("Num. of Data Points:", self.num_points_spin)
        setup_layout.addWidget(params_box)

        sample_box = QGroupBox("Sample Info")
        sample_form = QFormLayout(sample_box)
        self.in_product = QLineEdit()
        self.in_product.setPlaceholderText("optional")
        sample_form.addRow("Product Name:", self.in_product)
        self.in_batch = QLineEdit()
        self.in_batch.setPlaceholderText("optional")
        sample_form.addRow("Batch:", self.in_batch)
        self.in_notes = QLineEdit()
        self.in_notes.setPlaceholderText("optional")
        sample_form.addRow("Sample Notes:", self.in_notes)
        setup_layout.addWidget(sample_box)

        run_box = QVBoxLayout()
        self.run_btn = QPushButton("RUN")
        self.run_btn.setObjectName("runButton")
        self.run_btn.setToolTip("Start a timed reminder to take/enter a reading every 'Data Interval'.")
        self.run_btn.clicked.connect(self._start_run)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.clicked.connect(self._stop_run)
        run_box.addWidget(self.run_btn)
        run_box.addWidget(self.stop_btn)
        setup_layout.addLayout(run_box)

        outer.addWidget(CollapsibleSection("Test Setup and Status", content_widget=setup_box, start_expanded=True))

        # --- status readouts row ---
        status_row = QHBoxLayout()

        def add_status(label_text):
            box = QLineEdit()
            box.setReadOnly(True)
            cell = QVBoxLayout()
            cell.addWidget(QLabel(label_text))
            cell.addWidget(box)
            status_row.addLayout(cell)
            return box

        self.elapsed_label = add_status("Elapsed Time")
        self.readings_taken_label = add_status("Readings Taken")
        self.time_until_next_label = add_status("Time Until Next Reading")
        self.program_status_label = add_status("Program Status")
        self.program_status_label.setText("Idle")
        outer.addLayout(status_row)

        # --- manual reading entry ---
        entry_box = QGroupBox("Manual Reading Entry (read the value off the DV1 display)")
        entry_form = QFormLayout(entry_box)

        self.in_viscosity = QLineEdit()
        self.in_viscosity.setPlaceholderText("e.g. 1250.0")
        entry_form.addRow("Viscosity (cP):", self.in_viscosity)

        self.in_torque = QLineEdit()
        self.in_torque.setPlaceholderText("e.g. 45.2")
        entry_form.addRow("% Torque:", self.in_torque)

        self.in_temp = QLineEdit()
        self.in_temp.setPlaceholderText("e.g. 23.5 (optional)")
        entry_form.addRow("Temperature (C):", self.in_temp)

        self.in_rpm = QComboBox()
        self.in_rpm.addItems([str(v) for v in VALID_SPEEDS_RPM if v > 0])
        self.in_rpm.setEditable(True)
        entry_form.addRow("Speed (RPM):", self.in_rpm)

        self.calc_preview = QLabel("")
        self.calc_preview.setStyleSheet("color: #333;")
        entry_form.addRow("", self.calc_preview)

        for widget in (self.in_model, self.in_spindle, self.in_rpm):
            widget.currentTextChanged.connect(self._update_calc_preview)
        self.in_rpm.editTextChanged.connect(self._update_calc_preview)

        add_btn = QPushButton("Add Reading")
        add_btn.setObjectName("exportButton")
        add_btn.setToolTip("Ctrl+Enter")
        add_btn.clicked.connect(self._add_manual_reading)
        entry_form.addRow("", add_btn)

        outer.addWidget(entry_box)

        # --- spindle advisor ---
        advisor_box = QWidget()
        advisor_layout = QVBoxLayout(advisor_box)

        advisor_intro = QLabel(
            "Enter a ballpark expected viscosity for your sample (spec sheet, prior "
            "batch, or a guess). Uses the 'Model' selected above to suggest "
            "spindle/speed combos predicted to land in Brookfield's recommended "
            "10-100% torque window, ranked closest to 50%."
        )
        advisor_intro.setWordWrap(True)
        advisor_intro.setStyleSheet("color: #555; font-style: italic;")
        advisor_layout.addWidget(advisor_intro)

        advisor_row = QHBoxLayout()
        self.advisor_viscosity = QLineEdit()
        self.advisor_viscosity.setPlaceholderText("Expected viscosity, e.g. 1200 (cP)")
        advisor_btn = QPushButton("Suggest Spindle && Speed")
        advisor_btn.clicked.connect(self._suggest_spindle_speed)
        advisor_row.addWidget(QLabel("Expected viscosity (cP):"))
        advisor_row.addWidget(self.advisor_viscosity)
        advisor_row.addWidget(advisor_btn)
        advisor_layout.addLayout(advisor_row)

        self.advisor_table = QTableWidget(0, 3)
        self.advisor_table.setHorizontalHeaderLabels(["Spindle", "Speed (RPM)", "Predicted % Torque"])
        self.advisor_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.advisor_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.advisor_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.advisor_table.setMaximumHeight(140)
        self.advisor_table.cellDoubleClicked.connect(self._apply_advisor_row)
        advisor_layout.addWidget(self.advisor_table)

        advisor_hint = QLabel("Double-click a row to apply it to Spindle/Speed above.")
        advisor_hint.setStyleSheet("color: #777; font-size: 11px;")
        advisor_layout.addWidget(advisor_hint)

        advisor_ref = QLabel(
            "Reference: Brookfield DV1 Operating Instructions manual (M14-023-A0416), "
            "Appendix D (FSR formula) and Brookfield's documented 10-100% recommended "
            "torque range. Predicted values are estimates based on your entered "
            "expected viscosity, not a measurement -- confirm against the actual "
            "%torque reading and re-select spindle/speed if needed."
        )
        advisor_ref.setWordWrap(True)
        advisor_ref.setStyleSheet("color: #777; font-size: 11px;")
        advisor_layout.addWidget(advisor_ref)

        outer.addWidget(CollapsibleSection(
            "Spindle / Speed Advisor (decide before taking a reading)",
            content_widget=advisor_box, start_expanded=True,
        ))

        # --- Data page: table + live plot, in a splitter so it's resizable ---
        data_box = QGroupBox("DATA")
        data_layout = QVBoxLayout(data_box)
        splitter = QSplitter(Qt.Vertical)

        self.dash_table_view = QTableView()
        self.dash_table_view.setModel(self.table_model)
        self.dash_table_view.horizontalHeader().setStretchLastSection(True)
        self.dash_table_view.setMinimumHeight(160)
        splitter.addWidget(self.dash_table_view)

        self.dash_plot_canvas = PlotPanel()
        self.dash_plot_canvas.setMinimumHeight(260)
        splitter.addWidget(self.dash_plot_canvas)
        splitter.setSizes([200, 320])

        data_layout.addWidget(splitter)
        data_box.setMinimumHeight(500)
        outer.addWidget(data_box, stretch=1)

        self._update_calc_preview()
        self._update_dashboard_status_labels()

        # The Dashboard packs a LOT onto one tab (readouts, connection panel,
        # test setup, manual entry, advisor, data table, live plot) -- on a
        # normal-height display that's taller than the available window,
        # which without scrolling forces every section to compress toward
        # its minimum size instead (cramped, unreadable labels/table). Wrap
        # the whole tab in a scroll area so sections keep their natural
        # size and the user scrolls instead.
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    # ------------------------------------------------------------------
    # Spindle/speed advisor
    # ------------------------------------------------------------------
    def _suggest_spindle_speed(self):
        model = self.in_model.currentText()
        text = self.advisor_viscosity.text().strip()
        try:
            expected_viscosity = float(text)
        except ValueError:
            QMessageBox.warning(
                self, "Invalid input", f"'{text}' is not a valid expected viscosity."
            )
            return
        if expected_viscosity <= 0:
            QMessageBox.warning(self, "Invalid input", "Expected viscosity must be > 0.")
            return

        suggestions = recommend_spindle_speed(model, expected_viscosity)
        self.advisor_table.setRowCount(0)
        if not suggestions:
            QMessageBox.information(
                self, "No matches",
                "No spindle/speed combination for this model predicts a %torque "
                "in the recommended 10-100% window for that expected viscosity. "
                "Try a different model, or double-check the expected viscosity."
            )
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
            parts.append(f"Full Scale Range: {fsr:,.1f} cP")
        if sr is not None:
            parts.append(f"Shear Rate: {sr:,.3f} 1/s")
        self.calc_preview.setText(" | ".join(parts) if parts else "")

    # ------------------------------------------------------------------
    # Manual reading entry -> updates readouts, table, live plot
    # ------------------------------------------------------------------
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
            timestamp=datetime.now(),
            viscosity_cp=viscosity,
            percent_torque=torque,
            temperature_c=temp,
            rpm=rpm,
            spindle=spindle,
            model=model,
            source="manual",
            notes=self.in_notes.text().strip(),
            product=self.in_product.text().strip(),
            batch=self.in_batch.text().strip(),
        )
        self.readings.append(reading)
        self.table_model.refresh()
        self._update_dashboard_readouts(reading)
        self._update_dashboard_status_labels()
        self._refresh_dashboard_plot()

        status = percent_torque_status(torque)
        if status != "ok" and status != "unknown":
            QMessageBox.information(self, "Torque out of recommended range", status)

        self.in_viscosity.clear()
        self.in_torque.clear()

    def _update_dashboard_readouts(self, reading: Reading):
        def fmt(v):
            return "" if v is None else f"{v:.3f}"

        self.dash_visc_out.setText(fmt(reading.viscosity_cp))
        self.dash_speed_out.setText(fmt(reading.rpm))
        self.dash_torque_out.setText(fmt(reading.percent_torque))
        self.dash_shear_stress_out.setText(fmt(reading.shear_stress()))
        self.dash_shear_rate_out.setText(fmt(reading.shear_rate()))
        self.dash_temp_out.setText(fmt(reading.temperature_c))

    def _update_dashboard_status_labels(self):
        self.readings_taken_label.setText(str(len(self.readings)))

    def _refresh_dashboard_plot(self):
        if not self.readings:
            return
        t0 = self.readings[0].timestamp
        elapsed_min = [(r.timestamp - t0).total_seconds() / 60.0 for r in self.readings]
        self.dash_plot_canvas.plot_xy(
            elapsed_min, [r.viscosity_cp for r in self.readings],
            xlabel="Elapsed time (min)", ylabel="Viscosity (cP)", title="Viscosity vs Time",
        )

    # ------------------------------------------------------------------
    # RUN / STOP timed-test controls
    # ------------------------------------------------------------------
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
        self.program_status_label.setText("Running (manual entry)")
        self.run_timer.start()

    def _stop_run(self):
        self.run_active = False
        self.run_timer.stop()
        self.program_status_label.setText("Stopped")

    def _on_run_tick(self):
        if not self.run_active:
            return
        self.run_elapsed_s += 1
        self.run_next_in_s -= 1
        self.elapsed_label.setText(self._format_mmss(self.run_elapsed_s))

        if self.run_next_in_s <= 0:
            self.run_next_in_s = self.run_interval_s
            self._flash_reading_reminder()
            if self.run_target_points and len(self.readings) >= self.run_target_points:
                self._stop_run()
                self.program_status_label.setText("Complete")
        self.time_until_next_label.setText(self._format_mmss(self.run_next_in_s))

    def _flash_reading_reminder(self):
        # Non-blocking on purpose: a modal QMessageBox here would steal focus
        # and forcibly close any open dropdown (Model/Spindle/etc.) the user
        # happens to have open at that instant, which looked like a combo-box
        # bug but was actually this reminder firing mid-interaction.
        QApplication.beep()
        self.program_status_label.setText("Reading due now")
        self.program_status_label.setStyleSheet("background: #e8a33c; font-weight: bold;")
        QTimer.singleShot(1500, self._clear_reading_reminder_flash)

    def _clear_reading_reminder_flash(self):
        if self.run_active:
            self.program_status_label.setText("Running (manual entry)")
        self.program_status_label.setStyleSheet("")

    # ------------------------------------------------------------------
    # Tab 2: data table + export
    # ------------------------------------------------------------------
    def _build_table_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.horizontalHeader().setStretchLastSection(True)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self.table_view)

        btn_row = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected Row(s)")
        delete_btn.setObjectName("deleteButton")
        delete_btn.clicked.connect(self._delete_selected_rows)
        save_session_btn = QPushButton("Save Session...")
        save_session_btn.setToolTip("Save the in-progress session (Ctrl+S) so you can close the app and resume later.")
        save_session_btn.clicked.connect(self._save_session)
        load_session_btn = QPushButton("Load Session...")
        load_session_btn.clicked.connect(self._load_session)
        export_xlsx_btn = QPushButton("Export to Excel...")
        export_xlsx_btn.setObjectName("exportButton")
        export_xlsx_btn.setToolTip("Export to Excel (Ctrl+E)")
        export_xlsx_btn.clicked.connect(self._export_excel)
        export_csv_btn = QPushButton("Export to CSV...")
        export_csv_btn.setObjectName("exportButton")
        export_csv_btn.clicked.connect(self._export_csv)
        clear_btn = QPushButton("Clear Session")
        clear_btn.setObjectName("deleteButton")
        clear_btn.clicked.connect(self._clear_session)
        btn_row.addWidget(delete_btn)
        btn_row.addWidget(save_session_btn)
        btn_row.addWidget(load_session_btn)
        btn_row.addWidget(export_xlsx_btn)
        btn_row.addWidget(export_csv_btn)
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        return w

    def _delete_selected_rows(self):
        rows = sorted({idx.row() for idx in self.table_view.selectionModel().selectedRows()}, reverse=True)
        if not rows:
            QMessageBox.information(self, "No selection", "Select one or more rows in the table first.")
            return
        confirm = QMessageBox.question(
            self, "Delete rows", f"Delete {len(rows)} selected reading(s)?",
        )
        if confirm != QMessageBox.Yes:
            return
        for row in rows:
            del self.readings[row]
        self.table_model.refresh()
        self._update_dashboard_status_labels()
        self._refresh_dashboard_plot()

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
        show_toast(self, f"Session saved to {path}")

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
                "session (save first if you want to keep them). Continue?",
            )
            if confirm != QMessageBox.Yes:
                return
        self.readings.clear()
        self.readings.extend(loaded)
        self.table_model.refresh()
        self._update_dashboard_status_labels()
        self._refresh_dashboard_plot()
        show_toast(self, f"Loaded {len(loaded)} reading(s) from {path}")

    def _clear_session(self):
        if not self.readings:
            return
        confirm = QMessageBox.question(
            self, "Clear session",
            f"Remove all {len(self.readings)} logged readings from this session?",
        )
        if confirm == QMessageBox.Yes:
            self.readings.clear()
            self.table_model.refresh()
            self._update_dashboard_status_labels()

    def _export_excel(self):
        if not self.readings:
            QMessageBox.information(self, "No data", "No readings to export yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export to Excel", "dv1_readings.xlsx", "Excel files (*.xlsx)")
        if not path:
            return
        try:
            export_to_excel(self.readings, path)
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        show_toast(self, f"Exported to {path}")

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
        show_toast(self, f"Exported to {path}")

    # ------------------------------------------------------------------
    # Tab 3: plots
    # ------------------------------------------------------------------
    def _build_plots_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        controls = QHBoxLayout()
        self.plot_type = QComboBox()
        self.plot_type.addItems([
            "Viscosity vs Time",
            "Viscosity vs Shear Rate",
            "% Torque vs Time",
            "Temperature vs Time",
        ])
        refresh_btn = QPushButton("Refresh Plot")
        refresh_btn.clicked.connect(self._refresh_plot)
        controls.addWidget(QLabel("Plot:"))
        controls.addWidget(self.plot_type)
        controls.addWidget(refresh_btn)
        controls.addStretch()
        layout.addLayout(controls)

        self.plot_canvas = PlotPanel()
        layout.addWidget(self.plot_canvas)
        return w

    def _refresh_plot(self):
        if not self.readings:
            QMessageBox.information(self, "No data", "No readings to plot yet.")
            return
        kind = self.plot_type.currentText()
        t0 = self.readings[0].timestamp
        elapsed_min = [(r.timestamp - t0).total_seconds() / 60.0 for r in self.readings]

        if kind == "Viscosity vs Time":
            self.plot_canvas.plot_xy(
                elapsed_min, [r.viscosity_cp for r in self.readings],
                xlabel="Elapsed time (min)", ylabel="Viscosity (cP)", title="Viscosity vs Time",
            )
        elif kind == "Viscosity vs Shear Rate":
            pts = [(r.shear_rate(), r.viscosity_cp) for r in self.readings
                   if r.shear_rate() is not None and r.viscosity_cp is not None]
            pts.sort(key=lambda p: p[0])
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if not xs:
                QMessageBox.information(
                    self, "No shear rate data",
                    "None of the logged readings have a spindle with a defined "
                    "Shear Rate Constant (SRC), so shear rate can't be calculated.",
                )
                return
            self.plot_canvas.plot_xy(
                xs, ys, xlabel="Shear Rate (1/s)", ylabel="Viscosity (cP)",
                title="Viscosity vs Shear Rate",
            )
        elif kind == "% Torque vs Time":
            self.plot_canvas.plot_xy(
                elapsed_min, [r.percent_torque for r in self.readings],
                xlabel="Elapsed time (min)", ylabel="% Torque", title="% Torque vs Time",
            )
        elif kind == "Temperature vs Time":
            self.plot_canvas.plot_xy(
                elapsed_min, [r.temperature_c for r in self.readings],
                xlabel="Elapsed time (min)", ylabel="Temperature (C)", title="Temperature vs Time",
            )

    # ------------------------------------------------------------------
    # Tab 4: statistics
    # ------------------------------------------------------------------
    def _build_stats_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        refresh_btn = QPushButton("Refresh Statistics")
        refresh_btn.clicked.connect(self._refresh_stats)
        layout.addWidget(refresh_btn)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        layout.addWidget(self.stats_text)
        return w

    def _refresh_stats(self):
        summary = summarize(self.readings)
        lines = [f"Total readings logged: {summary['n_total']}", ""]
        for field_name, label in [
            ("viscosity_cp", "Viscosity (cP)"),
            ("percent_torque", "% Torque"),
            ("temperature_c", "Temperature (C)"),
            ("rpm", "RPM"),
        ]:
            s = summary[field_name]
            if s is None:
                lines.append(f"{label}: no data")
            else:
                lines.append(
                    f"{label}: n={s['n']}  mean={s['mean']:.3f}  "
                    f"stdev={s['stdev']:.3f}  min={s['min']:.3f}  max={s['max']:.3f}"
                )
        lines.append("")
        lines.append(f"Readings below 10% torque (accuracy not guaranteed): {summary['n_below_10pct_torque']}")
        lines.append(f"Readings above 100% torque (out of range): {summary['n_above_100pct_torque']}")
        if summary["n_below_10pct_torque"] or summary["n_above_100pct_torque"]:
            lines.append("")
            lines.append(
                "Brookfield recommends collecting data between 10-100% torque. "
                "Consider a different spindle/speed combination for flagged readings."
            )

        fit = power_law_fit(self.readings)
        lines.append("")
        lines.append("--- Power-Law (Ostwald-de Waele) Fit ---")
        lines.append("Model: apparent viscosity = K * shear_rate^(n-1)")
        if fit is None:
            lines.append(
                "Not enough data: need >=2 readings with a spindle that has a defined "
                "Shear Rate Constant (LV-2C/LV-3C/SA-70/ULA/DIN/SC4 spindles -- plain "
                "RV/HA/HB/T spindles have no SRC on the DV1) and viscosity > 0."
            )
        else:
            n = fit["n"]
            if n < 0.95:
                behavior = "shear-thinning (pseudoplastic) -- typical of polymer solutions/gels"
            elif n > 1.05:
                behavior = "shear-thickening (dilatant)"
            else:
                behavior = "approximately Newtonian"
            lines.append(
                f"n (flow behavior index) = {n:.4f}  |  K (consistency index) = {fit['k']:.4f} "
                f"cP*s^(n-1)  |  R^2 = {fit['r_squared']:.4f}  |  points used = {fit['n_points']}"
            )
            lines.append(f"Interpretation: {behavior}")
            lines.append(
                "Fit quality (R^2) matters most when points span a real range of shear "
                "rates (i.e. multiple speeds on the same spindle/sample), not a single point."
            )
        self.stats_text.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Tab 5: serial discovery / terminal (connection itself lives on Dashboard)
    # ------------------------------------------------------------------
    def _build_serial_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        warn = QLabel(
            "This tab gives you a raw serial terminal for protocol discovery/testing "
            "only. It does NOT send or interpret any DV1-specific commands, because I "
            "could not find a publicly documented DV1 serial command set (the DV1 manual "
            "only documents talking to Brookfield's own Wingather SQ software). "
            "Contact Brookfield/AMETEK support for the official 'DV1 Interface Command "
            "Reference' if one exists for your unit -- once you have it, real commands "
            "can be added to core/serial_interface.py (see DV1Protocol). "
            "Connect/disconnect from the 'Viscometer' panel on the Dashboard tab -- "
            "this tab shares that same connection."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #a33; font-weight: bold;")
        layout.addWidget(warn)

        if not PYSERIAL_AVAILABLE:
            missing = QLabel("pyserial is not installed. Run: pip install pyserial")
            missing.setStyleSheet("color: #a33;")
            layout.addWidget(missing)

        capture_box = QGroupBox("Auto-Capture (records everything the instrument sends, unattended)")
        capture_layout = QVBoxLayout(capture_box)
        capture_intro = QLabel(
            "The DV1 streams continuous raw frames over this connection on its own "
            "(no query needed). This does NOT decode those frames into Viscosity/"
            "Torque/etc. yet -- the field meanings aren't confirmed -- it just "
            "timestamps and records every raw line automatically so nothing is "
            "missed while you correlate it against the DV1's display."
        )
        capture_intro.setWordWrap(True)
        capture_intro.setStyleSheet("color: #555; font-style: italic;")
        capture_layout.addWidget(capture_intro)

        capture_btn_row = QHBoxLayout()
        self.capture_toggle_btn = QPushButton("Start Auto-Capture")
        self.capture_toggle_btn.clicked.connect(self._toggle_auto_capture)
        self.capture_count_label = QLabel("0 lines captured")
        export_capture_btn = QPushButton("Export Raw Capture to CSV...")
        export_capture_btn.clicked.connect(self._export_raw_capture)
        capture_btn_row.addWidget(self.capture_toggle_btn)
        capture_btn_row.addWidget(self.capture_count_label)
        capture_btn_row.addStretch()
        capture_btn_row.addWidget(export_capture_btn)
        capture_layout.addLayout(capture_btn_row)
        layout.addWidget(capture_box)

        term_box = QGroupBox("Terminal")
        term_layout = QVBoxLayout(term_box)
        self.terminal_output = QPlainTextEdit()
        self.terminal_output.setReadOnly(True)
        if self._terminal_log:
            self.terminal_output.appendPlainText("\n".join(self._terminal_log))
        term_layout.addWidget(self.terminal_output)

        send_row = QHBoxLayout()
        self.terminal_input = QLineEdit()
        self.terminal_input.setPlaceholderText("Bytes to send (as text; sent as UTF-8 + \\r\\n)")
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self._send_terminal_line)
        read_btn = QPushButton("Read Now")
        read_btn.clicked.connect(self._read_terminal_now)
        send_row.addWidget(self.terminal_input)
        send_row.addWidget(send_btn)
        send_row.addWidget(read_btn)
        term_layout.addLayout(send_row)

        layout.addWidget(term_box)
        return w

    # ------------------------------------------------------------------
    # Auto-capture: records the DV1's unsolicited raw stream unattended
    # ------------------------------------------------------------------
    def _toggle_auto_capture(self):
        if self.capture_active:
            self.capture_active = False
            self.capture_timer.stop()
            self.capture_toggle_btn.setText("Start Auto-Capture")
            return

        if not self.serial_link or not self.serial_link.is_open:
            QMessageBox.information(
                self, "Not connected", "Connect to a serial port first (Dashboard tab)."
            )
            return
        self.capture_active = True
        self._raw_rx_buffer = ""
        self.capture_timer.start()
        self.capture_toggle_btn.setText("Stop Auto-Capture")

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
        self.capture_count_label.setText(f"{len(self.raw_capture)} lines captured")

    def _export_raw_capture(self):
        if not self.raw_capture:
            QMessageBox.information(self, "No data", "No raw capture data yet -- start Auto-Capture first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Raw Capture to CSV", "dv1_raw_capture.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        import csv
        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "raw_line"])
                for ts, line in self.raw_capture:
                    writer.writerow([ts.isoformat(sep=" ", timespec="milliseconds"), line])
        except Exception as e:
            QMessageBox.critical(self, "Export failed", str(e))
            return
        show_toast(self, f"Saved {len(self.raw_capture)} lines to {path}")

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

    def _toggle_serial_connection(self):
        if self.serial_link and self.serial_link.is_open:
            if self.capture_active:
                self._toggle_auto_capture()
            self.serial_link.close()
            self.serial_link = None
            self.connect_btn.setText("Connect")
            self.viscometer_status_label.setText("No Viscometer")
            self.viscometer_status_label.setStyleSheet(
                "background: #ddd; padding: 4px; font-weight: bold; color: #333;"
            )
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
        self.viscometer_status_label.setText(f"Connected: {port} @ {baud} baud")
        self.viscometer_status_label.setStyleSheet(
            "background: #2e8b3d; padding: 4px; font-weight: bold; color: white;"
        )
        self._log_terminal(f"[connected to {port} @ {baud} baud]")

    def _send_terminal_line(self):
        if not self.serial_link or not self.serial_link.is_open:
            QMessageBox.information(self, "Not connected", "Connect to a serial port first (Dashboard tab).")
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
            QMessageBox.information(self, "Not connected", "Connect to a serial port first (Dashboard tab).")
            return
        try:
            data = self.serial_link.read_all_available()
        except SerialConnectionError as e:
            QMessageBox.critical(self, "Read failed", str(e))
            return
        if data:
            self._log_terminal(f"<< {data}")
        else:
            self._log_terminal("<< (no data available)")

    def closeEvent(self, event):
        self.run_timer.stop()
        self.capture_timer.stop()
        if self.serial_link and self.serial_link.is_open:
            self.serial_link.close()
        self._save_settings()
        event.accept()

    # ------------------------------------------------------------------
    # Settings persistence (last-used model/spindle/port/baud, window size)
    # ------------------------------------------------------------------
    def _save_settings(self) -> None:
        settings = QSettings()
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("model", self.in_model.currentText())
        settings.setValue("spindle", self.in_spindle.currentText())
        settings.setValue("baud", self.baud_combo.currentText())
        port_data = self.port_combo.currentData()
        if port_data:
            settings.setValue("port", port_data)

    def _restore_settings(self) -> None:
        settings = QSettings()
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)

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
