"""When something goes wrong: a dialog with "Copy error details" so the person can
just paste it to you, plus the link used next to error messages."""

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from .. import appinfo
from .common import button, label

COPY_LINK = "<a href='copy-error' style='color:#9aa0a6'>Copy error details</a>"


def copy_report(extra: str = "") -> str:
    text = appinfo.error_report()
    if extra:
        from pathlib import Path
        home = str(Path.home())
        text += "\n\n---- this error ----\n" + (extra.replace(home, "~") if len(home) > 3
                                                   else extra)
    QGuiApplication.clipboard().setText(text)
    return text


def attach_copy_link(lab):
    """Make 'Copy error details' links inside a label work."""
    lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
    lab.setOpenExternalLinks(False)

    def go(href):
        if href == "copy-error":
            copy_report()
            old = lab.text()
            lab.setText(old.replace(COPY_LINK, "<span style='color:#9aa0a6'>✓ Copied, paste it "
                                               "to whoever is helping you</span>"))
            QTimer.singleShot(4000, lambda: lab.text() != old and lab.setText(old))
    lab.linkActivated.connect(go)


class ErrorDialog(QDialog):
    def __init__(self, parent, title: str, message: str, details: str = ""):
        super().__init__(parent)
        self.details = details
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(10)
        root.addWidget(label(title, "Title"))
        root.addWidget(label(message, wrap=True))
        root.addWidget(label("Click Copy error details and send it to whoever gave you the "
                             "app. It includes the app version and what happened (no keys or "
                             "sign-ins).", "Hint", wrap=True))
        if details:
            box = QPlainTextEdit(details)
            box.setReadOnly(True)
            box.setMaximumHeight(160)
            box.setStyleSheet("font-family: Consolas, monospace; font-size: 8.5pt;")
            root.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(button("Open log folder", "Link",
                             lambda: appinfo.open_folder(appinfo.log_dir())))
        row.addStretch()
        self.copy_btn = button("Copy error details", on_click=self.copy)
        row.addWidget(self.copy_btn)
        row.addWidget(button("Close", "Primary", self.accept))
        root.addLayout(row)

    def copy(self):
        copy_report(self.details)
        self.copy_btn.setText("✓ Copied")


class CrashReporter(QObject):
    """Shows unexpected errors from any thread, one dialog at a time."""
    crashed = Signal(str)

    def __init__(self, parent_window_fn):
        super().__init__()
        self.window = parent_window_fn
        self.showing = False
        self.crashed.connect(self._show, Qt.QueuedConnection)

    def report(self, text: str):
        self.crashed.emit(text)

    def _show(self, text):
        if self.showing:
            return
        self.showing = True
        try:
            ErrorDialog(self.window(), "Something went wrong",
                        "Anon Brain hit an unexpected problem. You can keep using it, but if it "
                        "keeps happening, send the error details.", text[-4000:]).exec()
        finally:
            self.showing = False
