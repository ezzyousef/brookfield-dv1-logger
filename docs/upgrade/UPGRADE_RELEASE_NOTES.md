# DV1 Viscosity Logger 2.1.0: release notes

## For users

- **Safer data.** Sessions save atomically, and the open session is mirrored to a recovery file that is offered back after a crash. Closing with unsaved readings asks first. Every session from 2.0.0 still opens.
- **Fewer transcription errors.** Each reading is checked against viscosity = % torque × full-scale range / 100. Readings are flagged for torque outside 10–100 %, temperature off the set point, late entry after a reminder, double entry, an unusual speed, or overdue calibration. Flags appear in the table and in every export.
- **Faster entry.** Type the viscosity and press Enter (or the numpad Enter) to move to torque, then temperature; Enter there adds the reading. Large touch-friendly controls (Ctrl+Shift+L), a high-contrast readout (Ctrl+Shift+H), a batch sample queue (Ctrl+Shift+N), and a trend selector are also new.
- **Notebook page.** Instrument ID, calibration date and interval, protocol, operator, sample preparation, temperature set point, a measurement checklist, a PC clock check, and the audit trail of every change.
- **Flow models.** Newtonian, power law, Bingham, Herschel–Bulkley, Cross and Carreau, with 95 % intervals and AICc ranking. A model is only fitted when the data can support it; otherwise the app says why. The results describe the measured range only.
- **Compare page.** Repeatability (s, CV, standard and expanded uncertainty of the mean), flow curves of all samples, and hysteresis of up/down speed sweeps.
- **Instrument page.** A simulated viscometer for training, replay of recorded sessions, and documented line protocols for other instruments. **The DV1 still has no live link**, because its command set is not public. Every connection is read-only until you allow sending and name the protocol document you follow.
- **Exports.** A CSV export preview, a provenance file beside each CSV, revision numbers, and the notebook on the Excel Provenance sheet. Every reading is labelled manually transcribed, simulated, replayed, or received from an instrument.

## Migration

- Sessions saved by 2.1.0 use format 2. 2.0.0 cannot open them, so keep 2.0.0-format copies if you share files with users who have not updated.
- CSV and Excel exports gain four columns at the end: `sample_id`, `operator`, `source_label`, `qc_flags`. Existing columns keep their positions.

## Security notes

- Serial writes are blocked by default; the barrier is tested with a simulated port.
- Spreadsheet formula injection from notes is neutralised.
- Session and CSV files are size-limited and validated before use. Instructions found inside data files are kept as plain notes and never acted on.

## Not verified

The app was not run against a real DV1 or any other instrument. The PyInstaller build passed its self-test and the installer `DV1Logger-Setup-2.1.0.exe` compiled (SHA-256 `07795320C7E96444463D3DE0A6799FB48282163C3F8FF515A742DF7526C88D83`, 89 292 784 bytes), but it was not installed or run on a clean PC. The software is not code-signed.
