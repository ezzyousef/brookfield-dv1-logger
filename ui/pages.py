"""Pages and dialogs added in 2.1.0: the experiment notebook, sample comparison, the
instrument-source card and the export preview. Each builder takes the MainWindow and stores the
widgets it needs on it, like the pages in ui/main_window.py.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.compare import hysteresis, replicate_table, samples
from core.data_io import readings_to_dataframe
from core.figures import comparison_figure, source_counts
from core.instruments import DV1_UNAVAILABLE_REASON
from core.session import CHECKLIST_ITEMS
from labkit.qt.widgets import Card, Pill, PlotCanvas, ResponsiveRow, ResultTable, scrollable


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Hint")
    label.setWordWrap(True)
    return label


# ----------------------------------------------------------------------------- notebook
NOTEBOOK_TEXT_FIELDS = (
    ("title", "Experiment"), ("instrument_id", "Instrument ID"), ("instrument_serial", "Instrument serial no."),
    ("calibration_date", "Calibration date (YYYY-MM-DD)"), ("calibration_reference", "Calibration certificate / fluid lot"),
    ("operator", "Operator"), ("protocol", "Protocol / SOP"),
)


def build_notebook_page(win) -> QWidget:
    w = QWidget()
    outer = QVBoxLayout(w)
    outer.setContentsMargins(0, 0, 8, 0)
    outer.setSpacing(12)
    outer.addWidget(_hint(
        "Traceability for this session. These fields are saved with the session and written to the "
        "Provenance sheet of every Excel export and beside every CSV export. Recording them does not by "
        "itself make the measurement compliant with any standard."))

    row = ResponsiveRow(breakpoint=980)
    card = Card("Experiment notebook")
    form = QFormLayout()
    win.nb_fields = {}
    for key, label in NOTEBOOK_TEXT_FIELDS:
        edit = QLineEdit(getattr(win.notebook, key))
        edit.setAccessibleName(label)
        edit.editingFinished.connect(lambda k=key, e=edit: win.set_notebook_field(k, e.text().strip()))
        form.addRow(_hint(label), edit)
        win.nb_fields[key] = edit
    win.nb_fields["calibration_date"].setPlaceholderText("e.g. 2026-06-01")
    win.nb_interval = QSpinBox()
    win.nb_interval.setRange(0, 120)
    win.nb_interval.setSuffix(" months")
    win.nb_interval.setToolTip("Your lab's calibration interval (0 = no check). Not a Brookfield requirement.")
    win.nb_interval.setValue(win.notebook.calibration_interval_months)
    win.nb_interval.valueChanged.connect(lambda v: win.set_notebook_field("calibration_interval_months", int(v)))
    form.addRow(_hint("Calibration interval"), win.nb_interval)
    win.nb_target = QLineEdit("" if win.notebook.target_temperature_c is None else f"{win.notebook.target_temperature_c:g}")
    win.nb_target.setPlaceholderText("blank = no set point")
    win.nb_target.editingFinished.connect(win.set_notebook_target_temperature)
    form.addRow(_hint("Target temperature (°C)"), win.nb_target)
    win.nb_tolerance = QDoubleSpinBox()
    win.nb_tolerance.setRange(0.05, 20.0)
    win.nb_tolerance.setSingleStep(0.1)
    win.nb_tolerance.setValue(win.notebook.temperature_tolerance_c)
    win.nb_tolerance.setSuffix(" °C")
    win.nb_tolerance.valueChanged.connect(lambda v: win.set_notebook_field("temperature_tolerance_c", float(v)))
    form.addRow(_hint("Temperature tolerance"), win.nb_tolerance)
    win.nb_prep = QPlainTextEdit(win.notebook.sample_preparation)
    win.nb_prep.setMaximumHeight(80)
    win.nb_prep.setPlaceholderText("How the sample was prepared (mixing, resting time, degassing …)")
    win.nb_prep.textChanged.connect(lambda: win.set_notebook_field("sample_preparation",
                                                                   win.nb_prep.toPlainText().strip(), audit=False))
    form.addRow(_hint("Sample preparation"), win.nb_prep)
    win.nb_notes = QPlainTextEdit(win.notebook.notes)
    win.nb_notes.setMaximumHeight(80)
    win.nb_notes.textChanged.connect(lambda: win.set_notebook_field("notes", win.nb_notes.toPlainText().strip(),
                                                                    audit=False))
    form.addRow(_hint("Operator notes"), win.nb_notes)
    card.body.addLayout(form)
    win.nb_calibration = Pill("No calibration date", "warn")
    card.add_header_widget(win.nb_calibration)
    row.addWidget(card, 3)

    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    check = Card("Measurement checklist", "From docs/MANUAL.md. Ticks are saved with the session.")
    win.nb_checks = {}
    for item in CHECKLIST_ITEMS:
        box = QCheckBox(item)
        box.setChecked(bool(win.notebook.checklist.get(item)))
        box.toggled.connect(lambda on, i=item: win.set_checklist_item(i, on))
        check.body.addWidget(box)
        win.nb_checks[item] = box
    right_layout.addWidget(check)
    clock = Card("Clock")
    win.nb_clock = _hint("")
    clock.body.addWidget(win.nb_clock)
    clock.body.addWidget(_hint(
        "Every reading is timestamped with this PC's clock. Before a timed run, compare it with the lab's "
        "reference clock (or the time shown by your phone's network time) and correct Windows' time if it "
        "is off; the offset is not corrected afterwards."))
    right_layout.addWidget(clock)
    right_layout.addStretch(1)
    row.addWidget(right, 2)
    outer.addWidget(row)

    audit = Card("Audit trail", "Every change to the session, in order. It is saved with the session and cannot be edited.")
    win.audit_table = ResultTable(["Time", "Action", "Detail"])
    win.audit_table.setMinimumHeight(220)
    audit.body.addWidget(win.audit_table, 1)
    outer.addWidget(audit, 1)
    refresh_notebook_page(win)
    return scrollable(w)


def refresh_notebook_page(win) -> None:
    if not hasattr(win, "nb_calibration"):
        return
    state, text = win.notebook.calibration_status()
    pill = win.nb_calibration
    pill.setText({"ok": "Calibration current", "due": "Calibration overdue", "unknown": "Calibration unknown"}[state])
    pill.setObjectName({"ok": "PillGood", "due": "PillBad", "unknown": "PillWarn"}[state])
    pill.setToolTip(text)
    pill.style().unpolish(pill)
    pill.style().polish(pill)
    now = datetime.now().astimezone()
    win.nb_clock.setText(f"PC clock: {now:%Y-%m-%d %H:%M:%S}  (UTC{now:%z}, {now.tzname()})")
    win.audit_table.fill([(a.time, a.action, a.detail) for a in reversed(win.audit[-500:])])


def load_notebook_into_page(win) -> None:
    """Show a newly loaded notebook in the page's widgets without recording audit entries."""
    if not hasattr(win, "nb_fields"):
        return
    win._nb_loading = True
    try:
        for key, edit in win.nb_fields.items():
            edit.setText(str(getattr(win.notebook, key)))
        win.nb_interval.setValue(win.notebook.calibration_interval_months)
        win.nb_target.setText("" if win.notebook.target_temperature_c is None else f"{win.notebook.target_temperature_c:g}")
        win.nb_tolerance.setValue(win.notebook.temperature_tolerance_c)
        win.nb_prep.setPlainText(win.notebook.sample_preparation)
        win.nb_notes.setPlainText(win.notebook.notes)
        for item, box in win.nb_checks.items():
            box.setChecked(bool(win.notebook.checklist.get(item)))
    finally:
        win._nb_loading = False
    refresh_notebook_page(win)


