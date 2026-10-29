"""Pick which part of a song plays under the video: a waveform with a highlighted
window the length of the video. Drag (or click) to move it."""


import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from . import theme
from .common import run_task

_cache: dict = {}


def fmt(t: float) -> str:
    t = max(0, int(round(t)))
    return f"{t // 60}:{t % 60:02d}"


def song_peaks(path: str, buckets: int = 400) -> tuple[np.ndarray, float]:
    """(peak per bucket 0..1, duration in seconds)."""
    if path in _cache:
        return _cache[path]
    from ..engine import _tool, run_tool
    rate = 4000
    r = run_tool([_tool("ffmpeg"), "-v", "error", "-i", path, "-ac", "1", "-ar", rate,
                  "-f", "s16le", "-"], text=False)
    a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    dur = len(a) / rate
    if len(a) < buckets:
        peaks = np.zeros(buckets)
    else:
        a = np.abs(a[: len(a) // buckets * buckets]).reshape(buckets, -1)
        peaks = np.sqrt((a ** 2).mean(axis=1))
        peaks = peaks / (peaks.max() or 1.0)
    _cache[path] = (peaks, dur)
    return peaks, dur


class SongStrip(QWidget):
    start_changed = Signal(float)       # while dragging
    start_picked = Signal(float)        # when you let go

    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)
        self.setCursor(Qt.OpenHandCursor)
        self.peaks, self.duration = None, 0.0
        self.start, self.span = 0.0, 60.0
        self.path = ""
        self._grab = None
        self.setToolTip("Drag the highlighted part to choose which part of the song plays")

    # --- data --------------------------------------------------------------------
    def set_song(self, path: str, start: float = 0.0):
        self.path, self.start = path, start
        self.peaks, self.duration = None, 0.0
        self.update()
        if not path:
            return

        def done(res, p=path):
            if p == self.path:
                self.peaks, self.duration = res
                self.start = min(self.start, max(0.0, self.duration - 1))
                self.update()

        run_task(self, lambda emit: song_peaks(path), done, lambda m, e: None)

    def set_span(self, seconds: float):
        self.span = max(5.0, float(seconds))
        self.update()

    # --- drawing -----------------------------------------------------------------
    def _x(self, t):
        return 8 + (self.width() - 16) * (t / self.duration if self.duration else 0)

    def _t(self, x):
        return (x - 8) / max(1, self.width() - 16) * self.duration

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        bg = QPainterPath()
        bg.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.fillPath(bg, QColor(255, 255, 255, 14))
        if self.peaks is None:
            p.setPen(QColor(255, 255, 255, 110))
            p.drawText(r, Qt.AlignCenter, "Reading the song…" if self.path else "No music")
            return
        prim = QColor(theme.primary())
        x0, x1 = self._x(self.start), self._x(min(self.duration, self.start + self.span))
        sel = QPainterPath()
        sel.addRoundedRect(QRectF(x0, 3, max(4, x1 - x0), self.height() - 6), 9, 9)
        fill = QColor(prim)
        fill.setAlpha(45)
        p.fillPath(sel, fill)
        n = len(self.peaks)
        w = (self.width() - 16) / n
        mid = self.height() / 2
        for i, v in enumerate(self.peaks):
            x = 8 + i * w
            h = max(1.5, v * (self.height() - 16) / 2)
            inside = x0 <= x <= x1
            c = QColor(prim) if inside else QColor(255, 255, 255, 70)
            p.fillRect(QRectF(x, mid - h, max(1.0, w * 0.7), 2 * h), c)
        p.setPen(prim)
        p.drawPath(sel)
        p.setPen(QColor(255, 255, 255, 170))
        f = p.font()
        f.setPointSizeF(8)
        p.setFont(f)
        p.drawText(QRectF(x0 + 6, 4, 80, 14), Qt.AlignLeft, fmt(self.start))
        p.drawText(QRectF(self.width() - 60, self.height() - 18, 52, 14), Qt.AlignRight,
                   fmt(self.duration))

    # --- dragging ----------------------------------------------------------------
    def mousePressEvent(self, e):
        if not self.duration:
            return
        t = self._t(e.position().x())
        if self.start <= t <= self.start + self.span:
            self._grab = t - self.start          # drag the window by where you grabbed it
        else:
            self._grab = self.span / 2           # click elsewhere: centre it there
        self.setCursor(Qt.ClosedHandCursor)
        self._move(t)

    def mouseMoveEvent(self, e):
        if self._grab is not None:
            self._move(self._t(e.position().x()))

    def mouseReleaseEvent(self, e):
        if self._grab is not None:
            self._grab = None
            self.setCursor(Qt.OpenHandCursor)
            self.start_picked.emit(self.start)

    def _move(self, t):
        last = max(0.0, self.duration - min(self.span, self.duration))
        self.start = round(min(max(0.0, t - self._grab), last), 1)
        self.update()
        self.start_changed.emit(self.start)
