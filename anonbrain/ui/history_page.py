"""History: every video you've made, with thumbnails."""

import time
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import free_tts
from .background import GlassFrame
from .common import button, cover_thumb, label


def voice_label(vid: str) -> str:
    if not vid or vid == "__none__":
        return "no voice"
    if vid.startswith(free_tts.PREFIX):
        return free_tts.VOICES.get(vid[len(free_tts.PREFIX):], "free voice").split(" ·")[0]
    if vid.startswith("custom:"):
        from ..custom_voices import get
        v = get(vid)
        return v["name"] if v else "your voice"
    return "ElevenLabs"


class HistoryCard(GlassFrame):
    def __init__(self, entry: dict, page):
        super().__init__(radius=18, clickable=False)
        self.entry, self.page = entry, page
        self.setFixedWidth(250)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)

        thumb = QLabel()
        thumb.setFixedSize(QSize(226, 150))
        thumb.setAlignment(Qt.AlignCenter)
        pix = cover_thumb(entry.get("thumb", ""), 226, 150)
        if pix is not None:
            thumb.setPixmap(pix)
        else:
            thumb.setText("no thumbnail")
        thumb.setStyleSheet("QLabel { border-radius: 12px; background: rgba(0,0,0,0.35);"
                            " color: rgba(255,255,255,0.5); }")
        lay.addWidget(thumb)

        first = next((l.strip(" >") for l in entry.get("text", "").splitlines() if l.strip()), "")
        title = entry.get("hook") or first or "Untitled"
        t = label(title[:60] + ("…" if len(title) > 60 else ""), "Section", wrap=True)
        t.setStyleSheet("font-size: 10.5pt;")
        lay.addWidget(t)
        when = time.strftime("%b %d, %I:%M %p", time.localtime(entry["created"]))
        secs = int(entry.get("length", 0))
        meta = f"{when} · {secs // 60}:{secs % 60:02d} · {voice_label(entry.get('voice', ''))}"
        lay.addWidget(label(meta, "Hint", wrap=True))
        exists = Path(entry.get("video", "")).is_file()
        if not exists:
            lay.addWidget(label("Video file was moved or deleted", "Error"))
        row = QHBoxLayout()
        row.setSpacing(6)
        play = button("▶ Play", on_click=self.play)
        play.setEnabled(exists)
        row.addWidget(play)
        folder = button("Folder", on_click=self.folder)
        folder.setEnabled(exists)
        row.addWidget(folder)
        row.addStretch()
        lay.addLayout(row)
        row2 = QHBoxLayout()
        reuse = button("Reuse post", "Link", self.reuse,
                       "Load this post into step 2 to make a new version")
        reuse.setEnabled(bool(entry.get("text")))
        row2.addWidget(reuse)
        row2.addStretch()
        row2.addWidget(button("Remove", "Link", self.remove, "Remove from history"))
        lay.addLayout(row2)

    def play(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.entry["video"]))

    def folder(self):
        from ..appinfo import show_in_folder
        show_in_folder(self.entry["video"])

    def reuse(self):
        self.page.reuse.emit(self.entry)

    def remove(self):
        box = QMessageBox(self)
        box.setWindowTitle("Remove from history")
        box.setText("Remove this video from your history?")
        keep = box.addButton("Remove, keep the video file", QMessageBox.AcceptRole)
        delete = box.addButton("Remove and delete the video", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() in (keep, delete):
            self.page.state.history.remove(self.entry, delete_files=box.clickedButton() is delete)
            self.page.refresh()


class HistoryPage(QWidget):
    closed = Signal()
    reuse = Signal(dict)

    def __init__(self, state):
        super().__init__()
        self.setObjectName("Transparent")
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 24, 36, 20)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(label("History", "Title"))
        self.count = label("", "Subtitle")
        head.addSpacing(12)
        head.addWidget(self.count, 0, Qt.AlignBottom)
        head.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search your videos…")
        self.search.setFixedWidth(260)
        self._per_row = None
        self._later = QTimer(self)           # typing / resizing: rebuild once it settles
        self._later.setSingleShot(True)
        self._later.setInterval(140)
        self._later.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self._later.start())
        head.addWidget(self.search)
        head.addSpacing(8)
        head.addWidget(button("Done", "Primary", self.closed.emit))
        root.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        root.addWidget(self.scroll, 1)
        self.empty = label("Nothing here yet. Every video you make shows up here, so you can "
                           "find it again and avoid posting the same post twice.", "Subtitle", wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)
        state.events.history_changed.connect(self.refresh)

    def refresh(self):
        self._later.stop()
        q = self.search.text().strip().lower()
        entries = [e for e in self.state.history.entries
                   if not q or q in (e.get("text", "") + " " + e.get("hook", "")).lower()]
        n = len(self.state.history.entries)
        self.count.setText(f"{n} video{'s' * (n != 1)}" if n else "")
        inner = QWidget()
        inner.setObjectName("Transparent")
        grid = QGridLayout(inner)
        grid.setContentsMargins(0, 0, 8, 0)
        grid.setSpacing(16)
        per_row = max(1, (self.scroll.viewport().width() - 8) // 266)
        self._per_row = per_row
        for i, e in enumerate(entries):
            grid.addWidget(HistoryCard(e, self), i // per_row, i % per_row, Qt.AlignTop)
        grid.setColumnStretch(per_row, 1)
        grid.setRowStretch(len(entries) // per_row + 1, 1)
        self.scroll.setWidget(inner)
        self.empty.setVisible(not entries)
        if not entries and q:
            self.empty.setText("No videos match that search.")
        elif not entries:
            self.empty.setText("Nothing here yet. Every video you make shows up here, so you "
                               "can find it again and avoid posting the same post twice.")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # only rebuild when a different number of cards fits in a row
        per_row = max(1, (self.scroll.viewport().width() - 8) // 266)
        if self.isVisible() and per_row != self._per_row:
            self._later.start()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
