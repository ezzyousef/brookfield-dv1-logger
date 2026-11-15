# Upgrade audit: brookfield_dv1_logger (repository 05)

Baseline: `feature/licensing` @ `11bd09c` (app 2.0.0, labkit 1.1.0, 44 tests passing, self-test passing). This table compares each target in the 05 prompt with the code **before** this round.

| # | Target | Before | Evidence (before) |
|---|---|---|---|
| 1 | Structured manual capture: keyboard-first entry, configurable timed prompts, large controls, batch samples, spindle/speed/temperature metadata, prep and operator notes, interval warnings, automated QC flags, audit history, clock hints | PARTIAL | Manual entry, a timed reminder (interval, number of points) and spindle/speed/temperature fields existed. Missing: Enter-to-advance entry, large controls, batch queue, sample ID, operator, prep notes, interval lateness, QC flags beyond the torque dialog, audit trail, clock hint. `nan`/`inf` were accepted as values |
| 2 | Instrument adapter architecture: simulation, safe replay, user-supplied documented protocols, DV1 unavailable | MISSING | Only `RawSerialLink`, which could write to any port with no guard. `DV1Protocol` raised NotImplementedError |
| 3 | Rheology fits (Newtonian, power law, Bingham, HB, Cross/Carreau) only when the data support them, with residuals, units, CIs and range warnings | PARTIAL | Power-law log-log regression with R² only. No CIs, no other models, no support checks |
| 4 | Comparison dashboards (repeatability, replicate uncertainty, flow curves, hysteresis); notebook with traceability fields and revisioned exports | MISSING | None |
| 5 | UX: high-contrast readout, adviser with documented constants, checklist, trend graph, numpad, export preview, recoverable session, friendly errors | PARTIAL | The adviser existed (it inverts the manual's FSR formula) but did not show the constants. The live plot showed viscosity only. Errors appeared as raw `str(e)` dialogs. No checklist, recovery or preview |
| 6 | Validate corrupt session/import files, serial authorisation, write protection, failure recovery, packaging, simulated-reading tests | MISSING / PARTIAL | `load_session_json` trusted the file. `import_from_csv` = `pd.read_csv(path)` (**defect, below**). The PyInstaller spec, Inno script and `build.ps1` existed |
| A | Acceptance: model computations against independent implementations and manual examples | MISSING | Only a power-law self-consistency test |
| A | Prove hardware cannot receive unsupported commands | MISSING | The terminal sent any typed text |
| A | Preserve old sessions | UNVERIFIED | No legacy fixture |
| A | Label measured vs manually transcribed readings | PARTIAL | A `source` field existed ("manual"/"serial") but was not explained anywhere |

## Defects found

1. `core/data_io.py:80` (before): `pd.read_csv(path)`. A data row wider than the header turned its extra leading values into row labels, so every value shifted (reproduced: `2026-01-01 12:00:00,100,50,999` was loaded with timestamp = 100). This is the same defect as in supercap. Fixed with record-level validation, following the reviewed supercap design (commit `afd16f0`).
2. xlsxwriter wrote a note `=1+1` as a live formula, which allows formula injection into the exported workbook. The regression test failed on the old code and is now fixed.
3. Sessions were written with the locale code page and not atomically. A UTF-8 session written by another tool lost its characters.
4. The manual entry form accepted `nan` and `inf`.
5. The Serial page stated as fact that "the DV1 streams continuous raw frames on its own". This is unverified, and the wording has been changed.

## Risks noted, not changed

- pyserial raises DTR/RTS when it opens a port (its default). This is a control-line change, not a command. It was left unchanged because changing it without evidence from the manual could break other instruments.
- The spindle/model constants cannot be checked against the printed manual: no copy is in the repository.
