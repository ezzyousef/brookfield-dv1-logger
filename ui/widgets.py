"""Widgets specific to the DV1 Logger.

Everything general — cards, tiles, toasts, plot canvas, command palette — comes from
labkit so this application looks like the rest of the lab's tools. What remains here is
the collapsible section the dense Dashboard relies on.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A titled container that expands or collapses when its header is clicked.

    Lets the Dashboard, which packs a lot onto one page, be tidied by folding away the
    sections not needed right now without losing them. Sections toggle independently.
    Colours come from the shared stylesheet, so it follows the light and dark themes.
    """

    toggled = Signal(bool)

    def __init__(self, title: str, parent=None, content_widget: QWidget | None = None,
                 start_expanded: bool = True):
        super().__init__(parent)
        self.title = title
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        self.toggle_btn = QToolButton()
        self.toggle_btn.setObjectName("CollapsibleHeader")
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(start_expanded)
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if start_expanded else Qt.ArrowType.RightArrow)
        self.toggle_btn.setStyleSheet("QToolButton#CollapsibleHeader { border: none; background: transparent;"
                                      " font-weight: 650; font-size: 14px; padding: 4px 0; }")
        self.toggle_btn.clicked.connect(self._on_toggled)
        outer.addWidget(self.toggle_btn)

        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 4, 0, 4)
        self.body.setVisible(start_expanded)
        outer.addWidget(self.body)
        if content_widget is not None:
            self.body_layout.addWidget(content_widget)

    @property
    def expanded(self) -> bool:
        return self.toggle_btn.isChecked()

    def _on_toggled(self):
        expanded = self.toggle_btn.isChecked()
        self.body.setVisible(expanded)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.toggled.emit(expanded)

    def addWidget(self, w):  # noqa: N802 - Qt naming
        self.body_layout.addWidget(w)

    def addLayout(self, layout):  # noqa: N802 - Qt naming
        self.body_layout.addLayout(layout)
