"""`DV1Logger.exe --selftest`: exercise the whole application without a visible window.

Used to verify a packaged build: it loads every module, builds every figure and export
from synthetic readings, opens every page and toggles the theme. Prints plain ASCII,
because a frozen Windows console uses the legacy code page.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


def run_selftest() -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    failures: list[str] = []

    def check(label: str, ok: bool, detail: str = "") -> None:
        print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"  ({detail})"))
        if not ok:
            failures.append(label)

    try:
        from core.analysis import Reading, power_law_fit
        from core.figures import PLOT_KINDS, build_figure, excel_report, origin_book
        from labkit.excel import write_workbook
        from labkit.origin import origin_available, write_labtalk_package
        from ui.resources import APP_VERSION
    except Exception as exc:                                    # noqa: BLE001
        print(f"FAIL  imports: {exc}")
        return 1
    frozen = "frozen" if getattr(sys, "frozen", False) else "source"
    print(f"Brookfield DV1 Viscosity Logger {APP_VERSION} ({frozen} build)\n")

    t0 = datetime(2026, 1, 1, 12, 0, 0)
    readings = [Reading(timestamp=t0 + timedelta(seconds=30 * i), viscosity_cp=2000.0 / (1 + i) ** 0.3,
                        percent_torque=40.0 + i, temperature_c=23.0 + 0.1 * i, rpm=rpm,
                        spindle="SC4-18", model="LVDV1", product="Gel", batch="B1")
                for i, rpm in enumerate([1.0, 2.0, 5.0, 10.0, 20.0, 50.0])]
    fit = power_law_fit(readings)
    check("power-law fit on synthetic shear-thinning data", fit is not None and fit["n"] < 1,
          str(fit))
    specs = [build_figure(k, readings) for k in PLOT_KINDS]
    check(f"{sum(not s.is_empty for s in specs)} of {len(PLOT_KINDS)} figures have data",
          all(not s.is_empty for s in specs))

    with tempfile.TemporaryDirectory() as tmp:
        try:
            path = write_workbook(excel_report(readings, version=APP_VERSION), Path(tmp) / "t.xlsx")
            check(f"Excel workbook written ({path.stat().st_size // 1024} kB)", path.stat().st_size > 8000)
        except Exception as exc:                                # noqa: BLE001
            check("Excel workbook", False, str(exc))
        try:
            result = write_labtalk_package([origin_book(readings)], Path(tmp) / "origin")
            check(f"Origin LabTalk package written ({result.graphs} graphs)", result.graphs >= 4)
        except Exception as exc:                                # noqa: BLE001
            check("Origin package", False, str(exc))
    print(f"note  {origin_available()[1]}")

    try:
        from PySide6.QtWidgets import QApplication
        from ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        app.setStyle("Fusion")
        window = MainWindow()
        window.show()
        window.readings.extend(readings)
        window.history.record("self-test readings")
        window._on_readings_changed()
        for key in window.page_keys:
            window.go_to(key)
            for _ in range(5):
                app.processEvents()
        built = sum(window.is_page_built(k) for k in window.page_keys)
        check(f"interface: {built} of {len(window.page_keys)} pages built", built == len(window.page_keys))
        window.toggle_theme()
        window.toggle_theme()
        check("no duplicate keyboard shortcuts", window.shortcut_conflicts() == [], str(window.shortcut_conflicts()))
        window.undo()
        check("undo removes the self-test readings", len(window.readings) == 0)
        window.close()
    except Exception as exc:                                    # noqa: BLE001
        check("interface", False, f"{type(exc).__name__}: {exc}")

    print()
    if failures:
        print(f"SELF-TEST FAILED - {len(failures)} problem(s): {', '.join(failures)}")
        return 1
    print("SELF-TEST PASSED - this build is working.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(run_selftest())
