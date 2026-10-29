"""Splash screen: big ANON BRAIN title, Start button."""

import math

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget

from . import background, theme
from .common import button, label

TITLE_FONTS = ["Segoe UI Black", "Arial Black", "Segoe UI Variable Display", "Segoe UI"]


class GradientTitle(QWidget):
    """'ANON BRAIN' in huge heavy letters, filled with a slowly moving gradient."""

    def __init__(self, text: str = "ANON BRAIN"):
        super().__init__()
        self.text = text
        self.setObjectName("Transparent")
        self.setMinimumHeight(150)
        if background.CURRENT is not None:
            background.CURRENT.frame_ready.connect(self.update)

    def _font(self, width: float) -> QFont:
        f = QFont()
        f.setFamilies(TITLE_FONTS)
        f.setWeight(QFont.Black)
        f.setLetterSpacing(QFont.PercentageSpacing, 104)
        size = 140.0
        f.setPixelSize(int(size))
        w = QFontMetricsF(f).horizontalAdvance(self.text)
        f.setPixelSize(max(40, int(size * min(1.0, width * 0.86 / max(w, 1)))))
        return f

    def sizeHint(self):
        return self.minimumSizeHint()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = self._font(self.width())
        fm = QFontMetricsF(f)
        tw = fm.horizontalAdvance(self.text)
        x = (self.width() - tw) / 2
        y = (self.height() + fm.capHeight()) / 2
        path = QPainterPath()
        path.addText(QPointF(x, y), f, self.text)

        t = background.CURRENT.t if background.CURRENT else 0.0
        shift = 0.5 + 0.5 * math.sin(t * 0.35)
        cols = [theme.color("primary"), theme.color("secondary"), theme.color("tertiary")]

        # soft glow: draw the letters tiny, then scale them up (= blur)
        k = 7
        small = QImage(max(1, self.width() // k), max(1, self.height() // k),
                       QImage.Format_ARGB32_Premultiplied)
        small.fill(Qt.transparent)
        gp = QPainter(small)
        gp.setRenderHint(QPainter.Antialiasing)
        gp.scale(1 / k, 1 / k)
        glow = QLinearGradient(x, 0, x + tw, 0)
        for stop, c in ((0, cols[0]), (0.5, cols[1]), (1, cols[2])):
            c = QColor(c)
            c.setAlpha(170)
            glow.setColorAt(stop, c)
        gp.fillPath(path, glow)
        gp.end()
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(0.75)
        p.drawImage(QRectF(self.rect()), small)
        p.restore()

        g = QLinearGradient(x - tw * shift * 0.6, 0, x + tw * (1.6 - shift * 0.6), 0)
        g.setColorAt(0.0, cols[0].lighter(125))
        g.setColorAt(0.35, cols[1].lighter(115))
        g.setColorAt(0.7, cols[2].lighter(125))
        g.setColorAt(1.0, cols[0].lighter(125))
        p.fillPath(path, g)
        # glassy top shine
        shine = QLinearGradient(0, y - fm.capHeight(), 0, y)
        shine.setColorAt(0, QColor(255, 255, 255, 90))
        shine.setColorAt(0.5, QColor(255, 255, 255, 0))
        p.fillPath(path, shine)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawPath(path)


class SplashPage(QWidget):
    start = Signal()
    settings = Signal()
    history = Signal()
    automate = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Transparent")
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 30)

        top = QHBoxLayout()
        top.addStretch()
        top.addWidget(button("🕘  History", on_click=self.history.emit))
        top.addSpacing(6)
        self.settings_btn = button("⚙  Settings", on_click=self.settings.emit)
        top.addWidget(self.settings_btn)
        root.addLayout(top)
        root.addStretch(3)

        self.content = QWidget()
        self.content.setObjectName("Transparent")
        col = QVBoxLayout(self.content)
        col.setSpacing(6)
        self.title = GradientTitle()
        col.addWidget(self.title)
        tag = label("posts in, videos out", "Subtitle")
        tag.setAlignment(Qt.AlignCenter)
        tag.setStyleSheet("font-size: 15pt; letter-spacing: 3px;")
        col.addWidget(tag)
        col.addSpacing(34)
        row = QHBoxLayout()
        row.addStretch()
        self.start_btn = button("Make a video  →", "Primary", self.start.emit,
                                "Step by step: gameplay, post, layout, voice, render")
        self.start_btn.setStyleSheet("font-size: 14pt; padding: 14px 44px; border-radius: 18px;")
        self.start_btn.setMinimumWidth(260)
        row.addWidget(self.start_btn)
        row.addSpacing(12)
        self.automate_btn = button("⚡  Automate", on_click=self.automate.emit,
                                   tip="Find posts in subreddits, make videos and post them "
                                       "on a schedule")
        self.automate_btn.setStyleSheet("font-size: 14pt; padding: 14px 30px; "
                                        "border-radius: 18px;")
        row.addWidget(self.automate_btn)
        row.addStretch()
        col.addLayout(row)
        root.addWidget(self.content)
        root.addStretch(4)

        foot = label("Turn 4chan & Reddit posts into narrated gameplay videos. Free, on your PC.",
                     "Hint")
        foot.setAlignment(Qt.AlignCenter)
        root.addWidget(foot)

    def play_intro(self):
        """Fade the title in when the app opens."""
        eff = QGraphicsOpacityEffect(self.content)
        self.content.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(1100)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.content.setGraphicsEffect(None))
        anim.start()
        self._anim = anim
