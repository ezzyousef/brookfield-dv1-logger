# Implementation plan (as carried out)

The milestones are in priority order. Each one was committed separately on `upgrade/05-brookfield`, with its tests.

| Milestone | Scope | Commit |
|---|---|---|
| 0 | labkit 1.1.0 → 1.2.0 via `sync.py --apply --test --only brookfield_dv1_logger`; `.labkit-backup/` ignored | `a91d8ce` |
| A | Importer correctness and security: record-level CSV validation before pandas (supercap-reviewed design: header found by its `timestamp` cell, title lines dropped, trailing empty fields accepted, wider rows refused with their line), CSV re-import, session format 2 (notebook, audit, revision) with legacy loading, atomic UTF-8 save, size/binary/type validation, formula guard on exports | `afd16f0` |
| B | Science and instrument safety: serial write barrier; simulation/replay/documented-protocol adapters (DV1 refused); six flow models with support checks, t-based CIs, AICc, residual diagnostics; QC flags; replicates and hysteresis; 40 oracle tests | `3668566` |
| C | Workflow and UI: notebook page (traceability, checklist, clock, audit trail), Compare page, flow-model table, Instrument page with sources and a read-only terminal, keyboard-first entry, large controls, high-contrast readout, batch queue, trend selector, constants display, crash recovery, export preview with provenance and revisions, friendly errors | milestone C commit |
| E | Version 2.1.0 (code, installer, spec bundles `examples/`), CHANGELOG, README, equation report, protocol guide, upgrade reports, extended self-test | final commit |

## Design choices

- **No SciPy at runtime.** The app's Levenberg–Marquardt and Student-t are about 150 lines of numpy and math. SciPy is used only by the tests, as the independent oracle. This keeps the installer the same size.
- **Log-residual objective for every model.** Readings span decades, and the same objective makes AICc comparable between models.
- **Cross/Carreau with η∞ = 0.** DV1 data rarely reach a high-shear plateau, and a free η∞ would be unidentifiable.
- **The write barrier sits in `RawSerialLink`,** the only place bytes leave the app. The UI and the adapters cannot bypass it.
- **DV1 definitions are refused by name.** This is a deliberate, conservative rule. Lifting it needs a reviewed code change.
- **Session format 2** is a JSON object, and the version 1 bare list is still read. The app does not write version 1 (documented in the CHANGELOG).
