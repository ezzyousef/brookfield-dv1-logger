# Changelog

## 2.1.0 (2026-11-15)

### Fixed after an independent Codex review
- The raw terminal now **refuses** to send on a connection identified as a DV1: by the instrument
  name (now required), the stated document, or the port's USB description. Before, it only warned.
- Herschel–Bulkley (and any ill-conditioned fit) no longer crashes when building intervals.
  Unresolved intervals are suppressed with a stated reason.
- The formula guard covers every exported text cell (source, spindle, model, source label, QC
  flags, torque status, notes, notebook and settings values). Only complete numeric literals are
  exempt, so `-1+2` is guarded.
- Reversible escaping: exactly one apostrophe is added to text starting with = + - @ tab CR or an
  apostrophe, and exactly one is removed on re-import. Text whitespace is kept.
- CSV import refuses short rows (a missing value must be an explicit empty field) and duplicate
  column names.
- Each fit's warnings (for example an unresolved yield stress) are exported with its parameters.
- Session notebooks are validated (types, finite numbers, ranges, checklist booleans).
- The absolute torque readout (dyne·cm) was removed: its constant had no traceable
  manufacturer source.

### Fixed
- **CSV import read wrong values when a row had more values than the header.** pandas used the extra leading values as row labels and shifted every column. For example, `2026-01-01 12:00:00,100,50,999` was loaded with timestamp 100. Rows are now validated one by one before parsing, and a wider row is refused with its line number. Title lines above the header and trailing empty fields are handled.
- **Excel and CSV exports could run a note as a spreadsheet formula.** A note such as `=1+1` was written by xlsxwriter as a formula. Text cells starting with `=`, `+`, `@`, or `-` followed by a non-digit now get a leading apostrophe, which CSV import removes again.
- Typing `nan`, `inf` or a negative viscosity was accepted. These are now rejected.
- Sessions were written with the system code page and not atomically. They are now written as UTF-8 and atomically: a failed save leaves the previous file intact.

### Added
- Session format 2: experiment notebook, audit trail and export revision. Sessions from 2.0.0 (and their `NaN` values) still load, with a note.
- Validation of corrupt, truncated, oversized, binary and mistyped session files, with the reading and field named. CSV re-import (`readings_from_csv`) with per-cell errors.
- Experiment notebook page: instrument ID and serial, calibration date and interval, protocol, operator, sample preparation, temperature set point and tolerance, checklist, PC clock check, and audit trail.
- Automatic QC flags on every reading: torque window, viscosity-vs-torque transcription check, temperature set point, DV1 speed list, late entry, double entry, calibration overdue.
- Flow models: Newtonian, power law, Bingham, Herschel–Bulkley, Cross and Carreau, fitted on log residuals with 95 % t intervals, AICc ranking, residual diagnostics, and support checks (points, distinct rates, decades, plateau). Shown on the Statistics page and in the Excel export.
- Compare page: replicate statistics (s, CV, u, U95), flow curves by sample, hysteresis loop area.
- Instrument adapters: simulation, replay of sessions or CSVs, and user-supplied documented line protocols. DV1 definitions are refused; DV1 live automation stays unavailable.
- Serial write barrier: connections are read-only until sending is allowed with a stated document, and the permission ends on disconnect.
- Crash recovery file, plus a prompt when closing with unsaved readings.
- CSV export preview, provenance file beside each CSV export, export revisions. The Excel Provenance sheet now carries the notebook and the readings by source.
- Keyboard-first entry (Enter moves between fields, including numpad Enter), large-controls mode, high-contrast readout, batch sample queue, trend selector, spindle constants with their source, configurable late-entry flag and reminder beep.
- `examples/synthetic_shear_sweep.json`: a clearly labelled synthetic session for training and replay.
- `docs/EQUATION_REGRESSION_REPORT.md` and `docs/PROTOCOL_DEFINITIONS.md`.

### Changed
- labkit 1.1.0 → 1.2.0 (vendored with `sync.py --apply --test`).
- Readings carry `sample_id`, `operator` and `qc_flags`. CSV and Excel exports gain the `sample_id`, `operator`, `source_label` and `qc_flags` columns, appended after the existing ones.
- The Serial page is now "Instrument". Its auto-capture text no longer states that the DV1 streams frames on its own, which is unverified.

### Compatibility
- 2.1.0 opens every 2.0.0 session. 2.0.0 cannot open sessions saved by 2.1.0 (format 2).

## 2.0.0
- Interface rebuilt on labkit; offline licence status (not enforced).