# ----------------------------------------------------------------------------- comparison
def build_compare_page(win) -> QWidget:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 8, 0)
    layout.setSpacing(12)
    layout.addWidget(_hint(
        "Samples are grouped by Sample ID (or product and batch). Replicates are readings of one sample at the "
        "same spindle and speed. u is the standard uncertainty of the mean (s/√n) and U95 the expanded "
        "interval t·u: the statistical (Type A) part only, without calibration uncertainty."))
    rep = Card("Repeatability")
    win.compare_table = ResultTable(["Sample", "Spindle", "RPM", "n", "Mean (cP)", "s (cP)", "CV (%)",
                                     "u (cP)", "U95 (cP)", "Mean temp (°C)"])
    win.compare_table.setMinimumHeight(200)
    rep.body.addWidget(win.compare_table, 1)
    layout.addWidget(rep)
    curves = Card("Flow curves")
    win.compare_canvas = PlotCanvas()
    win.compare_canvas.setMinimumHeight(340)
    curves.body.addWidget(win.compare_canvas, 1)
    layout.addWidget(curves, 1)
    hyst = Card("Hysteresis (up/down speed sweeps)")
    win.hysteresis_table = ResultTable(["Sample", "Up speeds", "Down speeds", "Loop area (Pa/s)",
                                        "Loop area (% of up)", "Viscosity drop at shared speeds", "Note"])
    win.hysteresis_table.setMinimumHeight(140)
    hyst.body.addWidget(win.hysteresis_table)
    layout.addWidget(hyst)
    refresh_compare_page(win)
    return scrollable(w)


