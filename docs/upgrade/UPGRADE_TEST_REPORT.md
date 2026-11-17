# Test report: brookfield_dv1_logger 2.1.0

Environment: Windows 11, Python 3.14.5, PySide6 6.11.1, numpy 2.4.6, pandas 3.0.3, SciPy 1.18.0 (tests only), pyserial 3.5. Date: 2026-11-15.

## Commands

```
set QT_QPA_PLATFORM=offscreen & set MPLBACKEND=Agg
py -3 -m pytest -q -p no:cacheprovider        # full suite
py -3 selftest.py                             # source self-test
py -3 -m PyInstaller DV1Logger.spec --noconfirm
dist\DV1Logger\DV1Logger.exe --selftest       # frozen self-test
ISCC.exe /DMyAppVersion=2.1.0 installer.iss
```

## Results

| Stage | Tests | Result |
|---|---|---|
| Baseline (`feature/licensing` @ 11bd09c) | 44 | 44 passed (78 s); self-test passed |
| After labkit 1.2.0 sync (`sync.py --apply --test`) | 44 | 44 passed |
| After milestone A (importers) | 85 | 85 passed |
| After milestone B (adapters, rheology) | 159 | 159 passed |
| After the 2.1.0 build | 189 | 189 passed in 50 s |
| Final, after the Codex review | **224** | **224 passed in 53 s**; source self-test passed (12 checks); frozen exe self-test passed (12 checks) |

New test files:

- `test_hostile_files.py` (40): CSV ragged rows (including the three supercap review cases), empty, binary, oversized and UTF-16 files, re-import, formula guard; sessions in 13 corrupt forms, truncated, oversized, binary, the legacy 2.0.0 fixture, NaN, UTF-8, atomic save, and embedded instructions kept as data.
- `test_oracle_rheology.py` (40): see `docs/EQUATION_REGRESSION_REPORT.md`.
- `test_instruments.py` (34): the write barrier with a simulated port, DV1 refusal, protocol validation, simulation, and replay.
- `test_window_upgrade.py` (28): the UI end to end, offscreen.
- `test_exports.py` +3: Excel formula injection, provenance and model rows, comparison figure.

## Regression tests that failed before their fix

- The CSV row wider than the header: reproduced on the old code (values shifted, timestamp = 100), then fixed.
- Excel formula injection: `test_excel_report_never_turns_a_note_into_a_formula` failed with the old `data_io.py` stashed.
- The deferred recovery check on a deleted window raised a RuntimeError in the suite, then was fixed with the context-object `singleShot`.

## Hardware safety evidence

Every serial test uses `FakeSerial`, which records each byte. With no authorisation the following write **0 bytes**: connect, read line, read-all, auto-capture, terminal Send (blocked with a message), the simulation and replay sources, a listen-only protocol adapter, a protocol adapter with commands defined, and DV1 definitions (refused). Bytes are written only after `authorize_writes(reason)` on an open port, and only the documented query or the typed line. Disconnecting ends the permission.

## Performance

- Model comparison: 2 ms for 11 points and 3 ms for 220 points (six models).
- The test suite went from 950 s (unreleased intermediate state) to 50 s after closed windows were deleted.

## Screenshots

`docs/upgrade/screenshots/`: dashboard, notebook, statistics, compare, instrument pages. They are offscreen captures from the synthetic example session, dark theme.

## Not run or not verified

- No real DV1, instrument or serial port was used.
- The installer was compiled but not installed or uninstalled.
- High-DPI and screen-reader checks were not done beyond the accessible names that were set.
- The light theme was not captured (it is exercised by `test_every_page_builds_in_both_themes`).
- Spindle constants could not be compared with the printed manual.
- An independent Codex review was run afterwards; its 9 findings are regression-tested in `test_codex_review.py` (35 tests) and fixed (see `UPGRADE_HANDOFF.md`).
