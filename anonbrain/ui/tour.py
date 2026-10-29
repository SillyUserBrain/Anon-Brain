"""The first-run tour: the window dims, one part at a time is lit up, and a small
card explains it. Shown once (Settings → About can show it again)."""

from PySide6.QtCore import QEasingCurve, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import anim, theme
from .common import button


def _rect(widget) -> QRect | None:
    """A widget's rectangle in the main window's coordinates (None if hidden)."""
    if widget is None or not widget.isVisible():
        return None
    win = widget.window()
    top_left = widget.mapTo(win, widget.rect().topLeft())
    return QRect(top_left, widget.size())


def _union(widgets) -> QRect | None:
    rects = [r for r in (_rect(w) for w in widgets) if r is not None]
    if not rects:
        return None
    out = rects[0]
    for r in rects[1:]:
        out = out.united(r)
    return out


def steps(win):
    """(prepare, target, title, text). prepare() runs first (e.g. opens a screen);
    target() gives the rectangle to light up, or None for a card in the middle."""

    def wizard():
        if win.screens.currentWidget() is not win.wizard:
            win.show_screen(win.wizard)
        if win.index != 0:
            win.go(0)

    def splash():
        if win.screens.currentWidget() is not win.splash:
            win.show_screen(win.splash, -1)

    return [
        (splash, lambda: None, "Welcome to Anon Brain 👋",
         "Anon Brain turns Reddit and 4chan posts into narrated videos over gameplay, "
         "ready for TikTok, Shorts and Reels.\n\nHere's a quick look around. It takes a minute."),
        (wizard, lambda: _rect(win.bar), "Five steps to a video",
         "Gameplay → Post → Layout → Voice & Music → Render. Finished steps get a ✓, and "
         "you can click one to jump back to it."),
        (wizard, lambda: _rect(win.stack), "1 · Pick your gameplay",
         "Choose a folder of gameplay clips (or one video). Each video gets a fresh stretch "
         "of footage, so nothing repeats."),
        (wizard, lambda: _union(win.bar.buttons[1:]), "Then the post, the look and the voice",
         "Paste a Reddit or 4chan link (or drop a screenshot) in Post. Place it, or switch "
         "to big captions, in Layout. Pick a voice and music, then Render."),
        (wizard, lambda: _rect(win.next_btn), "Next",
         "Moves you to the next step. It lights up once the step you're on is done."),
        (wizard, lambda: _rect(win.presets_btn), "Presets",
         "Happy with how a video looks? Save it as a preset (Ctrl+S) so every video matches."),
        (wizard, lambda: _rect(win.automate_btn), "Automate",
         "Give it subreddits and it finds good posts, makes the videos and posts them on a "
         "schedule, from the tray. You can review each one first."),
        (wizard, lambda: _rect(win.settings_btn), "Settings",
         "Colors, voices, your accounts and help. Settings → About can show this tour again."),
        (wizard, lambda: None, "You're set!",
         "Start by picking your gameplay. Press F1 any time for keyboard shortcuts."),
    ]


