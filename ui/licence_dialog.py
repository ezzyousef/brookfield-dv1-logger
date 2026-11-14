"""Help > Licence: the installed licence's status, this computer's id and offline activation.

Nothing here uses the network. Licensing is not enforced (core.licensing.ENFORCE is False),
so the dialog only reports; every feature stays available whatever it says.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

from core import licensing
from labkit.licence import MAX_BYTES
from labkit.qt.widgets import Card


def status_sentence(st) -> str:
    """One plain sentence describing a licence Status."""
    if st.ok:
        claims = st.claims
        who = claims.get("organisation") or claims.get("name") or ""
        text = f"Licensed ({claims.get('kind', 'licence')}), serial {claims.get('serial', '?')}"
        if who:
            text += f", for {who}"
        if st.expires:
            text += f", valid until {st.expires.isoformat()}"
        return text + "."
    reason = st.reason or "No licence installed."
    if not licensing.ENFORCE:
        reason += " Every feature is available; no licence is required."
    return reason


class LicenceDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, folder=None, notify=None):
        super().__init__(parent)
        self.setWindowTitle("Licence")
        self.setModal(True)
        self.setMinimumWidth(520)
        self._folder = folder
        self._notify = notify

        card = Card("Licence")
        self.edition = QLabel()
        self.edition.setObjectName("PageTitle")
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.warnings = QLabel()
        self.warnings.setWordWrap(True)
        self.warnings.setObjectName("Hint")
        card.body.addWidget(self.edition)
        card.body.addWidget(self.status_label)
        card.body.addWidget(self.warnings)

        caption = QLabel("This computer's &device id")
        caption.setObjectName("Hint")
        self.device = QLineEdit(licensing.device_id())
        self.device.setReadOnly(True)
        self.device.setAccessibleName("This computer's device id")
        self.device.setToolTip("Send this id (or the activation request) to obtain a licence for this computer.")
        caption.setBuddy(self.device)
        card.body.addWidget(caption)
        card.body.addWidget(self.device)

        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setVisible(False)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.body.addWidget(self.message)

        self.copy_button = QPushButton("&Copy activation request")
        self.copy_button.setToolTip("Copy a short text to send to the publisher; it holds only "
                                    "the product name and this computer's id.")
        self.copy_button.clicked.connect(self.copy_request)
        self.install_button = QPushButton("&Install licence file…")
        self.install_button.clicked.connect(self.choose_file)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("Primary")
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.install_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(card)
        layout.addLayout(buttons)
        self.refresh()

    # ------------------------------------------------------------------ status
    def refresh(self) -> None:
        kwargs = {"store": licensing.store(self._folder)} if self._folder is not None else {}
        st = licensing.status(**kwargs)
        self.current = st
        self.edition.setText(f"Edition: {st.edition.capitalize()}")
        self.status_label.setText(status_sentence(st))
        self.warnings.setText("\n".join(st.warnings))
        self.warnings.setVisible(bool(st.warnings))

    def _show_message(self, text: str, ok: bool) -> None:
        self.message.setText(text)
        self.message.setVisible(True)
        if callable(self._notify):
            self._notify(text, "success" if ok else "error")

    # ------------------------------------------------------------------ actions
    def copy_request(self) -> None:
        QApplication.clipboard().setText(licensing.activation_request())
        self._show_message("Activation request copied to the clipboard.", True)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Install licence file", "",
                                              "Licence files (*.json *.lic);;All files (*)")
        if path:
            self.install_file(path)

    def install_file(self, path) -> bool:
        try:
            with open(Path(path), "rb") as fh:
                raw = fh.read(MAX_BYTES + 1)
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            self._show_message("That file could not be read.", False)
            return False
        try:
            licensing.install(text, self._folder)
        except licensing.LicenceError as e:
            self._show_message(str(e), False)
            return False
        self.refresh()
        self._show_message("Licence installed.", True)
        return True