def refresh_compare_page(win) -> None:
    if not hasattr(win, "compare_table"):
        return
    rows = replicate_table(win.readings)
    win.compare_table.fill([(r.sample, r.spindle or "", r.rpm, r.n, r.mean_cp, r.sd_cp, r.cv_pct, r.u_mean_cp,
                             r.u95_cp, r.mean_temperature_c) for r in rows])
    spec = comparison_figure(win.readings)
    if spec.is_empty:
        win.compare_canvas.show_message("Flow curves need readings with a spindle that has a shear-rate constant.",
                                        win.theme)
    else:
        win.compare_canvas.show_figure(spec, win.theme)
    hrows = []
    for label, rs in samples(win.readings).items():
        h = hysteresis(rs, label)
        if h is None:
            continue
        drops = ", ".join(f"{rpm:g} rpm: {d:.1f} %" for rpm, _a, _b, d in h.per_speed)
        hrows.append((h.sample, " → ".join(f"{x:g}" for x in h.up_rpm), " → ".join(f"{x:g}" for x in h.down_rpm),
                      h.loop_area_pa_s, h.relative_area_pct, drops, h.note))
    win.hysteresis_table.fill(hrows)


# ----------------------------------------------------------------------------- instrument source
def build_instrument_card(win) -> Card:
    card = Card("Instrument source", "Readings that do not come from the keyboard. Each is labelled with its source.")
    dv1 = QLabel("DV1 live automation: not available. " + DV1_UNAVAILABLE_REASON)
    dv1.setWordWrap(True)
    dv1.setObjectName("PillWarn")
    dv1.setStyleSheet("padding: 8px 10px; border-radius: 8px;")
    card.body.addWidget(dv1)
    form = QFormLayout()
    win.adapter_kind = QComboBox()
    win.adapter_kind.addItem("Simulation (training, not a measurement)", "simulation")
    win.adapter_kind.addItem("Replay a recorded session or CSV", "replay")
    win.adapter_kind.addItem("Documented protocol on the serial port", "protocol")
    form.addRow(_hint("Source"), win.adapter_kind)
    sim_row = QHBoxLayout()
    win.sim_k = QDoubleSpinBox()
    win.sim_k.setRange(0.01, 1e9)
    win.sim_k.setDecimals(2)
    win.sim_k.setValue(2000.0)
    win.sim_k.setPrefix("K ")
    win.sim_k.setSuffix(" mPa·sⁿ")
    win.sim_n = QDoubleSpinBox()
    win.sim_n.setRange(0.05, 2.0)
    win.sim_n.setSingleStep(0.05)
    win.sim_n.setValue(0.6)
    win.sim_n.setPrefix("n ")
    win.sim_noise = QDoubleSpinBox()
    win.sim_noise.setRange(0.0, 20.0)
    win.sim_noise.setValue(1.0)
    win.sim_noise.setSuffix(" % noise")
    for widget in (win.sim_k, win.sim_n, win.sim_noise):
        sim_row.addWidget(widget)
    form.addRow(_hint("Simulated fluid"), sim_row)
    win.sim_rpms = QLineEdit("1, 2, 5, 10, 20, 50, 20, 10, 5, 2, 1")
    win.sim_rpms.setToolTip("Speed sequence for the simulation (rpm, comma-separated). Model and spindle "
                            "come from the Dashboard.")
    form.addRow(_hint("Speeds (rpm)"), win.sim_rpms)
    file_row = QHBoxLayout()
    win.adapter_file = QLineEdit()
    win.adapter_file.setReadOnly(True)
    win.adapter_file.setPlaceholderText("replay file or protocol definition (.json)")
    browse = QPushButton("Choose…")
    browse.clicked.connect(win._choose_adapter_file)
    file_row.addWidget(win.adapter_file, 1)
    file_row.addWidget(browse)
    form.addRow(_hint("File"), file_row)
    win.adapter_interval = QDoubleSpinBox()
    win.adapter_interval.setRange(0.2, 3600.0)
    win.adapter_interval.setValue(2.0)
    win.adapter_interval.setSuffix(" s")
    form.addRow(_hint("Poll every"), win.adapter_interval)
    card.body.addLayout(form)
    buttons = QHBoxLayout()
    win.adapter_start_btn = QPushButton("Start source")
    win.adapter_start_btn.setObjectName("Primary")
    win.adapter_start_btn.clicked.connect(win._start_adapter)
    win.adapter_stop_btn = QPushButton("Stop source")
    win.adapter_stop_btn.clicked.connect(win._stop_adapter)
    win.adapter_status = _hint("Stopped.")
    buttons.addWidget(win.adapter_start_btn)
    buttons.addWidget(win.adapter_stop_btn)
    buttons.addWidget(win.adapter_status, 1)
    card.body.addLayout(buttons)
    return card


