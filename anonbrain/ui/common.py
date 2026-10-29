"""Shared UI pieces: background tasks, step bar, cards, small helpers."""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .background import GlassFrame


class Task(QThread):
    """Runs fn(emit) off the UI thread so the window never freezes.

    emit(message, fraction) can be called from inside fn to report progress.
    """
    status = Signal(str, float)
    done = Signal(object)
    failed = Signal(str, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(lambda m, f=0.0: self.status.emit(m, f)))
        except Exception as e:  # shown to the user, never crashes the app
            from ..appinfo import log_exception
            log_exception("Task failed", e)
            self.failed.emit(str(e) or e.__class__.__name__, e)


_running: set = set()     # every Task still going, so quitting can wait for them


def wait_for_tasks(ms: int) -> bool:
    """Give background work up to `ms` to finish (the app is closing).
    True if everything finished."""
    import time
    end = time.monotonic() + ms / 1000
    for task in list(_running):
        left = max(0, int((end - time.monotonic()) * 1000))
        if task.isRunning() and not task.wait(left):
            return False
    return True


def run_task(owner, fn, on_done=None, on_fail=None, on_status=None) -> Task:
    task = Task(fn, owner)
    _running.add(task)
    task.finished.connect(lambda: _running.discard(task))
    if on_done:
        task.done.connect(on_done)
    if on_fail:
        task.failed.connect(on_fail)
    if on_status:
        task.status.connect(on_status)
    # keep a reference until finished
    owner._tasks = getattr(owner, "_tasks", set())
    owner._tasks.add(task)
    task.finished.connect(lambda: owner._tasks.discard(task))
    task.start()
    return task


_thumbs: dict = {}


def cover_thumb(path: str, w: int, h: int):
    """A picture cropped to fill w x h, read from disk and sized once (lists that
    are rebuilt often reuse it). None if it isn't there (yet: asked again next time)."""
    if not path:
        return None
    key = (path, w, h)
    if key not in _thumbs:
        pix = QPixmap(path)
        if pix.isNull():
            return None
        pix = pix.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        _thumbs[key] = pix.copy((pix.width() - w) // 2, (pix.height() - h) // 2, w, h)
    return _thumbs[key]


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, name: str | None = None, on_click=None, tip: str = "") -> QPushButton:
    from .anim import AnimButton
    b = AnimButton(text)
    if name:
        b.setObjectName(name)
    if on_click:
        b.clicked.connect(on_click)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def restyle(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)


class Card(GlassFrame):
    """Frosted glass panel. Clickable cards emit `clicked` and can be 'selected'."""

    def __init__(self, clickable: bool = False):
        super().__init__(radius=20, clickable=clickable)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(22, 20, 22, 20)
        self.body.setSpacing(8)


class StepBar(QWidget):
    """The checklist across the top: ✓ Gameplay — ✓ Post — Voice — Render."""
    jump = Signal(int)

    def __init__(self, names: list[str]):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.names = names
        self.buttons = []
        for i, n in enumerate(names):
            if i:
                line = QLabel("──")
                line.setObjectName("StepLine")
                row.addWidget(line)
            b = button(f"{i + 1}  {n.replace('&', '&&')}", "Step", lambda _=False, i=i: self.jump.emit(i))
            self.buttons.append(b)
            row.addWidget(b)
        row.addStretch()

    def update_state(self, current: int, done: list[bool]):
        for i, b in enumerate(self.buttons):
            state = "current" if i == current else ("done" if done[i] else "todo")
            mark = "✓" if done[i] and i != current else str(i + 1)
            b.setText(f"{mark}  {self.names[i].replace('&', '&&')}")
            b.setProperty("state", state)
            b.setEnabled(i <= current or all(done[:i]))
            restyle(b)


def page_header(title: str, subtitle: str) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(2)
    box.addWidget(label(title, "Title"))
    box.addWidget(label(subtitle, "Subtitle", wrap=True))
    return box


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {seconds % 60}s"
    return f"{seconds}s"
