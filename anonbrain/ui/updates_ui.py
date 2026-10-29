"""The "New update available" note in the corner, and updating in place."""

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .. import appinfo, updates
from . import theme
from .common import button, label, run_task

EVERY = 6 * 3600 * 1000          # check again this often while the app stays open


class UpdatePill(QPushButton):
    def __init__(self, parent):
        super().__init__("●  New update available", parent)
        self.setObjectName("UpdatePill")
        self.setCursor(Qt.PointingHandCursor)
        self.restyle()
        self.hide()

    def restyle(self):
        p = theme.color("primary")
        self.setStyleSheet(
            "QPushButton#UpdatePill { background: rgba(14, 16, 22, 215); color: #ffffff;"
            f" border: 1px solid rgba({p.red()}, {p.green()}, {p.blue()}, 160);"
            " border-radius: 11px; padding: 3px 12px; font-size: 9pt; font-weight: 600; }"
            "QPushButton#UpdatePill:hover {"
            f" background: rgba({p.red()}, {p.green()}, {p.blue()}, 70); }}")
        self.adjustSize()


class UpdateChecker(QObject):
    found = Signal(object)          # a Release
    FULL = "●  New update available"
    SHORT = "●  Update"

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.release = None
        self.pill = UpdatePill(win)
        self.pill.clicked.connect(self.open_dialog)
        self.timer = QTimer(self)
        self.timer.setInterval(EVERY)
        self.timer.timeout.connect(self.check)

    def start(self):
        if not updates.enabled():
            return
        QTimer.singleShot(5000, self.check)
        self.timer.start()

    def wanted(self) -> bool:
        return updates.enabled() and bool(self.win.state.settings["check_updates"])

    def check(self, manual=False, on_result=None):
        if not updates.enabled() or (not manual and not self.wanted()):
            return

        def done(rel):
            if rel is not None:
                self._show(rel)
            if on_result:
                on_result(rel, "")

        def fail(msg, e):
            appinfo.log.info("Update check failed: %s", msg)
            if on_result:
                on_result(None, msg)
        run_task(self, lambda emit: updates.check(), done, fail)

    def _show(self, rel):
        new = self.release is None or rel.version != self.release.version
        self.release = rel
        self.pill.setToolTip(f"Anon Brain {rel.version} is out. Click to update.")
        self.pill.restyle()
        self.place()
        self.pill.show()
        self.pill.raise_()
        if new:
            self.found.emit(rel)
            if not self.win.isVisible():
                self.win.tray_message("Anon Brain update", f"Version {rel.version} is ready. "
                                      "Open Anon Brain to update.")

    def place(self):
        """Top right: in the header row, just left of the screen's top-right buttons."""
        from PySide6.QtWidgets import QAbstractButton, QCheckBox, QLabel, QWidget
        p = self.pill
        p.adjustSize()
        W = self.win.width()
        screen = self.win.screens.currentWidget() if hasattr(self.win, "screens") else None
        row = []
        if screen is not None:
            for b in screen.findChildren(QAbstractButton):
                if b is p or not b.isVisible() or b.width() < 12:
                    continue
                r = b.rect().translated(b.mapTo(self.win, b.rect().topLeft()))
                if r.top() < 90 and r.center().x() > W * 0.5 and r.right() <= W:
                    row.append(r)
        if not row:
            p.setText(self.FULL)
            p.adjustSize()
            p.move(W - p.width() - 28, 18)
            p.raise_()
            return
        top = min(r.top() for r in row)
        row = [r for r in row if r.top() <= top + 12]           # the topmost row only
        left = min(r.left() for r in row)
        mid = sum(r.center().y() for r in row) / len(row)
        # other things in that row (text, switches) the note mustn't cover
        others = []
        for wdg in screen.findChildren(QWidget):
            if wdg is p or not wdg.isVisible() or isinstance(wdg, QAbstractButton) or \
                    not isinstance(wdg, (QLabel, QCheckBox)):
                continue
            r = wdg.rect().translated(wdg.mapTo(self.win, wdg.rect().topLeft()))
            if abs(r.center().y() - mid) < 16 and r.right() < left:
                fm = wdg.fontMetrics()
                text_w = fm.horizontalAdvance(wdg.text()) + 24 if hasattr(wdg, "text") else r.width()
                others.append(r.left() + min(r.width(), text_w))
        for text in (self.FULL, self.SHORT):
            p.setText(text)
            p.adjustSize()
            x = left - p.width() - 14
            if not others or x > max(others) + 10:
                break
        p.move(max(16, x), int(mid - p.height() / 2))
        p.raise_()

    def open_dialog(self):
        if self.release is not None:
            UpdateDialog(self.win, self.release).exec()


