"""Animated, blurred backgrounds and frosted "liquid glass" panels.

Each style is drawn small (which keeps it fast) and then scaled up smoothly,
which gives the soft blur. Glass panels re-draw an even blurrier copy of the
background behind them, tinted, with a bright rim, like Apple's glass.
All styles use the three theme colours.
"""

import math
import random

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QPoint,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QFrame, QWidget

from . import theme

STYLES = {
    "orbs": "Glow Orbs",
    "mesh": "Mesh Gradient",
    "aurora": "Aurora Flow",
    "silk": "Silk Waves",
    "bokeh": "Bokeh Drift",
    "stars": "Starfield",
    "dots": "Dot Grid Wave",
    "rays": "Light Rays",
    "still": "Still (no motion)",
}

CURRENT = None   # the window's BackgroundWidget, used by glass panels


def _mix(a: QColor, b: QColor, f: float) -> QColor:
    f = max(0.0, min(1.0, f))
    return QColor(int(a.red() + (b.red() - a.red()) * f),
                  int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


class BackgroundWidget(QWidget):
    """Paints the animated background; put the rest of the UI inside it."""
    frame_ready = Signal()

    def __init__(self, settings):
        super().__init__()
        global CURRENT
        CURRENT = self
        self.settings = settings
        self.setObjectName("Transparent")
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.t = random.uniform(0, 300)        # animation clock (seconds)
        self.clock = QElapsedTimer()
        self.clock.start()
        self.frame = None                      # small rendered background
        self.frost = None                      # extra-blurry copy for glass
        rng = random.Random(7)
        self.particles = [(rng.random(), rng.random(), rng.random(), rng.random(),
                           rng.randrange(3), rng.random() * 6.28) for _ in range(90)]
        self.grain = self._make_grain()
        self.shade = None                      # darkening + vignette + grain, cached
        self.busy = False                      # a video is being made: animate gently
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.apply_settings()

    # --- settings ----------------------------------------------------------
    def apply_settings(self):
        s = self.settings
        self.style_id = s["bg_style"] if s["bg_style"] in STYLES else "orbs"
        self.blur = int(s["bg_blur"])          # 0..100
        self.speed = int(s["bg_speed"])        # 0..100
        self.bright = int(s["bg_brightness"])  # 20..100
        self.shade = None
        self._retime()
        self._render()
        self.update()

    def set_busy(self, on: bool):
        """While a video renders, the background moves at a lower frame rate so the
        render gets the processor."""
        self.busy = on
        self._retime()

    def _retime(self):
        animate = self.style_id != "still" and self.speed > 0
        if not animate:
            self.timer.stop()
            return
        ms = 66 if self.busy else 33           # 15 or 30 fps
        if not self.timer.isActive() or self.timer.interval() != ms:
            self.timer.start(ms)

    def _on_screen(self) -> bool:
        win = self.window()
        return win.isVisible() and not win.isMinimized()

    def _tick(self):
        dt = min(self.clock.restart() / 1000.0, 0.1)
        self.t += dt * (0.08 + self.speed / 100 * 1.6)
        if not self._on_screen():      # in the tray or minimized: no drawing at all
            return
        self._render()
        self.update()

    # --- rendering ---------------------------------------------------------
    def _make_grain(self) -> QPixmap:
        img = QImage(160, 160, QImage.Format_ARGB32_Premultiplied)
        rng = random.Random(3)
        for y in range(160):
            for x in range(160):
                v = rng.randrange(256)
                a = rng.randrange(0, 12)
                img.setPixelColor(x, y, QColor(v, v, v, a))
        return QPixmap.fromImage(img)

    def _render(self):
        if self.width() < 2 or self.height() < 2:
            return
        div = 2.5 + self.blur / 100 * 11          # bigger = softer
        w = max(32, int(self.width() / div))
        h = max(24, int(self.height() / div))
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(6, 7, 10))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        t = 0.0 if self.style_id == "still" else self.t
        cols = [theme.color("primary"), theme.color("secondary"), theme.color("tertiary")]
        getattr(self, "_draw_" + ("mesh" if self.style_id == "still" else self.style_id))(p, w, h, t, cols)
        p.end()
        # extra softening passes for higher blur settings
        for _ in range(int(self.blur >= 35) + int(self.blur >= 70)):
            img = img.scaled(max(8, w // 2), max(6, h // 2), Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation).scaled(w, h, Qt.IgnoreAspectRatio,
                                                              Qt.SmoothTransformation)
        self.frame = img
        self.frost = img.scaled(max(8, w // 3), max(6, h // 3), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        self.frame_ready.emit()

    def resizeEvent(self, e):
        self.shade = None
        self._render()
        super().resizeEvent(e)

    def _shade(self) -> QPixmap:
        """Everything drawn over the moving colors that doesn't move: made once per
        window size, not 30 times a second."""
        if self.shade is None or self.shade.size() != self.size() * self.devicePixelRatioF():
            dpr = self.devicePixelRatioF()
            pm = QPixmap(self.size() * dpr)
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            r = QRectF(self.rect())
            # darken for readability
            p.fillRect(r, QColor(4, 5, 8, int(255 * (1 - self.bright / 100) * 0.9)))
            # vignette
            rad = max(self.width(), self.height()) * 0.75
            g = QRadialGradient(QPointF(self.width() / 2, self.height() / 2), rad)
            g.setColorAt(0.55, QColor(0, 0, 0, 0))
            g.setColorAt(1.0, QColor(0, 0, 0, 150))
            p.fillRect(r, g)
            p.drawTiledPixmap(self.rect(), self.grain)
            p.end()
            self.shade = pm
        return self.shade

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.frame is None:
            self._render()
        p.drawImage(QRectF(self.rect()), self.frame)
        p.drawPixmap(0, 0, self._shade())

    # --- styles (w, h are the small render size; t is seconds) ---------------
    @staticmethod
    def _c(c: QColor, a: int) -> QColor:
        c = QColor(c)
        c.setAlpha(max(0, min(255, int(a))))
        return c

    def _blob(self, p, x, y, r, c, a_mid, a_core):
        g = QRadialGradient(QPointF(x, y), r)
        g.setColorAt(0.0, self._c(c, a_core))
        g.setColorAt(0.45, self._c(c, a_mid))
        g.setColorAt(1.0, self._c(c, 0))
        p.setBrush(g)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, y), r, r)

    def _draw_orbs(self, p, w, h, t, cols):
        s = min(w, h)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for i in range(6):
            x = w * (0.5 + 0.42 * math.sin(t * 0.13 * (1 + i * 0.17) + i * 1.7))
            y = h * (0.5 + 0.40 * math.cos(t * 0.11 * (1 + i * 0.23) + i * 2.3))
            r = s * (0.42 + 0.12 * math.sin(t * 0.21 + i))
            self._blob(p, x, y, r, cols[i % 3], 70, 170)

    def _draw_mesh(self, p, w, h, t, cols):
        s = max(w, h)
        p.fillRect(0, 0, w, h, cols[2].darker(400))
        pts = [(0.15, 0.2), (0.85, 0.25), (0.3, 0.85), (0.8, 0.8), (0.5, 0.5)]
        for i, (bx, by) in enumerate(pts):
            x = w * (bx + 0.18 * math.sin(t * 0.07 + i * 2.1))
            y = h * (by + 0.18 * math.cos(t * 0.06 + i * 1.3))
            self._blob(p, x, y, s * (0.55 + 0.1 * math.sin(t * 0.1 + i)), cols[i % 3], 120, 210)

    def _draw_aurora(self, p, w, h, t, cols):
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(3, 4, 9))
        g.setColorAt(1, cols[2].darker(600))
        p.fillRect(0, 0, w, h, g)
        p.setPen(Qt.NoPen)
        for (x, y, z, _, _, ph) in self.particles[:60]:
            a = 60 + 60 * math.sin(t * 2.2 + ph)
            p.setBrush(QColor(255, 255, 255, int(a * z)))
            p.drawEllipse(QPointF(x * w, y * h * 0.7), 0.6, 0.6)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        n = 80
        sw = w / n
        for i in range(n):
            xf = i / n
            top = h * (0.12 + 0.12 * math.sin(xf * 6 + t * 0.35) + 0.05 * math.sin(xf * 15 - t * 0.6))
            length = h * (0.38 + 0.16 * math.sin(xf * 9 + t * 0.45))
            k = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(xf * 22 + t * 0.9))
            c = _mix(cols[0], cols[1], xf * 2) if xf < 0.5 else _mix(cols[1], cols[2], xf * 2 - 1)
            g = QLinearGradient(0, top, 0, top + length)
            g.setColorAt(0.0, self._c(c, 0))
            g.setColorAt(0.12, self._c(c, 190 * k))
            g.setColorAt(0.5, self._c(c, 70 * k))
            g.setColorAt(1.0, self._c(c, 0))
            p.fillRect(QRectF(i * sw, top, sw + 1, length), g)

    def _draw_silk(self, p, w, h, t, cols):
        p.fillRect(0, 0, w, h, QColor(5, 6, 10))
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        steps = 48
        for k in range(5):
            base = h * (0.22 + 0.15 * k)
            amp = h * (0.08 + 0.02 * k)
            thick = h * 0.22
            top = []
            for j in range(steps + 1):
                x = w * j / steps
                y = (base + amp * math.sin(j / steps * 6.28 * (0.8 + 0.2 * k) + t * (0.35 + 0.07 * k) + k)
                     + amp * 0.4 * math.sin(j / steps * 14 - t * 0.5 + k * 2))
                top.append(QPointF(x, y))
            poly = QPolygonF(top + [QPointF(pt.x(), pt.y() + thick) for pt in reversed(top)])
            c = cols[k % 3]
            g = QLinearGradient(0, base - amp, 0, base + thick + amp)
            g.setColorAt(0, self._c(c, 150))
            g.setColorAt(1, self._c(c, 0))
            p.setBrush(g)
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)
            p.setPen(QPen(self._c(c.lighter(150), 120), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(top))

    def _draw_bokeh(self, p, w, h, t, cols):
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, cols[2].darker(700))
        g.setColorAt(1, cols[0].darker(800))
        p.fillRect(0, 0, w, h, g)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        s = min(w, h)
        for (x0, y0, z, sp, ci, ph) in self.particles[:34]:
            r = s * (0.04 + 0.12 * z)
            x = ((x0 + t * 0.01 * (0.3 + z) + 0.05 * math.sin(t * 0.2 + ph)) % 1.2 - 0.1) * w
            y = ((y0 - t * 0.012 * (0.4 + sp)) % 1.2 - 0.1) * h
            c = cols[ci]
            a = 45 + 35 * math.sin(t * 0.6 + ph)
            gr = QRadialGradient(QPointF(x, y), r)
            gr.setColorAt(0.0, self._c(c, a * 0.6))
            gr.setColorAt(0.8, self._c(c, a * 1.3))
            gr.setColorAt(1.0, self._c(c, 0))
            p.setBrush(gr)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(x, y), r, r)

    def _draw_stars(self, p, w, h, t, cols):
        p.fillRect(0, 0, w, h, QColor(3, 4, 8))
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        s = max(w, h)
        for i in range(3):   # nebula band
            f = (i + 0.5) / 3
            self._blob(p, w * f, h * (0.75 - 0.5 * f) + h * 0.05 * math.sin(t * 0.1 + i),
                       s * 0.38, cols[i], 35, 80)
        p.setPen(Qt.NoPen)
        for n, (x0, y0, z, sp, ci, ph) in enumerate(self.particles):
            layer = n % 3
            x = ((x0 - t * 0.004 * (layer + 1)) % 1.0) * w
            y = y0 * h
            a = (90 + 70 * math.sin(t * (1.5 + sp) + ph)) * (0.5 + layer * 0.25)
            c = QColor(255, 255, 255) if ci else _mix(cols[0], QColor(255, 255, 255), 0.6)
            p.setBrush(self._c(c, a))
            p.drawEllipse(QPointF(x, y), 0.5 + layer * 0.45, 0.5 + layer * 0.45)
        cyc = t % 9.0                                # shooting star
        if cyc < 1.2:
            f = cyc / 1.2
            sx, sy = w * (0.2 + 0.6 * f), h * (0.1 + 0.3 * f)
            g = QLinearGradient(sx, sy, sx - w * 0.12, sy - h * 0.06)
            g.setColorAt(0, QColor(255, 255, 255, int(220 * (1 - f))))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(QPen(g, 1.2))
            p.drawLine(QPointF(sx, sy), QPointF(sx - w * 0.12, sy - h * 0.06))

    def _draw_dots(self, p, w, h, t, cols):
        p.fillRect(0, 0, w, h, QColor(5, 6, 10))
        sp = max(4.0, min(w, h) / 13)
        p.setPen(Qt.NoPen)
        cx1, cy1 = w * (0.3 + 0.2 * math.sin(t * 0.13)), h * (0.4 + 0.2 * math.cos(t * 0.11))
        cx2, cy2 = w * (0.75 + 0.15 * math.cos(t * 0.09)), h * (0.7 + 0.15 * math.sin(t * 0.12))
        y = sp / 2
        while y < h:
            x = sp / 2
            while x < w:
                d1 = math.hypot(x - cx1, y - cy1) / sp
                d2 = math.hypot(x - cx2, y - cy2) / sp
                v = 0.5 + 0.25 * math.sin(d1 * 0.9 - t * 1.6) + 0.25 * math.sin(d2 * 0.7 - t * 1.2)
                xf = x / w
                c = _mix(cols[0], cols[1], xf * 2) if xf < 0.5 else _mix(cols[1], cols[2], xf * 2 - 1)
                p.setBrush(self._c(c, 40 + 200 * v * v))
                r = sp * (0.12 + 0.2 * v)
                p.drawEllipse(QPointF(x, y), r, r)
                x += sp
            y += sp

    def _draw_rays(self, p, w, h, t, cols):
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, cols[2].darker(500))
        g.setColorAt(1, QColor(3, 4, 8))
        p.fillRect(0, 0, w, h, g)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        ox, oy = w * (0.18 + 0.04 * math.sin(t * 0.15)), -h * 0.08
        L = math.hypot(w, h) * 1.3
        for i in range(11):
            a = 0.35 + i * 0.11 + 0.05 * math.sin(t * 0.25 + i * 1.3)
            spread = 0.035 + 0.025 * (0.5 + 0.5 * math.sin(t * 0.4 + i * 2.1))
            c = cols[i % 3]
            gr = QRadialGradient(QPointF(ox, oy), L)
            gr.setColorAt(0, self._c(c, 120))
            gr.setColorAt(0.6, self._c(c, 35))
            gr.setColorAt(1, self._c(c, 0))
            poly = QPolygonF([QPointF(ox, oy),
                              QPointF(ox + L * math.cos(a - spread), oy + L * math.sin(a - spread)),
                              QPointF(ox + L * math.cos(a + spread), oy + L * math.sin(a + spread))])
            p.setBrush(gr)
            p.setPen(Qt.NoPen)
            p.drawPolygon(poly)
        self._blob(p, ox, oy + h * 0.05, min(w, h) * 0.35, cols[0], 80, 200)
        p.setPen(Qt.NoPen)
        for (x0, y0, z, sp, ci, ph) in self.particles[:40]:
            x = ((x0 + t * 0.006 * (0.5 + sp)) % 1.0) * w
            y = ((y0 + t * 0.004 * (0.5 + z)) % 1.0) * h
            p.setBrush(QColor(255, 255, 255, int(40 + 40 * math.sin(t + ph))))
            p.drawEllipse(QPointF(x, y), 0.6, 0.6)


