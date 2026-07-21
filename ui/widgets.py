"""Small reusable Qt widgets shared across the DV1 Logger's tabs."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QToolButton,
)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.figure import Figure

from . import theme


class PlotCanvas(FigureCanvas):
    def __init__(self, figsize=(6, 3.2)):
        fig = Figure(figsize=figsize)
        super().__init__(fig)
        self.ax = fig.add_subplot(111)

    def plot_xy(self, x, y, xlabel="", ylabel="", title="", marker="o"):
        self.ax.clear()
        if x and y:
            self.ax.plot(x, y, marker=marker, linestyle="-", color=theme.BLUE)
        self.ax.set_xlabel(xlabel)
        self.ax.set_ylabel(ylabel)
        self.ax.set_title(title)
        self.ax.grid(True, alpha=0.3, color=theme.GRID)
        self.ax.set_facecolor(theme.SURFACE)
        self.figure.patch.set_facecolor(theme.SURFACE)
        self.figure.tight_layout()
        self.draw()


class PlotPanel(QWidget):
    """A PlotCanvas with matplotlib's built-in navigation toolbar attached
    above it -- gives every plot in the app box-select zoom, click-drag
    panning, scroll/toolbar zoom, a Home button to reset to the full-data
    view, Back/Forward through zoom history, and a Save-image button.
    Exposes the same `ax`/`figure`/`draw()`/`plot_xy()` surface as
    PlotCanvas via attribute delegation, so existing call sites
    (`self.plot_canvas.plot_xy(...)`) keep working unchanged once the
    constructor call is switched from PlotCanvas() to PlotPanel()."""

    def __init__(self, figsize=(6, 3.2), parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas = PlotCanvas(figsize=figsize)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def __getattr__(self, name):
        return getattr(self.canvas, name)


class ToastNotification(QWidget):
    """A transient, non-blocking confirmation shown bottom-right and
    auto-dismissed -- used for routine confirmations ("Exported",
    "Reading added", "Session saved") where a QMessageBox the user has to
    click through is disproportionate friction. Genuinely destructive-
    action confirmations (e.g. "Delete these rows?") still use QMessageBox."""

    def __init__(self, parent, text: str, kind: str = "success", duration_ms: int = 2600):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        accent = {"success": theme.GOOD, "error": theme.WARN}.get(kind, theme.BLUE)
        label = QLabel(f"  {text}  ")
        label.setWordWrap(True)
        label.setMaximumWidth(340)
        label.setStyleSheet(
            f"background-color: {theme.INK}; color: white; border-radius: 4px; "
            f"border-left: 4px solid {accent}; padding: 8px 12px; font-weight: 600;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        self.adjustSize()
        self._reposition()
        self.show()
        QTimer.singleShot(duration_ms, self.close)

    def _reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        top_level = parent.window()
        geo = top_level.geometry()
        x = geo.x() + geo.width() - self.width() - 24
        y = geo.y() + geo.height() - self.height() - 40
        self.move(max(x, 0), max(y, 0))


def show_toast(parent, text: str, kind: str = "success") -> None:
    ToastNotification(parent, text, kind)


class CollapsibleSection(QWidget):
    """A titled container that can be expanded/collapsed by clicking its
    header -- used to let a dense tab (the Dashboard packs a lot in) be
    tidied by collapsing sections not currently needed, without losing
    them. Independently toggleable, not an accordion."""

    toggled = Signal(bool)

    def __init__(self, title: str, parent=None, content_widget: QWidget | None = None,
                 start_expanded: bool = True):
        super().__init__(parent)
        self.title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(start_expanded)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if start_expanded else Qt.ArrowType.RightArrow)
        self.toggle_btn.setStyleSheet(
            f"QToolButton {{ border: none; font-weight: 600; color: {theme.INK_DIM}; "
            f"padding: 4px 0; background: transparent; }}"
        )
        self.toggle_btn.clicked.connect(self._on_toggled)
        outer.addWidget(self.toggle_btn)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(14, 4, 0, 4)
        self.body.setVisible(start_expanded)
        outer.addWidget(self.body)

        if content_widget is not None:
            self.body_layout.addWidget(content_widget)

    def _on_toggled(self):
        expanded = self.toggle_btn.isChecked()
        self.body.setVisible(expanded)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggled.emit(expanded)

    def addWidget(self, w):
        self.body_layout.addWidget(w)

    def addLayout(self, layout):
        self.body_layout.addLayout(layout)