# ----------------------------------------------------------------------------- export preview
class ExportPreviewDialog(QDialog):
    """What an export will contain, before any file is written."""

    def __init__(self, parent, readings, notebook, revision: int, kind: str = "CSV"):
        super().__init__(parent)
        self.setWindowTitle(f"Export preview — {kind}")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        flagged = sum(1 for r in readings if r.qc_flags)
        sources = "; ".join(f"{k}: {v}" for k, v in source_counts(readings).items())
        lines = [f"{len(readings)} reading(s) · export revision {revision}",
                 f"Sources — {sources}",
                 f"{flagged} reading(s) carry QC flags (in the qc_flags column)."]
        if notebook.title or notebook.instrument_id:
            lines.append(f"Experiment: {notebook.title or '—'} · instrument {notebook.instrument_id or '—'} · "
                         f"calibrated {notebook.calibration_date or '—'}")
        lines.append("A provenance file (<name>.provenance.json) is written beside the export.")
        self.summary = _hint("\n".join(lines))
        layout.addWidget(self.summary)
        frame = readings_to_dataframe(list(readings))
        shown = frame.head(20)
        self.table = QTableWidget(len(shown), len(frame.columns))
        self.table.setHorizontalHeaderLabels(list(frame.columns))
        for i, (_, row) in enumerate(shown.iterrows()):
            for j, value in enumerate(row):
                text = "" if value is None or (isinstance(value, float) and value != value) else (
                    f"{value:.6g}" if isinstance(value, float) else str(value))
                self.table.setItem(i, j, QTableWidgetItem(text))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        if len(frame) > len(shown):
            layout.addWidget(_hint(f"… and {len(frame) - len(shown)} more row(s)."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