class GlassFrame(QFrame):
    """Frosted glass panel: blurred background behind it, tint, bright rim."""
    clicked = Signal()

    def __init__(self, radius: int = 20, clickable: bool = False, strength: float = 1.0):
        super().__init__()
        self.setObjectName("Transparent")
        self.radius = radius
        self.clickable = clickable
        self.strength = strength
        self.selected = False
        self._sel = 0.0      # animated 0..1
        self._hover = 0.0    # animated 0..1
        self._anims = {}
        if clickable:
            self.setCursor(Qt.PointingHandCursor)

    def _animate(self, name, to, ms):
        from . import anim
        cur = getattr(self, name)
        if not anim.ENABLED:
            setattr(self, name, to)
            self.update()
            return
        old = self._anims.get(name)
        if old:
            old.stop()
        a = QVariantAnimation(self)
        a.setStartValue(cur)
        a.setEndValue(to)
        a.setDuration(ms)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v: (setattr(self, name, float(v)), self.update()))
        a.start()
        self._anims[name] = a

    def set_selected(self, on: bool):
        self.selected = on
        self._animate("_sel", 1.0 if on else 0.0, 300)

    def enterEvent(self, e):
        if self.clickable:
            self._animate("_hover", 1.0, 200)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.clickable:
            self._animate("_hover", 0.0, 320)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if self.clickable:
            self.clicked.emit()
        super().mousePressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        bg = CURRENT
        if bg is not None and bg.frost is not None and bg.width() > 0:
            pos = self.mapTo(bg, QPoint(0, 0))
            fx = bg.frost.width() / bg.width()
            fy = bg.frost.height() / bg.height()
            src = QRectF(pos.x() * fx, pos.y() * fy, self.width() * fx, self.height() * fy)
            p.save()
            p.setClipPath(path)
            p.drawImage(r, bg.frost, src)
            p.restore()
        tint = QColor(12, 14, 18, int(150 * self.strength * (1 - 0.25 * self._hover)))
        p.fillPath(path, tint)
        if self._sel > 0:
            sel = theme.color("primary")
            sel.setAlpha(int(38 * self._sel))
            p.fillPath(path, sel)
        if self._hover > 0:
            p.fillPath(path, QColor(255, 255, 255, int(10 * self._hover)))
        hl = QLinearGradient(0, 0, 0, self.height())
        hl.setColorAt(0, QColor(255, 255, 255, 30))
        hl.setColorAt(0.35, QColor(255, 255, 255, 6))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)
        rim = QLinearGradient(0, 0, 0, self.height())
        rim.setColorAt(0, QColor(255, 255, 255, int(70 + 60 * self._hover)))
        rim.setColorAt(1, QColor(255, 255, 255, int(18 + 30 * self._hover)))
        p.setPen(QPen(rim, 1))
        p.drawPath(path)
        if self._sel > 0:
            c = theme.color("primary")
            c.setAlpha(int(255 * self._sel))
            p.setPen(QPen(c, 2))
            p.drawPath(path)
