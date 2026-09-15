import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLBACKEND", "Agg")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    return app


def make_readings(n_value: float = 0.62, k_value: float = 4200.0, spindle: str = "SC4-18",
                  rpms=(1.0, 2.0, 5.0, 10.0, 20.0, 50.0), product: str = "Gel", batch: str = "B1"):
    """Readings that follow an exact power law, so a fit must give n and K back."""
    from core.analysis import Reading, shear_rate_per_sec

    t0 = datetime(2026, 1, 1, 12, 0, 0)
    out = []
    for i, rpm in enumerate(rpms):
        rate = shear_rate_per_sec(spindle, rpm)
        viscosity = k_value * rate ** (n_value - 1.0) if rate else 1000.0
        out.append(Reading(timestamp=t0 + timedelta(seconds=30 * i), viscosity_cp=viscosity,
                           percent_torque=15.0 + 10 * i, temperature_c=23.0 + 0.1 * i, rpm=rpm,
                           spindle=spindle, model="LVDV1", product=product, batch=batch))
    return out


@pytest.fixture
def readings():
    return make_readings()


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    """A MainWindow with its settings isolated and every modal dialog answered automatically."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "settings"))
    dialogs: list[tuple[str, str]] = []

    def answer(_parent, title, text, *args, **kwargs):
        dialogs.append((title, text))
        return QMessageBox.Yes

    for name in ("information", "warning", "critical", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(answer))

    from ui.main_window import MainWindow
    w = MainWindow()
    w.dialogs = dialogs
    w.show()
    yield w
    w.close()


def pump(qapp, seconds: float = 0.05) -> None:
    import time
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
