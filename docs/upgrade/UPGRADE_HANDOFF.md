# Handoff: brookfield_dv1_logger upgrade (repository 05)

| | |
|---|---|
| Local path | `E:\Lab Apps\brookfield_dv1_logger\brookfield_dv1_logger` |
| Branch | `upgrade/05-brookfield`, from `feature/licensing` at `11bd09c` (pushed; not merged into main) |
| Version | 2.0.0 → 2.1.0 (`ui/resources.py`, `installer.iss`) |
| labkit | 1.1.0 → 1.2.0 (`sync.py --apply --test --only brookfield_dv1_logger`: synced, 44 passed; backup in `.labkit-backup/20261115-115508`) |
| Tests | `py -3 -m pytest -q -p no:cacheprovider` (offscreen): **189 passed** (44 at baseline: +40 hostile files, +40 oracle, +34 instruments, +28 UI, +3 exports) |
| Builds | PyInstaller onedir: frozen `--selftest` passed. `DV1Logger-Setup-2.1.0.exe` compiled, SHA-256 `07795320C7E96444463D3DE0A6799FB48282163C3F8FF515A742DF7526C88D83`; not installed |

## Targets (05 prompt): before → now

| # | Target | Before | Now |
|---|---|---|---|
| 1 | Structured manual capture | PARTIAL | DONE: Enter/numpad chain, large controls, batch queue, sample ID/operator/prep/notes, late-entry flag, QC flags, audit trail, clock check, configurable reminder beep |
| 2 | Adapter architecture | MISSING | DONE: simulation, replay, documented protocols. DV1 live **unavailable by design**, and DV1 definitions are refused |
| 3 | Rheology fits | PARTIAL | DONE: six models, support checks, 95 % CIs, AICc, residual diagnostics, range/geometry/Newtonian-SRC warnings |
| 4 | Comparison and notebook | MISSING | DONE: Compare page (s, CV, u, U95, flow curves, hysteresis); notebook with traceability fields; revisioned exports with provenance; no compliance claim |
| 5 | UX | PARTIAL | DONE: high-contrast readout, constants with source, checklist, trend selector, export preview, crash recovery, friendly errors |
| 6 | Security/test | MISSING | DONE: corrupt-file validation, read-only serial with per-connection authorisation, recovery, packaging build, simulated-reading tests |
| Acc. | Independent model checks; hardware cannot receive unsupported commands; old sessions preserved; measured vs transcribed labelled | — | All covered by tests (see `UPGRADE_TEST_REPORT.md`) |

## Defects fixed (all with a test that failed first)

1. `core/data_io.py` (`import_from_csv`, formerly line 80, `pd.read_csv(path)`): a wider row shifted every value. Now validated record by record (`_clean_records`), and wider rows are refused with their line number.
2. Excel/CSV formula injection from notes (`guard_text`).
3. Sessions: locale encoding, non-atomic save, no validation.
4. `nan`/`inf` accepted on entry.
5. Deferred recovery check firing on a deleted window (`QTimer.singleShot(0, self, ...)`).

## Left out, with blockers

- **DV1 live logging**: needs Brookfield's DV1 command reference and consent. Not available, so it stays disabled (README and `docs/PROTOCOL_DEFINITIONS.md`).
- **Real-instrument validation**: needs hardware and real anonymised session files. None were supplied.
- **Code signing**: needs a purchased certificate.
- **Checking the constants against the printed manual**: the manual is not in the repository.

## Known limitations

- Undoing a session load restores the readings but not the previous notebook.
- 2.0.0 cannot open format-2 sessions.
- Cross and Carreau fix η∞ at 0.
- CIs are linearised.
- pyserial's default DTR/RTS on open was left unchanged.

## Next steps

1. Review on a real DV1 with manually transcribed readings, and check the QC tolerance (2 % / 0.1 % FS) against the lab's experience.
2. Optionally have Codex do a read-only review of `core/rheology.py` and `core/instruments.py` (not run in this round).
3. Merge into main after the owner's review.

## Rollback

- Code: `git switch feature/licensing`. The branch leaves `feature/licensing` untouched.
- labkit only: from `E:\Lab Apps\labkit`, run `py -3 sync.py --restore brookfield_dv1_logger`.
- Data: 2.1.0 never rewrites a 2.0.0 file unless the user saves over it. Keep copies of shared sessions in version 1 format if 2.0.0 users need them.
