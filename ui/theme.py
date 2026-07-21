"""App-wide visual design system for the DV1 Logger.

Instrument-panel look (closer to lab-instrument control software than a
consumer app), built around the blue/teal/orange identity already used by
the Dashboard tab and app icon. Applied once at startup via apply_theme();
individual widgets can still layer their own inline styles on top (e.g. the
live readout boxes, the "Reading due" flash) for state that changes at
runtime rather than being a fixed part of the chrome.
"""
from PySide6.QtGui import QFont

PANEL = "#EEF2F8"
SURFACE = "#FFFFFF"
SURFACE_RAISED = "#E4EAF3"
INK = "#1B1E22"
INK_DIM = "#5B6472"
BLUE = "#1c4b8c"
BLUE_DARK = "#0f2f5c"
BLUE_LIGHT = "#3f6bb0"
TEAL = "#00969a"
ORANGE = "#ff8c3c"
GOOD = "#2e8b3d"
WARN = "#b03a2e"
GRID = "#DCE3ED"
BORDER = "#C3CCDA"
ON_ACCENT = "#FFFFFF"

BLUE_HOVER, BLUE_PRESSED = "#163f75", "#0f2f5c"
GOOD_HOVER, GOOD_PRESSED = "#256f32", "#1c5726"
WARN_HOVER, WARN_PRESSED = "#8f2f25", "#74251d"

UI_FONT_FAMILY = "Segoe UI"
MONO_FONT_FAMILY = "Consolas"

QSS = f"""
* {{
    font-family: "{UI_FONT_FAMILY}";
    color: {INK};
}}
QWidget {{
    background-color: {PANEL};
}}
QMainWindow, QTabWidget::pane {{
    background: {PANEL};
    border: none;
}}
QTabBar::tab {{
    background: {SURFACE_RAISED};
    color: {INK_DIM};
    padding: 8px 16px 7px 12px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    margin-right: 3px;
}}
QTabBar::tab:hover {{
    background: {SURFACE};
    color: {INK};
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {INK};
    border: 1px solid {BORDER};
    border-top: 3px solid {BLUE};
    padding-top: 6px;
    margin-bottom: -1px;
    font-weight: 600;
}}
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-left: 4px solid {BLUE};
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 12px;
    padding-left: 4px;
    font-weight: 600;
    color: {INK_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {INK_DIM};
}}
QLabel {{
    background: transparent;
}}
QPushButton {{
    background: {BLUE};
    border: 1px solid {BLUE_PRESSED};
    border-radius: 4px;
    padding: 6px 14px;
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton:hover {{
    background: {BLUE_HOVER};
}}
QPushButton:pressed {{
    background: {BLUE_PRESSED};
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton:disabled {{
    background: {SURFACE_RAISED};
    color: {INK_DIM};
    border-color: {BORDER};
}}
QPushButton#exportButton, QPushButton#runButton {{
    background: {GOOD};
    border-color: {GOOD_PRESSED};
}}
QPushButton#exportButton:hover, QPushButton#runButton:hover {{
    background: {GOOD_HOVER};
}}
QPushButton#exportButton:pressed, QPushButton#runButton:pressed {{
    background: {GOOD_PRESSED};
}}
QPushButton#stopButton, QPushButton#deleteButton {{
    background: {WARN};
    border-color: {WARN_PRESSED};
}}
QPushButton#stopButton:hover, QPushButton#deleteButton:hover {{
    background: {WARN_HOVER};
}}
QPushButton#stopButton:pressed, QPushButton#deleteButton:pressed {{
    background: {WARN_PRESSED};
}}
QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 3px 6px;
    color: {INK};
    selection-background-color: {BLUE};
}}
QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QLineEdit:focus {{
    border: 2px solid {BLUE};
    padding: 2px 5px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    color: {INK};
    selection-background-color: {BLUE};
    selection-color: {ON_ACCENT};
}}
QTextEdit, QPlainTextEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 3px;
    color: {INK};
    font-family: "{MONO_FONT_FAMILY}";
    font-size: 10pt;
}}
QTableView, QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: {PANEL};
    gridline-color: {GRID};
    border: 1px solid {BORDER};
    font-family: "{MONO_FONT_FAMILY}";
    selection-background-color: {BLUE};
    selection-color: {ON_ACCENT};
}}
QHeaderView::section {{
    background-color: {SURFACE_RAISED};
    color: {INK_DIM};
    padding: 4px;
    border: 1px solid {BORDER};
    border-bottom: 2px solid {BLUE};
    font-family: "{UI_FONT_FAMILY}";
}}
QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:hover {{
    background-color: {BLUE};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: {SURFACE};
    border: none;
}}
QScrollBar::handle {{
    background: {BORDER};
    border-radius: 3px;
}}
QScrollBar::handle:hover {{
    background: {BLUE};
}}
QToolButton {{
    background: transparent;
    border: none;
}}
QMessageBox {{
    background-color: {SURFACE};
}}
"""


def apply_theme(app) -> None:
    app.setStyleSheet(QSS)
    app.setFont(QFont(UI_FONT_FAMILY, 9))