class Tour(QWidget):
    PAD = 8

    def __init__(self, win, on_done=None):
        super().__init__(win)
        self.win, self.on_done = win, on_done
        self.steps = steps(win)
        self.i = 0
        self.hole = None            # QRectF being lit up (animated)
        self._anim = None
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.StrongFocus)

        self.card = QFrame(self)
        self.card.setObjectName("TourCard")
        p = theme.color("primary").name()
        self.card.setStyleSheet(
            "QFrame#TourCard { background: rgba(16, 18, 24, 245); border-radius: 16px;"
            f" border: 1px solid {p}; }}"
            "QLabel { background: transparent; border: none; }")
        self.card.setFixedWidth(360)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(20, 16, 20, 14)
        lay.setSpacing(8)
        self.count = QLabel()
        self.count.setObjectName("Hint")
        self.title = QLabel()
        self.title.setStyleSheet("font-size: 13pt; font-weight: 700;")
        self.title.setWordWrap(True)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setObjectName("Muted")
        for w in (self.title, self.text):     # fixed width so wrapped text gets its height
            w.setFixedWidth(360 - 40)
        lay.addWidget(self.count)
        lay.addWidget(self.title)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        self.skip_btn = button("Skip tour", "Link", self.finish)
        self.back_btn = button("Back", on_click=lambda: self.show_step(self.i - 1))
        self.next_btn = button("Next", "Primary", lambda: self.show_step(self.i + 1))
        row.addWidget(self.skip_btn)
        row.addStretch()
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        lay.addSpacing(4)
        lay.addLayout(row)

    # --- running ------------------------------------------------------------------
    def start(self):
        self.setGeometry(self.win.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self.show_step(0)

    def finish(self):
        self.hide()
        self.deleteLater()
        if self.on_done:
            self.on_done()

    def show_step(self, i):
        if i >= len(self.steps):
            self.finish()
            return
        self.i = max(0, i)
        prepare, _, title, text = self.steps[self.i]
        prepare()
        self.count.setText(f"{self.i + 1} of {len(self.steps)}")
        self.title.setText(title)
        self.text.setText(text)
        self.back_btn.setVisible(self.i > 0)
        last = self.i == len(self.steps) - 1
        self.next_btn.setText("Let's go" if last else "Next")
        self.skip_btn.setVisible(not last)
        for w in (self.title, self.text):
            w.setFixedHeight(w.heightForWidth(w.width()))
        self.card.adjustSize()
        self.card.hide()
        # screens slide in: measure once they've settled
        QTimer.singleShot(420 if anim.ENABLED else 30, self._settle)

    def _settle(self):
        if not self.isVisible():
            return
        self._place(animate=True)
        self.card.show()
        self.setFocus()

    def _target(self) -> QRectF | None:
        r = self.steps[self.i][1]()
        if r is None:
            return None
        return QRectF(r).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    def _place(self, animate=True):
        if not self.isVisible():
            return
        self.raise_()
        target = self._target()
        start = self.hole
        if animate and anim.ENABLED and start is not None and target is not None:
            a = QVariantAnimation(self)
            a.setStartValue(0.0)
            a.setEndValue(1.0)
            a.setDuration(260)
            a.setEasingCurve(QEasingCurve.OutCubic)

            def step(t, s=QRectF(start), e=QRectF(target)):
                t = float(t)
                self.hole = QRectF(s.x() + (e.x() - s.x()) * t, s.y() + (e.y() - s.y()) * t,
                                   s.width() + (e.width() - s.width()) * t,
                                   s.height() + (e.height() - s.height()) * t)
                self.update()
            a.valueChanged.connect(step)
            a.start(QVariantAnimation.DeleteWhenStopped)
            self._anim = a
        else:
            self.hole = target
        self._move_card(target)
        self.update()

    def _move_card(self, target):
        c = self.card
        c.adjustSize()
        W, H = self.width(), self.height()
        if target is None:
            x, y = (W - c.width()) / 2, (H - c.height()) / 2
        else:
            x = min(max(16, target.center().x() - c.width() / 2), W - c.width() - 16)
            below = target.bottom() + 14
            if below + c.height() < H - 16:
                y = below
            else:
                y = max(16, target.top() - 14 - c.height())
            if target.height() > H * 0.45:          # a big area: sit inside it, centred
                y = target.center().y() - c.height() / 2
        c.move(int(x), int(y))

    # --- events ---------------------------------------------------------------------
    def resize_to_window(self):
        self.setGeometry(self.win.rect())
        self._place(animate=False)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.finish()
        elif k in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self.show_step(self.i + 1)
        elif k == Qt.Key_Left:
            self.show_step(self.i - 1)

    def mousePressEvent(self, e):
        e.accept()                  # the window underneath is paused during the tour

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shade = QPainterPath()
        shade.addRect(QRectF(self.rect()))
        if self.hole is not None:
            hole = QPainterPath()
            hole.addRoundedRect(self.hole, 12, 12)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(4, 5, 8, 185))
        if self.hole is not None:
            c = theme.color("primary")
            for w, a in ((7, 40), (3, 90), (1.6, 255)):
                c.setAlpha(a)
                p.setPen(QPen(c, w))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(self.hole, 12, 12)
