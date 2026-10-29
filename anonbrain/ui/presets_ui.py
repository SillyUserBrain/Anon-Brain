"""The Presets button: apply a saved look, save the current one, manage them."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QMenu,
    QMessageBox,
    QVBoxLayout,
)

from .common import Card, button, label

WHAT = ("Saves: shape, quality, where the post sits, corners, shadow, border, reveal, "
        "voice, pauses, volumes, music, watermark and end card.")


class PresetMenu:
    """Builds the menu each time it opens (so it's always up to date)."""

    def __init__(self, window, btn):
        self.window, self.btn = window, btn
        self.state = window.state
        btn.clicked.connect(self.open)

    def open(self):
        m = QMenu(self.btn)
        names = self.state.presets.names()
        if names:
            head = m.addAction("Apply a look")
            head.setEnabled(False)
            for n in names:
                m.addAction("   " + n, lambda n=n: self.apply(n))
            m.addSeparator()
        m.addAction("＋  Save the current look…", self.save_new)
        if names:
            m.addAction("Manage presets…", self.manage)
        m.exec(self.btn.mapToGlobal(self.btn.rect().bottomLeft()))

    def apply(self, name):
        if self.state.presets.apply(name, self.state.settings):
            self.window.reload_from_settings()
            self.flash(f"★  {name}")

    def flash(self, text):
        old = "★  Presets"
        self.btn.setText(text)
        QTimer.singleShot(2600, lambda: self.btn.setText(old))

    def save_new(self):
        name, ok = QInputDialog.getText(self.window, "Save this look",
                                        "Name it (like “My TikTok style”):\n\n" + WHAT)
        if not ok or not name.strip():
            return
        if name.strip() in self.state.presets.items and QMessageBox.question(
                self.window, "Replace preset",
                f"There's already a preset called “{name.strip()}”. Replace it?") != \
                QMessageBox.Yes:
            return
        self.window.layout_page_settle()
        saved = self.state.presets.save(name, self.state.settings)
        self.state.events.queue_changed.emit()      # batch rows list presets
        self.flash(f"✓  Saved “{saved}”")

    def manage(self):
        ManagePresets(self.state, self.window, self).exec()
        self.state.events.queue_changed.emit()


class ManagePresets(QDialog):
    def __init__(self, state, window, menu):
        super().__init__(window)
        self.state, self.window, self.menu = state, window, menu
        self.setWindowTitle("Presets")
        self.setMinimumWidth(520)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(22, 20, 22, 18)
        self.root.setSpacing(10)
        self.root.addWidget(label("Presets", "Title"))
        self.root.addWidget(label(WHAT, "Muted", wrap=True))
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.root.addLayout(self.list)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Done", "Primary", self.accept))
        self.root.addLayout(row)
        self.refresh()

    def refresh(self):
        while self.list.count():
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        for n in self.state.presets.names():
            card = Card()
            card.body.setContentsMargins(14, 8, 8, 8)
            r = QHBoxLayout()
            r.addWidget(label(n, "Section"), 1)
            r.addWidget(button("Apply", on_click=lambda _=False, n=n: (
                self.menu.apply(n), self.accept())))
            r.addWidget(button("Update", on_click=lambda _=False, n=n: self.update_one(n),
                               tip="Replace it with the look you have now"))
            r.addWidget(button("Rename", on_click=lambda _=False, n=n: self.rename(n)))
            r.addWidget(button("✕", on_click=lambda _=False, n=n: self.delete(n),
                               tip="Delete this preset"))
            card.body.addLayout(r)
            self.list.addWidget(card)
        if not self.state.presets.names():
            self.list.addWidget(label("No presets yet.", "Hint"))

    def update_one(self, n):
        self.window.layout_page_settle()
        self.state.presets.save(n, self.state.settings)
        self.menu.flash(f"✓  Updated “{n}”")

    def rename(self, n):
        new, ok = QInputDialog.getText(self, "Rename preset", "New name:", text=n)
        if ok and new.strip():
            new = self.state.presets.rename(n, new)
            for it in self.state.queue:
                if it.get("preset") == n:
                    it["preset"] = new
            self.refresh()

    def delete(self, n):
        if QMessageBox.question(self, "Delete preset", f"Delete “{n}”?") == QMessageBox.Yes:
            self.state.presets.delete(n)
            for it in self.state.queue:
                if it.get("preset") == n:
                    it["preset"] = ""
            self.refresh()
