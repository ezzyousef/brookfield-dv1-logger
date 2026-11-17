# Brookfield DV1 Viscosity Logger

A Windows desktop app (PySide6) for logging, plotting and analysing viscosity readings
taken with a Brookfield AMETEK DV1 Digital Viscometer. It uses the lab's shared
**labkit** interface (the same one as AeroLab Studio and Supercap Suite): a navigation
rail, light and dark themes, a Ctrl+K command palette, undo/redo, styled OriginLab graphs
and a formatted Excel workbook.

Made by Ezzeldien Yousef (ezzyousef2@aucegypt.edu), Energy Materials Laboratory (EML).
A step-by-step user guide with screenshots is in `DV1_Logger_User_Guide.docx` (this folder);
`docs/MANUAL.md` covers sample preparation and measurement practice.

## Important: about live instrument communication

Brookfield's DV1 Operating Instructions (M14-023-A0416) say the DV1 talks to a PC over
USB-B only through Brookfield's own **Wingather SQ** software, and no open ASCII command
set is published for the DV1 (unlike the DV2+Pro, DV-II+, DV2T and DV3T). Rather than guess
at command bytes for real lab hardware, **readings are entered manually**: read the value
off the DV1 display and type it in. Logging, plots, statistics and every export work from
manually entered data.

The **Instrument** page offers a simulated viscometer (for training), replay of recorded
sessions, and user-supplied *documented* line protocols for other instruments
(`docs/PROTOCOL_DEFINITIONS.md`). It also has a raw serial terminal. **Every connection is
read-only:** nothing is sent until you allow sending, name the instrument and the protocol document you
are following, and the permission ends when you disconnect. Sending to a DV1, and definitions
for the DV1, are refused.
Every reading is labelled with its source (manually transcribed, simulated, replayed, or
received from an instrument). To wire up live
auto-logging, ask Brookfield/AMETEK support for the DV1 interface command reference and put
the verified commands into `DV1Protocol` in `core/serial_interface.py`.

## What's included

| Page | What it does |
|---|---|
| **Dashboard** | Live-style readouts, viscometer connection, timed test (data interval, number of points, reminders), manual entry with full-scale range and shear-rate preview, spindle/speed advisor, readings table and live plot |
| **Data table** | Every reading of the session with its source and QC flags; delete rows; save/load sessions; CSV import; Excel, CSV and Origin export |
| **Notebook** | Instrument ID and serial, calibration date and interval, protocol, operator, sample preparation, temperature set point, measurement checklist, PC clock check, and the audit trail |
| **Plots** | Viscosity vs time, viscosity vs shear rate (log–log with a power-law fit), % torque vs time (10 % and 100 % limits marked), temperature vs time |
| **Statistics** | Mean, standard deviation, minimum and maximum per quantity; torque flags; Newtonian, power-law, Bingham, Herschel–Bulkley, Cross and Carreau fits with 95 % intervals and AICc ranking (only fitted when the data support them) |
| **Compare** | Repeatability per sample and speed (s, CV, u, U95), flow curves of every sample, hysteresis of up/down sweeps |
| **Instrument** | Simulation, replay and documented-protocol sources; read-only-by-default terminal and raw capture |
| **About** | Author, lab, sources and environment |

Calculations use the formulas and spindle constants of the DV1 manual, Appendix D:
full-scale range = TK × SMC × 10 000 / RPM and shear rate = SRC × RPM. Each reading is
checked against viscosity = % torque / 100 × full-scale range, to catch transcription errors.
Each reading also gets automatic QC flags: torque window, temperature set point, late entry,
double entry, and calibration overdue. Flow models are fitted on log residuals.
`docs/EQUATION_REGRESSION_REPORT.md` compares every formula and model with independent
calculations. Model parameters describe the measured shear-rate range only; they are not
measurements.

Sessions are saved in format 2 (readings, notebook, audit trail, export revision). Sessions
saved by 2.0.0 still open. Saving is atomic, and the open session is mirrored to a local
recovery file, which is offered back after an unexpected exit.

### Exports

- **Send to Origin** — one workbook with a column pair per trace, the readings table and a
  Results sheet, plus a styled graph per plot (colour-blind-safe palette, log axes, the fit in
  its data colour, legend placed clear of the data). Every send adds to the same Origin
  project; the arrow menu saves the project (.opju) or closes Origin. Without Origin,
  **Write LabTalk package** produces CSVs and a script that rebuilds the project on any PC
  with Origin (drag `AeroLab_build.ogs` into Origin).
- **Export to Excel** — Summary, per-analysis sheet with results and readings, native Excel
  charts, and a Provenance sheet.
- **Save figures** — 300 dpi PNGs; **Export to CSV** — the raw readings.

### Keyboard

| Keys | Action |
|---|---|
| Ctrl+Return | Add reading |
| Enter (or numpad Enter) | Viscosity → % torque → temperature → add reading |
| Ctrl+Shift+N | Next sample in the batch queue |
| Ctrl+Shift+L / Ctrl+Shift+H | Large touch-friendly controls / high-contrast readout |
| Ctrl+Z / Ctrl+Y | Undo / redo (add, delete, load, clear) |
| Ctrl+O / Ctrl+S | Load / save session |
| Ctrl+E / Ctrl+Shift+O | Export to Excel / send to Origin |
| F5 / Shift+F5 | Start / stop a timed run |
| Ctrl+K | Command palette |
| Ctrl+1 … Ctrl+8 | Go to a page |

## Setup (Windows)

1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. In this folder: `pip install -r requirements.txt`
3. Run: `python main.py`

`python main.py --selftest` checks the whole application without opening a window;
`python -m pytest tests` runs the test suite.

## Building the executable and installer

```
.\build.ps1
```

This runs the tests, builds `dist\DV1Logger\` with PyInstaller, runs the built exe's
self-test, packs a portable zip and compiles `installer_output\DV1Logger-Setup-<version>.exe`
with Inno Setup (`winget install JRSoftware.InnoSetup` if it is missing).

## Project structure

```
brookfield_dv1_logger/
├── main.py                  entry point (splash, --selftest, --version)
├── selftest.py              headless check used on packaged builds
├── core/
│   ├── analysis.py          spindle/model constants, FSR and shear rate, statistics, power-law fit
│   ├── data_io.py           sessions (JSON), CSV and Excel export
│   ├── figures.py           the four figures, the Origin book and the Excel report
│   └── serial_interface.py  raw serial link and notes on the DV1 protocol gap
├── ui/
│   ├── main_window.py       the application window (pages, menus, undo/redo)
│   ├── widgets.py           collapsible section
│   └── resources.py         version, author, asset paths
├── labkit/                  vendored shared interface — edit ..\..\labkit and run sync.py
├── tests/                   pytest suite
├── DV1Logger.spec, build.ps1, installer.iss
└── docs/
```

## Data source / accuracy notes

Spindle and model constants (SMC, SRC, TK) in `core/analysis.py` were transcribed from the
DV1 Operating Instructions (M14-023-A0416), Appendix D. For spindles or accessories not
listed there, or another manual revision, check the constants against your printed manual
before trusting calculated full-scale range or shear-rate values.
