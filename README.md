# Brookfield DV1 Viscosity Logger

A Windows desktop app (PySide6) for logging, plotting, and analyzing viscosity
readings taken from a Brookfield AMETEK DV1 Digital Viscometer.

## Important: about live instrument communication

Before relying on this for lab work, please read this section.

Brookfield's official DV1 Operating Instructions manual (M14-023-A0416)
states that the DV1 talks to a PC over its USB-B port only via Brookfield's
own **Wingather SQ** software, and does not publish an open ASCII command set
for the DV1 the way it does for some other models (e.g. DV2+Pro, DV-II+,
DV2T/DV3T). I looked for a public DV1-specific serial protocol document and
could not find one, and did not want to guess at command bytes to send to
real lab hardware.

Because of that, **this app's "Log Reading" tab is manual entry**: you read
the value off the DV1's display and type it in. That is fully functional
today -- logging, plotting, statistics, and Excel/CSV export all work from
manually-entered data.

There is also a **"Serial (Discovery)" tab** that gives you a raw,
protocol-agnostic serial connection (port list, connect/disconnect, and a
terminal to send/receive raw text) so you can experiment once you have real
protocol documentation, or use it directly if you actually have a DV2+Pro /
DV-II+ / DV2T / DV3T (those do have documented ASCII protocols).

**To get live auto-logging working:** contact Brookfield/AMETEK technical
support and ask for the "DV1 RS-232/USB Interface Command Reference" (or
equivalent) for your specific instrument/firmware. Once you have verified
commands, they go into `core/serial_interface.py` in the `DV1Protocol` class
(there's a docstring there explaining exactly where). Send me that
documentation and I can wire it up directly.

## What's included

- **Log Reading tab**: manual entry of viscosity, % torque, temperature, spindle,
  speed, and model. Automatically calculates Full Scale Range (FSR) and Shear
  Rate using the official formulas and spindle constants from Appendix D of
  the DV1 manual, and flags readings outside Brookfield's recommended
  10-100% torque range.
- **Data Table tab**: all readings logged this session, with Excel and CSV export.
- **Plots tab**: Viscosity vs Time, Viscosity vs Shear Rate, % Torque vs Time,
  Temperature vs Time.
- **Statistics tab**: mean/stdev/min/max per field, plus counts of
  out-of-recommended-range torque readings.
- **Serial (Discovery) tab**: raw port connect + terminal for protocol testing.

## Setup (Windows)

1. Install Python 3.10+ from python.org (check "Add to PATH" during install).
2. Open a terminal in this folder and run:
   ```
   pip install -r requirements.txt
   ```
3. Run the app:
   ```
   python main.py
   ```

## Building a standalone .exe (optional)

```
pip install pyinstaller
pyinstaller --onefile --windowed --name DV1Logger main.py
```
The `.exe` will be built for the OS you run this command on -- run it on a
Windows machine to get a Windows executable.

## Project structure

```
brookfield_dv1_logger/
├── main.py                  # entry point
├── ui/
│   └── main_window.py       # all GUI code
├── core/
│   ├── analysis.py          # spindle/model constants, FSR/shear-rate math, stats
│   ├── data_io.py           # Excel/CSV export/import
│   └── serial_interface.py  # raw serial link + notes on the DV1 protocol gap
├── requirements.txt
└── README.md
```

## Data source / accuracy notes

Spindle and model constants (SMC, SRC, TK) in `core/analysis.py` were
transcribed from Brookfield AMETEK's official DV1 Operating Instructions
manual (M14-023-A0416), Appendix D. If you use spindles/accessories not
listed there, or a different manual revision, double-check the constants
against your own printed manual before trusting calculated FSR/shear-rate
values -- transcription errors are possible.
