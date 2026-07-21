import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication, QSplashScreen
from ui.resources import load_app_icon, asset_path, AUTHOR_NAME
from ui.theme import apply_theme


def _set_windows_app_user_model_id() -> None:
    """Without this, Windows often shows a generic/blank icon for a
    Python-packaged app in the taskbar and Task Manager -- it groups
    windows by process/AppUserModelID rather than by the exe's embedded
    icon resource alone, and a frozen Python app doesn't get one by
    default. Setting an explicit ID here (before any window is shown)
    tells Windows to treat this as its own distinct app and use the icon
    set via setWindowIcon() everywhere, not just on the window itself.
    No-op and safe on non-Windows platforms."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "EML.DV1Logger.ViscosityLogger.1"
        )
    except Exception:
        pass


def _show_splash(app: QApplication) -> QSplashScreen:
    """A window that paints almost instantly, shown BEFORE the slower part
    of startup (importing ui.main_window pulls in matplotlib/pandas).
    Without something on screen during that wait, Windows shows its own
    "app isn't responding yet" placeholder instead. Falls back to a small
    solid-color pixmap if the EML logo asset isn't found, so this never
    fails startup over a missing image."""
    pixmap = QPixmap(asset_path("eml_logo.png"))
    if pixmap.isNull():
        pixmap = QPixmap(360, 220)
        pixmap.fill(QColor("#F3F4F6"))
    else:
        pixmap = pixmap.scaledToWidth(280, Qt.TransformationMode.SmoothTransformation)
    splash = QSplashScreen(pixmap)
    splash.showMessage(
        "Loading Brookfield DV1 Viscosity Logger…",
        Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
        QColor("#1B1E22"),
    )
    splash.show()
    app.processEvents()  # force the splash to actually paint now, before the slow import below
    return splash


def _prewarm_heavy_imports(app: QApplication) -> None:
    """Import the slow C-extension-heavy libraries this app depends on ONE
    AT A TIME, pumping the Qt event loop (processEvents) between each --
    a single monolithic `from ui.main_window import MainWindow` blocks the
    message loop for its entire cold-import duration in one uninterrupted
    stretch, which is long enough that Windows' DWM can treat the splash
    window itself as hung. Splitting the import into pieces with
    processEvents() in between keeps the message pump alive throughout."""
    modules = [
        "numpy", "pandas", "matplotlib", "matplotlib.backends.backend_qtagg",
        "openpyxl", "serial",
    ]
    for module_name in modules:
        try:
            __import__(module_name)
        except ImportError:
            pass
        app.processEvents()


def main():
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("Brookfield DV1 Viscosity Logger")
    app.setOrganizationName(AUTHOR_NAME)
    app.setApplicationVersion("1.0.0")
    app.setWindowIcon(load_app_icon())
    # Fusion style uses Qt's own popup rendering for QComboBox instead of the
    # native Windows popup, which avoids a known Windows-specific bug where a
    # combo box's dropdown can close itself immediately on click (race
    # between the native popup opening and the mouse-release event).
    app.setStyle("Fusion")
    apply_theme(app)

    splash = _show_splash(app)
    _prewarm_heavy_imports(app)

    from ui.main_window import MainWindow  # deferred: see _show_splash/_prewarm_heavy_imports
    window = MainWindow()
    app.processEvents()
    window.show()
    splash.finish(window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