class UpdateDialog(QDialog):
    def __init__(self, win, rel):
        super().__init__(win)
        self.win, self.rel = win, rel
        self.cancelled = False
        self.task = None
        self.setWindowTitle("Update Anon Brain")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        head = label(f"Anon Brain {rel.version} is ready", "Section")
        head.setStyleSheet("font-size: 13pt;")
        lay.addWidget(head)
        lay.addWidget(label(f"You have {appinfo.VERSION}. Your settings, presets, history and "
                            "sign-ins are kept.", "Muted", wrap=True))
        if rel.notes:
            lay.addWidget(label("What's new", "Hint"))
            notes = QTextBrowser()
            notes.setOpenExternalLinks(True)
            notes.setMarkdown(rel.notes)
            notes.setMaximumHeight(200)
            notes.setStyleSheet("QTextBrowser { background: rgba(255, 255, 255, 0.05);"
                                " color: #e8e9ec; border: 1px solid rgba(255, 255, 255, 0.12);"
                                " border-radius: 8px; padding: 6px; }")
            lay.addWidget(notes)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.status = label("", "Muted", wrap=True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.later_btn = button("Later", on_click=self.reject)
        row.addWidget(self.later_btn)
        if updates.can_install(rel):
            self.go_btn = button("Update now", "Primary", self.update_now,
                                 tip="Downloads the new version, installs it over this one "
                                     "and reopens Anon Brain")
        else:
            self.go_btn = button("Open download page", "Primary", self.open_page)
        row.addWidget(self.go_btn)
        lay.addLayout(row)

    def open_page(self):
        QDesktopServices.openUrl(QUrl(self.rel.page))
        self.accept()

    def update_now(self):
        if getattr(self.win, "busy", False) or self.win.automation.running:
            self.status.setText("Wait until the video being made is finished, then update.")
            return
        self.go_btn.setEnabled(False)
        self.bar.show()
        self.bar.setValue(0)
        mb = f" ({self.rel.size / 1e6:.0f} MB)" if self.rel.size else ""
        self.status.setText(f"Downloading the update{mb}…")
        self.later_btn.setText("Cancel")

        def fn(emit):
            return updates.download(self.rel, lambda f: emit("", f), lambda: self.cancelled)

        self.task = run_task(self, fn, self._downloaded, self._failed,
                             lambda m, f: self.bar.setValue(int(f * 100)))

    def _downloaded(self, path):
        self.status.setText("Installing… Anon Brain will close and reopen by itself.")
        self.bar.setValue(100)
        try:
            updates.run_installer(path)
        except OSError as e:
            self._failed(f"Couldn't start the installer: {e}", e)
            return
        QTimer.singleShot(600, self.win.quit_app)

    def _failed(self, msg, e):
        self.bar.hide()
        self.go_btn.setEnabled(True)
        self.later_btn.setText("Later")
        if isinstance(e, InterruptedError):
            QDialog.reject(self)
            return
        self.status.setText(f"The update didn't download: {msg}\nCheck your internet and try "
                            "again, or use the download page.")
        self.go_btn.setText("Try again")

    def reject(self):
        if self.task is not None and self.task.isRunning():
            self.cancelled = True
            return
        super().reject()
