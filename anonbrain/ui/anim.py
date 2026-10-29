"""Motion: smooth page transitions, animated buttons, fades.

Everything here can be switched off in Settings → Appearance → Animations.
"""

from PySide6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
)

from . import theme

ENABLED = True          # Settings → Appearance → Animations


def _anim(target_cb, start, end, ms, curve=QEasingCurve.OutCubic, parent=None):
    a = QVariantAnimation(parent)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.valueChanged.connect(target_cb)
    return a


# ---------------------------------------------------------------------------
class AnimButton(QPushButton):
    """A push button that eases into its hover state, dips when pressed and
    springs back when released. Primary buttons also glow on hover."""

    def __init__(self, text=""):
        super().__init__(text)
        self._hover = 0.0
        self._press = 0.0
        self._hover_anim = None
        self._press_anim = None
        self._glow = None

    # animation plumbing
    def _set_hover(self, v):
        self._hover = float(v)
        if self._glow is not None:
            self._glow.setBlurRadius(4 + 30 * self._hover)
            c = theme.color("primary")
            c.setAlpha(int(170 * self._hover))
            self._glow.setColor(c)
            self._glow.setEnabled(self._hover > 0.02)
        self.update()

    def _set_press(self, v):
        self._press = float(v)
        self.update()

    def _animate_hover(self, to):
        if not ENABLED:
            self._set_hover(to)
            return
        if self._hover_anim:
            self._hover_anim.stop()
        self._hover_anim = _anim(self._set_hover, self._hover, to, 180 if to else 260, parent=self)
        self._hover_anim.start()

    def _animate_press(self, to, ms, curve):
        if not ENABLED:
            self._set_press(to)
            return
        if self._press_anim:
            self._press_anim.stop()
        self._press_anim = _anim(self._set_press, self._press, to, ms, curve, self)
        self._press_anim.start()

    def _ensure_glow(self):
        if self.objectName() == "Primary" and self._glow is None:
            self._glow = QGraphicsDropShadowEffect(self)
            self._glow.setOffset(0, 2)
            self._glow.setEnabled(False)
            self.setGraphicsEffect(self._glow)

    # events
    def enterEvent(self, e):
        if self.isEnabled():
            self._ensure_glow()
            self._animate_hover(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate_hover(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._animate_press(1.0, 90, QEasingCurve.OutQuad)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._animate_press(0.0, 420, QEasingCurve.OutBack)
        super().mouseReleaseEvent(e)

    def changeEvent(self, e):
        if e.type() == e.Type.EnabledChange and not self.isEnabled():
            self._set_hover(0.0)
            self._set_press(0.0)
        super().changeEvent(e)

    def paintEvent(self, e):
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.state &= ~QStyle.State_MouseOver      # hover is drawn by us, smoothly
        dpr = self.devicePixelRatioF()
        img = QImage(int(self.width() * dpr), int(self.height() * dpr),
                     QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        ip = QPainter(img)
        ip.setRenderHint(QPainter.Antialiasing)
        self.style().drawControl(QStyle.CE_PushButton, opt, ip, self)
        # tint only where the button already has pixels (keeps its rounded shape)
        ip.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        if self._hover > 0:
            ip.fillRect(img.rect(), QColor(255, 255, 255, int(26 * self._hover)))
        if self._press > 0:
            ip.fillRect(img.rect(), QColor(0, 0, 0, int(40 * min(self._press, 1.0))))
        ip.end()

        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = min(1.0, 1.0 - 0.045 * self._press)
        cx, cy = self.width() / 2, self.height() / 2
        p.translate(cx, cy)
        p.scale(s, s)
        p.translate(-cx, -cy)
        p.drawImage(QPointF(0, 0), img)


# ---------------------------------------------------------------------------
class AnimatedStack(QStackedWidget):
    """QStackedWidget that slides and cross-fades between pages."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Transparent")
        self._group = None
        self._overlay = None
        self._incoming = None

    def _finish(self):
        if self._group:
            self._group.stop()
            self._group = None
        if self._overlay:
            self._overlay.deleteLater()
            self._overlay = None
        if self._incoming:
            self._incoming.setGraphicsEffect(None)
            self._incoming.move(0, 0)
            self._incoming = None

    def transition_to(self, widget, direction: int = 1, axis: str = "x", ms: int = 380):
        """direction: 1 = forward (comes from the right/bottom), -1 = back, 0 = fade only."""
        if isinstance(widget, int):
            widget = self.widget(widget)
        old = self.currentWidget()
        self._finish()
        if widget is old or old is None or not ENABLED or not self.isVisible():
            self.setCurrentWidget(widget)
            return

        snap = old.grab()
        self.setCurrentWidget(widget)
        widget.move(0, 0)

        overlay = QLabel(self)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setPixmap(snap)
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.show()
        overlay.raise_()
        self._overlay, self._incoming = overlay, widget

        dist = 70 if axis == "x" else 40
        def pt(v):
            return QPoint(v, 0) if axis == "x" else QPoint(0, v)

        out_fx = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(out_fx)
        in_fx = QGraphicsOpacityEffect(widget)
        in_fx.setOpacity(0.0)
        widget.setGraphicsEffect(in_fx)

        group = QParallelAnimationGroup(self)
        specs = [
            (out_fx, b"opacity", 1.0, 0.0, int(ms * 0.42), QEasingCurve.InQuad),
            (in_fx, b"opacity", 0.0, 1.0, ms, QEasingCurve.Linear),
        ]
        if direction:
            specs += [
                (overlay, b"pos", pt(0), pt(-direction * dist // 2), ms, QEasingCurve.OutCubic),
                (widget, b"pos", pt(direction * dist), pt(0), ms, QEasingCurve.OutCubic),
            ]
        for obj, prop, a, b, dur, curve in specs:
            an = QPropertyAnimation(obj, prop)
            an.setStartValue(a)
            an.setEndValue(b)
            an.setDuration(dur)
            an.setEasingCurve(curve)
            if obj is in_fx:            # new page appears just as the old one leaves
                an.setKeyValueAt(0.28, 0.0)
                an.setKeyValueAt(0.7, 0.92)
            group.addAnimation(an)
        group.finished.connect(self._finish)
        self._group = group
        group.start()

    def resizeEvent(self, e):
        self._finish()
        super().resizeEvent(e)


# ---------------------------------------------------------------------------
def fade_in(widget, ms: int = 320, rise: int = 0):
    """Fade (and optionally float up) a widget that just became visible."""
    if not ENABLED or not widget.isVisible():
        return
    fx = QGraphicsOpacityEffect(widget)
    fx.setOpacity(0.0)
    widget.setGraphicsEffect(fx)
    a = QPropertyAnimation(fx, b"opacity", widget)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setDuration(ms)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start()


def animate_value(bar, value: int, ms: int = 260):
    """Smoothly move a progress bar to `value`."""
    old = getattr(bar, "_value_anim", None)
    if old:
        old.stop()
    if not ENABLED or value < bar.value():
        bar.setValue(value)
        return
    a = QPropertyAnimation(bar, b"value", bar)
    a.setStartValue(bar.value())
    a.setEndValue(value)
    a.setDuration(ms)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.start()
    bar._value_anim = a
