"""Step 3: Layout. Pick the video's shape and quality, then place the post
on a life-size phone preview that shows exactly what the video will look like."""

import time
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import layout as L
from ..library import find_videos
from ..settings import cache_dir
from . import anim, theme
from .background import GlassFrame
from .common import Card, button, label, page_header, run_task

REVEAL_CHOICES = [
    ("fade", "Fade in each line", "Every line fades in just before the voice reads it"),
    ("slide", "Slide down", "The post is cropped, and the crop glides down to each "
                            "line as it's read"),
    ("off", "Show whole post", "The whole post is on screen from the start"),
]


def _lerp(a, b, t):
    return a + (b - a) * t


def _screen_aspect(fmt):
    """The phone's screen: landscape for widescreen, portrait for the rest."""
    return 16 / 9 if L.aspect(fmt) > 1 else 9 / 16


# ----------------------------------------------------------------------------
class ShapeIcon(QWidget):
    """A bordered rectangle in the exact shape of a format."""

    def __init__(self, ratio: float, owner: GlassFrame, box=46, scale=1.0):
        super().__init__()
        self.ratio, self.owner, self.scale = ratio, owner, scale
        self.setFixedSize(box, box)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_shape(self, ratio=None, scale=None):
        if ratio is not None:
            self.ratio = ratio
        if scale is not None:
            self.scale = scale
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = (min(self.width(), self.height()) - 4) * self.scale
        w, h = (s, s / self.ratio) if self.ratio >= 1 else (s * self.ratio, s)
        r = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
        sel = getattr(self.owner, "_sel", 0.0)
        c = QColor(theme.color("primary"))
        muted = QColor(255, 255, 255, 120)
        col = QColor(int(_lerp(muted.red(), c.red(), sel)), int(_lerp(muted.green(), c.green(), sel)),
                     int(_lerp(muted.blue(), c.blue(), sel)), int(_lerp(120, 255, sel)))
        fill = QColor(c)
        fill.setAlpha(int(45 * sel))
        p.setBrush(fill)
        p.setPen(QPen(col, 2.0))
        p.drawRoundedRect(r, 4, 4)


class FormatCard(GlassFrame):
    def __init__(self, key: str):
        super().__init__(radius=16, clickable=True)
        info = L.FORMATS[key]
        self.key = key
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        self.icon = ShapeIcon(L.aspect(key), self)
        row.addWidget(self.icon, 0, Qt.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(label(f"<b>{info['name']}</b>  <span style='color:{theme.MUTED}'>"
                            f"{key}</span>"))
        col.addWidget(label(info["uses"], "Hint", wrap=True))
        row.addLayout(col, 1)

    def update(self, *a):
        super().update(*a)
        self.icon.update()


class QualityCard(GlassFrame):
    def __init__(self, key: str):
        super().__init__(radius=14, clickable=True)
        self.key = key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(2)
        short = L.RESOLUTIONS[key][0]
        self.icon = ShapeIcon(9 / 16, self, box=40, scale=0.45 + 0.55 * short / 2160)
        lay.addWidget(self.icon, 0, Qt.AlignHCenter)
        name = label(f"<b>{key}</b>")
        name.setAlignment(Qt.AlignCenter)
        lay.addWidget(name)
        self.size_label = label("", "Hint")
        self.size_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.size_label)
        self.setToolTip(L.RESOLUTIONS[key][1])

    def set_format(self, fmt):
        w, h = L.output_size(fmt, self.key)
        self.size_label.setText(f"{w} × {h}")
        self.icon.set_shape(ratio=L.aspect(fmt))

    def update(self, *a):
        super().update(*a)
        self.icon.update()


FPS_CHOICES = [(24, "Film", "24 frames a second, like movies. Best for movie clips."),
               (30, "Standard", "30 frames a second: what most short videos use."),
               (60, "Smooth", "60 frames a second: the smoothest gameplay. Takes about "
                              "twice as long to make, and makes bigger files.")]


class FpsCard(GlassFrame):
    def __init__(self, fps: int, name: str, tip: str):
        super().__init__(radius=14, clickable=True)
        self.fps = fps
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(0)
        top = label(f"<b>{fps}</b> fps")
        top.setAlignment(Qt.AlignCenter)
        lay.addWidget(top)
        sub = label(name, "Hint")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        self.setToolTip(tip)


# ----------------------------------------------------------------------------
def placeholder_post() -> QPixmap:
    pm = QPixmap(600, 500)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#f0e0d6"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(0, 0, 600, 500), 18, 18)
    p.setBrush(QColor(0, 0, 0, 40))
    p.drawRoundedRect(QRectF(30, 34, 150, 150), 10, 10)
    for i, w in enumerate([340, 300, 360, 220, 520, 480, 500, 260]):
        x = 210 if i < 4 else 30
        y = 40 + i * 44 + (24 if i >= 4 else 0)
        p.drawRoundedRect(QRectF(x, y, w if x == 30 else min(w, 360), 18), 9, 9)
    p.setPen(QColor(0, 0, 0, 120))
    f = QFont()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 430, 600, 50), Qt.AlignCenter, "Your post goes here")
    p.end()
    return pm


def border_phase() -> float:
    """Where animated borders are in their spin (0..1), shared by every preview."""
    return (time.monotonic() / L.BORDER_PERIOD) % 1.0 if anim.ENABLED else 0.12


def border_brush(style: str, color: str, colors: list[str], centre: QPointF, phase: float):
    """Solid color, or the spinning gradient the renderer uses (same stops and turn)."""
    if not L.BORDER_STYLES.get(style, {}).get("animated"):
        return QColor(color)
    g = QConicalGradient(centre, -phase * 360)
    for pos, c in L.border_stops(style, colors):
        g.setColorAt(pos, QColor(c))
    return g


def theme_colors() -> list[str]:
    return [theme.COLORS[k] for k in ("primary", "secondary", "tertiary")]


class Swatch(QWidget):
    """A round color choice. Animated styles slowly spin, like in the video."""
    clicked = Signal()

    def __init__(self, tip: str, size=24):
        super().__init__()
        self.setFixedSize(size + 6, size + 6)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.color = "#ffffff"
        self.style_key = "solid"
        self.plus = False            # the "pick any color" swatch
        self.selected = False
        self._hover = 0.0

    def enterEvent(self, e):
        anim._anim(self._set_hover, self._hover, 1.0, 140, parent=self)

    def leaveEvent(self, e):
        anim._anim(self._set_hover, self._hover, 0.0, 200, parent=self)

    def _set_hover(self, v):
        self._hover = v
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QRectF(self.rect()).center()
        r = (self.width() - 6) / 2 + self._hover * 1.5
        if self.selected:
            p.setPen(QPen(QColor("#ffffff"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r + 2.2, r + 2.2)
            r -= 1.5
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        if self.plus and not self.color:
            p.setBrush(QColor(255, 255, 255, 18))
        else:
            p.setBrush(border_brush(self.style_key, self.color, theme_colors(), c,
                                    border_phase()))
        p.drawEllipse(c, r, r)
        if self.plus:
            p.setPen(QPen(QColor(255, 255, 255, 230) if not self.color else QColor(0, 0, 0, 170),
                          1.8))
            p.drawLine(QPointF(c.x() - r * 0.4, c.y()), QPointF(c.x() + r * 0.4, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - r * 0.4), QPointF(c.x(), c.y() + r * 0.4))


class PhoneCanvas(QWidget):
    """A phone showing the video. Drag the post to move it, drag a corner to resize."""
    box_changed = Signal(dict)      # while moving
    box_committed = Signal(dict)    # when a move / resize finishes
    brand_moved = Signal(str, float, float)   # watermark / end card dragged
    brand_committed = Signal(str)

    HANDLE = 7
    SNAP_PX = 9

    def __init__(self):
        super().__init__()
        self.setMinimumSize(QSize(280, 380))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.fmt = L.DEFAULT_FORMAT
        self.sa = _screen_aspect(self.fmt)       # screen aspect (animated)
        self.va = L.aspect(self.fmt)             # video aspect (animated)
        self.post = placeholder_post()
        self.post_aspect = self.post.width() / self.post.height()
        self.bg = None
        self.box = L.default_box(self.fmt, self.post_aspect)
        self.overlay = True
        self.round = 0.0            # corner rounding 0..1 (1 = oval)
        self.shadow = 0.0           # 0 = none, else strength 0..1
        self.border = 0.0           # thickness in pixels at 1080p, 0 = none
        self.border_style = "solid"
        self.border_color = "#ffffff"
        self.brand = {}             # kind -> {"img", "pos", "frac", "dim"}
        self.brand_show = set()     # kinds drawn on the phone
        self.brand_edit = None      # kind that can be dragged right now
        self.show_post = True       # False = captions only (no post image)
        self.mirror = False         # show the gameplay flipped (as the video will be)
        self.fit = "fill"           # "fill" or "blur" (whole video over a blurred copy)
        self._soft = (None, None)   # (source key, blurred copy) for "blur"
        self._shadow_cache = (None, None)
        self._ticker = QTimer(self)
        self._ticker.setInterval(33)
        self._ticker.timeout.connect(self.update)
        self.mode = None            # None | "move" | "resize"
        self.hover = None           # None | "post" | corner index
        self.guides = set()
        self._shape_anim = None
        self._box_anim = None
        self._target = None         # where a running animation will end up

    # --- inputs --------------------------------------------------------------
    def set_post(self, pixmap: QPixmap | None):
        self.post = pixmap if pixmap and not pixmap.isNull() else placeholder_post()
        self.post_aspect = self.post.width() / self.post.height()
        self.update()

    def set_background(self, pixmap: QPixmap | None):
        self.bg = pixmap if pixmap and not pixmap.isNull() else None
        self.update()

    def set_round(self, amount: float):
        self.round = min(max(amount, 0.0), 1.0)
        self.update()

    def set_style(self, shadow: float, border: float, style: str, color: str):
        self.shadow, self.border = shadow, border
        self.border_style, self.border_color = style, color
        self._tick()
        self.update()

    def animated(self) -> bool:
        return self.border > 0 and L.BORDER_STYLES.get(self.border_style, {}).get("animated", False)

    def _tick(self):
        """Only redraw 30x a second while an animated border is on screen."""
        on = self.animated() and anim.ENABLED and self.isVisible()
        if on and not self._ticker.isActive():
            self._ticker.start()
        elif not on:
            self._ticker.stop()

    def showEvent(self, e):
        super().showEvent(e)
        self._tick()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._ticker.stop()

    def _shadow_image(self, ow, oh, orx, ory, u):
        key = (round(ow), round(oh), round(orx, 1), round(ory, 1), round(self.shadow, 3),
               round(u, 4))
        if self._shadow_cache[0] != key:
            im, pad, _ = L.shadow_image(ow, oh, orx, ory, self.shadow, u)
            q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height,
                       QImage.Format_RGBA8888).copy()
            self._shadow_cache = (key, (q, pad))
        return self._shadow_cache[1]

    def post_path(self, r: QRectF) -> QPainterPath:
        """The post's outline: corners are quarter ellipses, 1.0 = full oval
        (same shape as layout.round_mask, which the renderer uses)."""
        path = QPainterPath()
        if self.round <= 0.004:
            path.addRect(r)
        else:
            path.addRoundedRect(r, self.round * 100, self.round * 100, Qt.RelativeSize)
        return path

    # --- watermark / end card -------------------------------------------------
    def set_brand(self, kind: str, item: dict | None, show: bool):
        if item is None:
            self.brand.pop(kind, None)
            self.brand_show.discard(kind)
        else:
            self.brand[kind] = item
            (self.brand_show.add if show else self.brand_show.discard)(kind)
        self.update()

    def brand_rect(self, kind: str, video: QRectF) -> QRectF | None:
        it = self.brand.get(kind)
        if not it or kind not in self.brand_show:
            return None
        w, h = it["frac"][0] * video.width(), it["frac"][1] * video.height()
        cx = video.left() + it["pos"][0] * video.width()
        cy = video.top() + it["pos"][1] * video.height()
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def _brand_hit(self, pos) -> bool:
        if not self.brand_edit:
            return False
        r = self.brand_rect(self.brand_edit, self.geometry_()[2])
        return bool(r and r.adjusted(-6, -6, 6, 6).contains(pos))

    def _drag_brand(self, centre: QPointF, video: QRectF, free: bool):
        from .brand import clamp_pos
        kind = self.brand_edit
        it = self.brand[kind]
        x = (centre.x() - video.left()) / video.width()
        y = (centre.y() - video.top()) / video.height()
        if kind == "captions":
            x = 0.5                 # captions are always centred across the video
        self.guides = set()
        if not free:
            m = L.margins(self.fmt)
            hy = it["frac"][1] / 2
            if abs(x - 0.5) * video.width() < self.SNAP_PX:
                x = 0.5
                self.guides.add("vcenter")
            for yy, name in ((0.5, "hcenter"), (m["top"] + hy, "top"),
                             (1 - m["bottom"] - hy, "bottom")):
                if abs(y - yy) * video.height() < self.SNAP_PX:
                    y = yy
                    self.guides.add(name)
                    break
        x, y = clamp_pos(x, y, *it["frac"])
        it["pos"] = [x, y]
        self.brand_moved.emit(kind, x, y)

    def _paint_brand(self, p, video):
        end = self.brand.get("endcard")
        if end and "endcard" in self.brand_show and end.get("dim"):
            p.fillRect(video, QColor(0, 0, 0, int(255 * end["dim"])))
        for kind in ("captions", "endcard", "watermark"):
            r = self.brand_rect(kind, video)
            if r is not None:
                p.drawImage(r, self.brand[kind]["img"])

    def set_overlay(self, on: bool):
        self.overlay = on
        self.update()

    def set_picture(self, mirror: bool, fit: str):
        self.mirror, self.fit = mirror, fit
        self.update()

    def target_box(self) -> dict:
        """The box once any running animation finishes."""
        return dict(self._target or self.box)

    def settle(self):
        """Jump any running animation to its end (before the next change)."""
        for a in (self._shape_anim, self._box_anim):
            if a is not None:
                a.stop()
        self._shape_anim = self._box_anim = None
        self.sa, self.va = _screen_aspect(self.fmt), L.aspect(self.fmt)
        if self._target:
            self.box = self._target
        self._target = None
        self.update()

    def set_box(self, box: dict, animate=False):
        self.settle()
        box = L.clamp(box, self.fmt, self.post_aspect)
        self._target = box
        if not animate or not anim.ENABLED:
            self.box = box
            self.update()
            return
        start = dict(self.box)
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(320)
        a.setEasingCurve(QEasingCurve.OutCubic)

        def step(t):
            t = float(t)
            self.box = {k: _lerp(start[k], box[k], t) for k in ("x", "y", "w")}
            self.update()
        a.valueChanged.connect(step)
        a.finished.connect(lambda: self.settle())
        a.start()
        self._box_anim = a

    def set_format(self, fmt: str, box: dict, animate=True):
        old = (self.sa, self.va)
        old_box = dict(self.box)
        for a in (self._shape_anim, self._box_anim):
            if a is not None:
                a.stop()
        self._shape_anim = self._box_anim = None
        self.fmt = fmt
        new = (_screen_aspect(fmt), L.aspect(fmt))
        box = L.clamp(box, fmt, self.post_aspect)
        self._target = box
        if not animate or not anim.ENABLED:
            self.settle()
            return
        a = QVariantAnimation(self)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(480)
        a.setEasingCurve(QEasingCurve.InOutCubic)

        def step(t):
            t = float(t)
            self.sa = _lerp(old[0], new[0], t)
            self.va = _lerp(old[1], new[1], t)
            self.box = {k: _lerp(old_box[k], box[k], t) for k in ("x", "y", "w")}
            self.update()
        a.valueChanged.connect(step)
        a.finished.connect(lambda: self.settle())
        a.start()
        self._shape_anim = a

    # --- geometry --------------------------------------------------------------
    def geometry_(self):
        """(device rect, screen rect, video rect) for the current size."""
        W, H = self.width(), self.height()
        pad = 14
        bezel_frac = 0.045
        # device = screen + bezel on all sides
        avail_w, avail_h = W - 2 * pad, H - 2 * pad
        # solve for screen size that fits once the bezel is added
        sw = min(avail_w, avail_h * self.sa)
        for _ in range(3):
            sh = sw / self.sa
            b = min(sw, sh) * bezel_frac + 6
            sw = min(avail_w - 2 * b, (avail_h - 2 * b) * self.sa)
        sh = sw / self.sa
        b = min(sw, sh) * bezel_frac + 6
        screen = QRectF((W - sw) / 2, (H - sh) / 2, sw, sh)
        device = screen.adjusted(-b, -b, b, b)
        if self.va >= self.sa:          # video as wide as the screen
            vw, vh = sw, sw / self.va
        else:                           # video as tall as the screen
            vw, vh = sh * self.va, sh
        top = screen.top() + (sh - vh) * 0.42
        video = QRectF(screen.left() + (sw - vw) / 2, top, vw, vh)
        return device, screen, video

    def post_rect(self, video: QRectF) -> QRectF:
        x, y, w, h = L.place_post(video.width(), video.height(),
                                  self.post_aspect, 1.0, self.box)
        return QRectF(video.left() + x, video.top() + y, w, h)

    def _corners(self, r: QRectF):
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def _hit(self, pos: QPointF):
        if self.brand_edit or not self.show_post:
            return None
        _, _, video = self.geometry_()
        r = self.post_rect(video)
        for i, c in enumerate(self._corners(r)):
            if (c - pos).manhattanLength() <= self.HANDLE * 2.4:
                return i
        return "post" if r.contains(pos) else None

    # --- mouse -----------------------------------------------------------------
    def _cursor_for(self, hit):
        if hit is None:
            return Qt.ArrowCursor
        if hit == "post":
            return Qt.ClosedHandCursor if self.mode == "move" else Qt.OpenHandCursor
        return Qt.SizeFDiagCursor if hit in (0, 2) else Qt.SizeBDiagCursor

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        self.setFocus()
        self.settle()
        pos = e.position()
        if self._brand_hit(pos):
            r = self.brand_rect(self.brand_edit, self.geometry_()[2])
            self.mode = "brand"
            self._grab = pos - r.center()
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return
        hit = self._hit(pos)
        if hit is None:
            return
        _, _, video = self.geometry_()
        r = self.post_rect(video)
        if hit == "post":
            self.mode = "move"
            self._grab = pos - r.center()
        else:
            self.mode = "resize"
            self._anchor = self._corners(r)[(hit + 2) % 4]
            self._corner = hit
        self.setCursor(self._cursor_for(hit))
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.mode is None:
            if self._brand_hit(pos):
                self.setCursor(Qt.OpenHandCursor)
                return
            hit = self._hit(pos)
            if hit != self.hover:
                self.hover = hit
                self.update()
            self.setCursor(self._cursor_for(hit))
            return
        _, _, video = self.geometry_()
        free = bool(e.modifiers() & Qt.ShiftModifier)
        if self.mode == "brand":
            self._drag_brand(pos - self._grab, video, free)
            self.update()
            return
        if self.mode == "move":
            self._move_to(pos - self._grab, video, free)
        else:
            self._resize_to(pos, video, free)
        self.box_changed.emit(dict(self.box))
        self.update()

    def mouseReleaseEvent(self, e):
        if self.mode == "brand":
            self.mode = None
            self.guides = set()
            self.brand_committed.emit(self.brand_edit)
            self.setCursor(Qt.OpenHandCursor)
            self.update()
            return
        if self.mode is not None:
            self.mode = None
            self.guides = set()
            self.box_committed.emit(dict(self.box))
            self.setCursor(self._cursor_for(self._hit(e.position())))
            self.update()

    def leaveEvent(self, e):
        if self.mode is None and self.hover is not None:
            self.hover = None
            self.update()

    def _move_to(self, centre: QPointF, video: QRectF, free: bool):
        r = self.post_rect(video)
        cx = (centre.x() - video.left()) / video.width()
        cy = (centre.y() - video.top()) / video.height()
        self.guides = set()
        if not free:
            m = L.margins(self.fmt)
            hy = r.height() / video.height() / 2
            if abs(cx - 0.5) * video.width() < self.SNAP_PX:
                cx = 0.5
                self.guides.add("vcenter")
            cands = [(0.5, "hcenter"), (m["top"] + hy, "top"), (1 - m["bottom"] - hy, "bottom")]
            for y, name in cands:
                if abs(cy - y) * video.height() < self.SNAP_PX:
                    cy = y
                    self.guides.add(name)
                    break
        self.box = L.clamp({"x": cx, "y": cy, "w": self.box["w"]}, self.fmt, self.post_aspect)

    def _resize_to(self, pos: QPointF, video: QRectF, free: bool):
        a = self._anchor
        dx = abs(pos.x() - a.x())
        dy = abs(pos.y() - a.y())
        pw = max(dx, dy * self.post_aspect)
        max_w = min(video.width(), video.height() * L.MAX_POST_HEIGHT * self.post_aspect)
        pw = min(max(pw, video.width() * L.MIN_POST_WIDTH), max_w)
        self.guides = set()
        if not free:   # snap to "fit width" with the side margins
            fit = video.width() * (1 - 2 * L.margins(self.fmt)["side"])
            if abs(pw - fit) < self.SNAP_PX and fit <= max_w:
                pw = fit
                self.guides.add("fit")
        ph = pw / self.post_aspect
        left = a.x() - pw if pos.x() < a.x() else a.x()
        top = a.y() - ph if pos.y() < a.y() else a.y()
        cx = (left + pw / 2 - video.left()) / video.width()
        cy = (top + ph / 2 - video.top()) / video.height()
        self.box = L.clamp({"x": cx, "y": cy, "w": pw / video.width()}, self.fmt,
                           self.post_aspect)

    def wheelEvent(self, e):
        if self.brand_edit or not self.show_post:
            return
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        self.settle()
        self.box = L.clamp({**self.box, "w": self.box["w"] * (1 + 0.04 * steps)}, self.fmt,
                           self.post_aspect)
        self.box_changed.emit(dict(self.box))
        self.box_committed.emit(dict(self.box))
        self.update()

    def keyPressEvent(self, e):
        if self.brand_edit or not self.show_post:
            return super().keyPressEvent(e)
        step = 0.02 if e.modifiers() & Qt.ShiftModifier else 0.004
        k = e.key()
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
                 Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if k in moves:
            dx, dy = moves[k]
            box = {**self.box, "x": self.box["x"] + dx, "y": self.box["y"] + dy}
        elif k in (Qt.Key_Plus, Qt.Key_Equal):
            box = {**self.box, "w": self.box["w"] * 1.03}
        elif k == Qt.Key_Minus:
            box = {**self.box, "w": self.box["w"] / 1.03}
        else:
            return super().keyPressEvent(e)
        self.settle()
        self.box = L.clamp(box, self.fmt, self.post_aspect)
        self.box_changed.emit(dict(self.box))
        self.box_committed.emit(dict(self.box))
        self.update()

    # --- painting --------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        device, screen, video = self.geometry_()
        portrait = self.sa < 1
        short = min(device.width(), device.height())
        rad = short * 0.13

        # soft shadow + glow under the phone
        glow = QRadialGradient(device.center(), max(device.width(), device.height()) * 0.62)
        c = theme.color("primary")
        c.setAlpha(38)
        glow.setColorAt(0, c)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)

        # side buttons
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#22252b"))
        if portrait:
            x = device.right() - 1
            p.drawRoundedRect(QRectF(x, device.top() + device.height() * 0.22, 4,
                                     device.height() * 0.11), 2, 2)
            x = device.left() - 3
            for y0, h in ((0.18, 0.05), (0.27, 0.08), (0.37, 0.08)):
                p.drawRoundedRect(QRectF(x, device.top() + device.height() * y0, 4,
                                         device.height() * h), 2, 2)
        else:
            y = device.top() - 3
            p.drawRoundedRect(QRectF(device.left() + device.width() * 0.22, y,
                                     device.width() * 0.11, 4), 2, 2)

        # body
        body = QPainterPath()
        body.addRoundedRect(device, rad, rad)
        g = QLinearGradient(device.topLeft(), device.bottomRight())
        g.setColorAt(0, QColor("#2a2d33"))
        g.setColorAt(0.5, QColor("#121317"))
        g.setColorAt(1, QColor("#1d1f24"))
        p.fillPath(body, g)
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.4))
        p.drawPath(body)

        # screen
        srad = max(rad - (screen.left() - device.left()), 6)
        spath = QPainterPath()
        spath.addRoundedRect(screen, srad, srad)
        p.fillPath(spath, QColor("#050506"))
        p.save()
        p.setClipPath(spath)
        self._paint_feed(p, screen, video)
        p.save()
        p.setClipRect(video)
        self._paint_video(p, video)
        p.restore()
        p.restore()

        # camera island
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#000000"))
        isl = short * 0.075
        if portrait:
            p.drawRoundedRect(QRectF(screen.center().x() - isl * 1.6, screen.top() + isl * 0.35,
                                     isl * 3.2, isl * 0.9), isl * 0.45, isl * 0.45)
        else:
            p.drawRoundedRect(QRectF(screen.left() + isl * 0.35, screen.center().y() - isl * 1.6,
                                     isl * 0.9, isl * 3.2), isl * 0.45, isl * 0.45)

        # post outline, handles, guides (drawn over everything so they're easy to grab)
        self._paint_controls(p, video)

    def _paint_feed(self, p, screen, video):
        """For feed formats: the app's header above the video and buttons below."""
        gap_top = video.top() - screen.top()
        gap_bot = screen.bottom() - video.bottom()
        if gap_top < 24 and gap_bot < 24:
            return
        a = min(1.0, (max(gap_top, gap_bot) - 24) / 40)
        p.setPen(Qt.NoPen)
        u = screen.width() / 30
        if gap_top > 3 * u:
            y = video.top() - 2.6 * u
            p.setBrush(QColor(255, 255, 255, int(70 * a)))
            p.drawEllipse(QPointF(screen.left() + 2 * u, y), u * 0.9, u * 0.9)
            p.drawRoundedRect(QRectF(screen.left() + 3.4 * u, y - u * 0.35, 7 * u, u * 0.7),
                              u * 0.35, u * 0.35)
        if gap_bot > 3 * u:
            y = video.bottom() + 1.6 * u
            p.setBrush(QColor(255, 255, 255, int(80 * a)))
            for i in range(3):
                p.drawEllipse(QPointF(screen.left() + (1.8 + i * 2.4) * u, y), u * 0.7, u * 0.7)
            p.setBrush(QColor(255, 255, 255, int(45 * a)))
            for i, w in enumerate((18, 24, 12)):
                p.drawRoundedRect(QRectF(screen.left() + u, y + (1.6 + i * 1.3) * u, w * u,
                                         u * 0.6), u * 0.3, u * 0.3)

    def _paint_video(self, p, video):
        # gameplay, cropped to fill like the real render
        if self.bg is not None:
            bw, bh = self.bg.width(), self.bg.height()
            va = video.width() / video.height()
            if bw / bh > va:
                sw, sh = bh * va, bh
            else:
                sw, sh = bw, bw / va
            src = QRectF((bw - sw) / 2, (bh - sh) / 2, sw, sh)
            p.save()
            if self.mirror:
                from PySide6.QtGui import QTransform
                p.setTransform(QTransform().translate(2 * video.center().x(), 0).scale(-1, 1),
                               True)
            if self.fit == "blur":
                if self._soft[0] is not self.bg:
                    small = self.bg.copy(src.toRect()).scaled(
                        max(4, int(sw / 24)), max(4, int(sh / 24)), Qt.IgnoreAspectRatio,
                        Qt.SmoothTransformation)
                    self._soft = (self.bg, small)
                p.drawPixmap(video, self._soft[1], QRectF(self._soft[1].rect()))
                p.fillRect(video, QColor(0, 0, 0, 40))
                k = min(video.width() / bw, video.height() / bh)
                fw, fh = bw * k, bh * k
                p.drawPixmap(QRectF(video.center().x() - fw / 2, video.center().y() - fh / 2,
                                    fw, fh), self.bg, QRectF(self.bg.rect()))
            else:
                p.drawPixmap(video, self.bg, src)
            p.restore()
        else:
            g = QLinearGradient(video.topLeft(), video.bottomRight())
            c1, c2 = theme.color("tertiary"), theme.color("secondary")
            c1.setAlpha(120)
            c2.setAlpha(90)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillRect(video, QColor("#101216"))
            p.fillRect(video, g)
            p.setPen(QColor(255, 255, 255, 110))
            f = QFont(self.font())
            f.setPixelSize(max(11, int(video.width() / 18)))
            p.setFont(f)
            p.drawText(video.adjusted(0, 0, 0, -video.height() * 0.06),
                       Qt.AlignHCenter | Qt.AlignBottom, "Gameplay plays here")

        # the post
        if self.show_post:
            self._paint_post(p, video)
        self._paint_brand(p, video)

        # what TikTok / Reels / Shorts draw on top of a vertical video
        if self.overlay and self.fmt == "9:16" and abs(self.va - 9 / 16) < 0.01:
            self._paint_app_overlay(p, video)

    def _paint_post(self, p, video):
        r = self.post_rect(video)
        u = L.unit(video.width(), video.height())
        b = max(1.0, self.border * u) if self.border > 0 else 0.0
        rx, ry = L.corner_radii(r.width(), r.height(), self.round)
        orx, ory = L.outer_radii(rx, ry, b, self.round) if b else (rx, ry)
        outer = r.adjusted(-b, -b, b, b)
        if self.shadow > 0:
            img, pad = self._shadow_image(outer.width(), outer.height(), orx, ory, u)
            p.drawImage(QPointF(outer.left() - pad, outer.top() - pad), img)
        if b:
            ring = QPainterPath()
            if orx > 0.5:
                ring.addRoundedRect(outer, orx, ory)
            else:
                ring.addRect(outer)
            ring = ring.subtracted(self.post_path(r))
            p.fillPath(ring, border_brush(self.border_style, self.border_color, theme_colors(),
                                          outer.center(), border_phase()))
        if self.round > 0.004:
            p.save()
            p.setClipPath(self.post_path(r), Qt.IntersectClip)
            p.drawPixmap(r, self.post, QRectF(self.post.rect()))
            p.restore()
        else:
            p.drawPixmap(r, self.post, QRectF(self.post.rect()))

    def _paint_app_overlay(self, p, v):
        u = v.width() / 30
        g = QLinearGradient(0, v.bottom() - v.height() * 0.3, 0, v.bottom())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 120))
        p.fillRect(QRectF(v.left(), v.bottom() - v.height() * 0.3, v.width(), v.height() * 0.3), g)
        p.setPen(Qt.NoPen)
        white = QColor(255, 255, 255, 190)
        # top tabs
        p.setBrush(QColor(255, 255, 255, 120))
        p.drawRoundedRect(QRectF(v.center().x() - 6.5 * u, v.top() + 3.2 * u, 5 * u, 0.8 * u),
                          0.4 * u, 0.4 * u)
        p.setBrush(white)
        p.drawRoundedRect(QRectF(v.center().x() + 0.8 * u, v.top() + 3.2 * u, 5 * u, 0.8 * u),
                          0.4 * u, 0.4 * u)
        # right-hand buttons
        x = v.right() - 2.6 * u
        y = v.top() + v.height() * 0.5
        p.setBrush(white)
        p.drawEllipse(QPointF(x, y), 1.35 * u, 1.35 * u)
        for i in range(4):
            cy = y + (3.6 + i * 3.1) * u
            p.setBrush(white)
            p.drawEllipse(QPointF(x, cy), 1.0 * u, 1.0 * u)
            p.setBrush(QColor(255, 255, 255, 140))
            p.drawRoundedRect(QRectF(x - 0.9 * u, cy + 1.3 * u, 1.8 * u, 0.5 * u),
                              0.25 * u, 0.25 * u)
        # caption at the bottom
        p.setBrush(white)
        base = v.bottom() - 7.5 * u
        p.drawRoundedRect(QRectF(v.left() + 1.4 * u, base, 8 * u, 0.9 * u), 0.45 * u, 0.45 * u)
        p.setBrush(QColor(255, 255, 255, 150))
        for i, w in enumerate((20, 15)):
            p.drawRoundedRect(QRectF(v.left() + 1.4 * u, base + (1.8 + i * 1.3) * u, w * u,
                                     0.7 * u), 0.35 * u, 0.35 * u)
        p.drawRoundedRect(QRectF(v.left() + 1.4 * u, base + 4.9 * u, 11 * u, 0.7 * u),
                          0.35 * u, 0.35 * u)

    def _paint_controls(self, p, video):
        r = self.post_rect(video)
        pc = theme.color("primary")
        sc = theme.color("secondary")
        active = self.mode is not None or self.hover is not None

        # safe-area lines while dragging
        if self.mode is not None:
            m = L.margins(self.fmt)
            pen = QPen(QColor(255, 255, 255, 70), 1, Qt.DashLine)
            p.setPen(pen)
            for y in (video.top() + m["top"] * video.height(),
                      video.bottom() - m["bottom"] * video.height()):
                p.drawLine(QPointF(video.left(), y), QPointF(video.right(), y))

        # snap guides
        p.setPen(QPen(sc, 1.6))
        if "vcenter" in self.guides:
            p.drawLine(QPointF(video.center().x(), video.top()),
                       QPointF(video.center().x(), video.bottom()))
        if "hcenter" in self.guides:
            p.drawLine(QPointF(video.left(), video.center().y()),
                       QPointF(video.right(), video.center().y()))
        m = L.margins(self.fmt)
        if "top" in self.guides:
            y = video.top() + m["top"] * video.height()
            p.drawLine(QPointF(video.left(), y), QPointF(video.right(), y))
        if "bottom" in self.guides:
            y = video.bottom() - m["bottom"] * video.height()
            p.drawLine(QPointF(video.left(), y), QPointF(video.right(), y))
        if "fit" in self.guides:
            for x in (r.left(), r.right()):
                p.drawLine(QPointF(x, video.top()), QPointF(x, video.bottom()))

        if self.brand_edit:          # placing text: only it can be dragged
            br = self.brand_rect(self.brand_edit, video)
            if br is not None:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(pc, 1.6, Qt.SolidLine if self.mode == "brand" else Qt.DashLine))
                p.drawRoundedRect(br.adjusted(-4, -4, 4, 4), 5, 5)
            return
        if not self.show_post:
            return

        # outline
        if active:
            p.setPen(QPen(pc, 2))
        else:
            c = QColor(255, 255, 255, 150)
            p.setPen(QPen(c, 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.post_path(r))
        if self.round > 0.004 and active:
            # faint box so the corner handles still make sense
            p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.DashLine))
            p.drawRect(r)

        # corner handles
        for i, c in enumerate(self._corners(r)):
            big = self.hover == i or (self.mode == "resize" and self._corner == i)
            rad = self.HANDLE + (2 if big else 0)
            p.setPen(QPen(pc, 2))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(c, rad, rad)

        # size bubble while working
        if self.mode is not None:
            text = f"{round(self.box['w'] * 100)}% wide"
            f = QFont(self.font())
            f.setPixelSize(12)
            f.setBold(True)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(text) + 18
            bub = QRectF(r.center().x() - tw / 2, max(r.top() - 30, video.top() + 4), tw, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 12, 16, 220))
            p.drawRoundedRect(bub, 11, 11)
            p.setPen(QColor("#ffffff"))
            p.drawText(bub, Qt.AlignCenter, text)


# ----------------------------------------------------------------------------
class LayoutPage(QWidget):
    changed = Signal()

    def __init__(self, state):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        s = state.settings
        self.fmt = s["format"] if s["format"] in L.FORMATS else L.DEFAULT_FORMAT
        self.res = s["resolution"] if s["resolution"] in L.RESOLUTIONS else L.DEFAULT_RESOLUTION
        self._bg_source = None
        self._post_source = None

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 26, 36, 10)
        root.setSpacing(16)
        root.addLayout(page_header(
            "Lay it out",
            "Pick the video's shape, then drag the post where you want it. "
            "The phone shows exactly what viewers will see."))

        cols = QHBoxLayout()
        cols.setSpacing(18)

        # --- left: shape + quality -------------------------------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("Transparent")
        left = QVBoxLayout(inner)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(10)
        scroll.setWidget(inner)
        scroll.viewport().setAutoFillBackground(False)

        left.addWidget(label("Shape", "Section"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.format_cards = {}
        for i, key in enumerate(L.FORMATS):
            card = FormatCard(key)
            card.clicked.connect(lambda k=key: self.set_format(k))
            grid.addWidget(card, i // 2, i % 2)
            self.format_cards[key] = card
        left.addLayout(grid)

        left.addSpacing(8)
        left.addWidget(label("Quality", "Section"))
        qrow = QHBoxLayout()
        qrow.setSpacing(8)
        self.quality_cards = {}
        for key in L.RESOLUTIONS:
            card = QualityCard(key)
            card.clicked.connect(lambda k=key: self.set_resolution(k))
            qrow.addWidget(card, 1)
            self.quality_cards[key] = card
        left.addLayout(qrow)
        self.quality_hint = label("", "Hint", wrap=True)
        left.addWidget(self.quality_hint)

        left.addSpacing(8)
        left.addWidget(label("Frame rate", "Section"))
        frow = QHBoxLayout()
        frow.setSpacing(8)
        self.fps_cards = {}
        for fps, name, tip in FPS_CHOICES:
            card = FpsCard(fps, name, tip)
            card.clicked.connect(lambda f=fps: self.set_fps(f))
            frow.addWidget(card, 1)
            self.fps_cards[fps] = card
        left.addLayout(frow)
        self.fps_hint = label("", "Hint", wrap=True)
        left.addWidget(self.fps_hint)

        left.addSpacing(8)
        left.addWidget(label("Video", "Section"))
        vgrid = QGridLayout()
        vgrid.setHorizontalSpacing(10)
        vgrid.setVerticalSpacing(6)
        vgrid.addWidget(label("Mirror"), 0, 0)
        self.mirror_box = QComboBox()
        for key, name, tip in (("off", "Off", "The video as it is"),
                               ("on", "Mirrored", "Flipped left to right the whole time"),
                               ("random", "Random flips",
                                "Flips back and forth every couple of seconds")):
            self.mirror_box.addItem(name, key)
            self.mirror_box.setItemData(self.mirror_box.count() - 1, tip, Qt.ToolTipRole)
        self.mirror_box.setToolTip("Flip the gameplay or clip left to right. Text, the post "
                                   "and your handle are never flipped.")
        self.mirror_box.currentIndexChanged.connect(self._picture_changed)
        vgrid.addWidget(self.mirror_box, 0, 1)
        vgrid.addWidget(label("Fit"), 1, 0)
        self.fit_box = QComboBox()
        for key, name, tip in (("fill", "Fill the screen", "Crops the sides so the video "
                                "fills the whole frame"),
                               ("blur", "Whole video, blurred behind",
                                "Nothing cut off: the full video in the middle, over a "
                                "blurred copy of itself. Good for wide movie clips.")):
            self.fit_box.addItem(name, key)
            self.fit_box.setItemData(self.fit_box.count() - 1, tip, Qt.ToolTipRole)
        self.fit_box.currentIndexChanged.connect(self._picture_changed)
        vgrid.addWidget(self.fit_box, 1, 1)
        vgrid.setColumnStretch(1, 1)
        left.addLayout(vgrid)
        left.addStretch()
        cols.addWidget(scroll, 10)

        # --- middle: the phone -------------------------------------------------
        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.canvas = PhoneCanvas()
        self.canvas.box_changed.connect(lambda b: self._sync_controls())
        self.canvas.box_committed.connect(lambda b: self._save())
        mid.addWidget(self.canvas, 1)
        urow = QHBoxLayout()
        urow.addStretch()
        self.undo_btn = button("↶  Undo", "Link", self.undo, tip="Undo (Ctrl+Z)")
        self.redo_btn = button("↷  Redo", "Link", self.redo, tip="Redo (Ctrl+Y)")
        self.readout = label("", "Hint")
        self.readout.setAlignment(Qt.AlignCenter)
        urow.addWidget(self.undo_btn)
        urow.addSpacing(10)
        urow.addWidget(self.readout)
        urow.addSpacing(10)
        urow.addWidget(self.redo_btn)
        urow.addStretch()
        mid.addLayout(urow)
        self.tip = label("", "Hint", wrap=True)
        self.tip.setAlignment(Qt.AlignCenter)
        mid.addWidget(self.tip)
        cols.addLayout(mid, 8)

        # --- right: tools for the post -------------------------------------------
        tools = Card()
        tools.setFixedWidth(262)
        tools.body.setContentsMargins(10, 12, 10, 12)
        tools.body.setSpacing(4)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("ToolTabs")
        self.tabs.setDocumentMode(False)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.setStyleSheet("QTabWidget#ToolTabs::tab-bar { alignment: center; }"
                                "QTabWidget#ToolTabs QTabBar::tab { padding: 8px 7px; }")
        tools.body.addWidget(self.tabs, 1)

        def page():
            w = QWidget()
            w.setObjectName("Transparent")
            lay = QVBoxLayout(w)
            lay.setContentsMargins(4, 10, 4, 0)
            lay.setSpacing(7)
            return w, lay

        def slider_head(text):
            row = QHBoxLayout()
            row.addWidget(label(text, "Hint"))
            row.addStretch()
            value = label("", "Muted")
            row.addWidget(value)
            return row, value

        # Place tab
        place, pl = page()
        pl.addWidget(label("Snap to", "Hint"))
        for text, where, tip in (("⤒   Top", "top", "Centre it near the top"),
                                 ("◎   Center", "center", "Put it right in the middle"),
                                 ("⤓   Bottom", "bottom", "Centre it near the bottom")):
            pl.addWidget(button(text, on_click=lambda _=False, w=where: self.snap(w), tip=tip))
        pl.addSpacing(6)
        row, self.size_label = slider_head("Size")
        pl.addLayout(row)
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(int(L.MIN_POST_WIDTH * 100), 100)
        self.size.valueChanged.connect(self._size_slid)
        self.size.sliderReleased.connect(self._save)
        pl.addWidget(self.size)
        pl.addWidget(button("↔   Fit width", on_click=self.fit_width,
                            tip="As wide as it can go, with a small margin"))
        pl.addSpacing(6)
        pl.addWidget(button("↺   Reset", on_click=self.reset_layout,
                            tip="Back to the default spot and size for this shape"))
        pl.addSpacing(4)
        self.overlay = QCheckBox("Show app buttons")
        self.overlay.setToolTip("TikTok, Reels and Shorts draw buttons and a caption over "
                                "these spots. Keep the post clear of them.")
        self.overlay.setChecked(bool(s["show_app_overlay"]))
        self.overlay.toggled.connect(self._overlay_toggled)
        pl.addWidget(self.overlay)
        pl.addStretch()
        self.tabs.addTab(place, "Place")

        # Style tab
        style, sl = page()
        row, self.round_label = slider_head("Corners")
        sl.addLayout(row)
        self.round = QSlider(Qt.Horizontal)
        self.round.setRange(0, 100)
        self.round.setToolTip("Round off the post's corners. All the way right makes "
                              "it an oval (or a circle if the post is square).")
        self.round.setValue(int(s["post_round"] or 0))
        self.round.valueChanged.connect(self._round_slid)
        self.round.sliderReleased.connect(self._save_round)
        sl.addWidget(self.round)

        sl.addSpacing(4)
        self.shadow_on = QCheckBox("Drop shadow")
        self.shadow_on.setToolTip("A soft shadow under the post so it stands out from busy "
                                  "gameplay")
        self.shadow_on.setChecked(bool(s["post_shadow"]))
        self.shadow_on.toggled.connect(lambda _: self._style_changed())
        row = QHBoxLayout()
        row.addWidget(self.shadow_on)
        row.addStretch()
        self.shadow_label = label("", "Muted")
        row.addWidget(self.shadow_label)
        sl.addLayout(row)
        self.shadow = QSlider(Qt.Horizontal)
        self.shadow.setRange(0, 100)
        self.shadow.setToolTip("How strong the shadow is")
        self.shadow.setValue(int(s["post_shadow_strength"]))
        self.shadow.valueChanged.connect(lambda _: self._style_changed(turn_on=self.shadow_on))
        sl.addWidget(self.shadow)

        sl.addSpacing(4)
        self.border_on = QCheckBox("Border")
        self.border_on.setToolTip("An outline around the post")
        self.border_on.setChecked(bool(s["post_border"]))
        self.border_on.toggled.connect(lambda _: self._style_changed())
        row = QHBoxLayout()
        row.addWidget(self.border_on)
        row.addStretch()
        self.border_label = label("", "Muted")
        row.addWidget(self.border_label)
        sl.addLayout(row)
        self.border_w = QSlider(Qt.Horizontal)
        self.border_w.setRange(2, 40)
        self.border_w.setToolTip("Border thickness")
        self.border_w.setValue(int(s["post_border_width"]))
        self.border_w.valueChanged.connect(lambda _: self._style_changed(turn_on=self.border_on))
        sl.addWidget(self.border_w)

        self.border_style = s["post_border_style"] if s["post_border_style"] in L.BORDER_STYLES \
            else "solid"
        self.border_color = s["post_border_color"] or "primary"
        self.swatches = []
        sl.addWidget(label("Color", "Hint"))
        grid = QGridLayout()
        grid.setSpacing(2)
        solid = [("primary", "Your main color"), ("secondary", "Your second color"),
                 ("tertiary", "Your third color"), ("#ffffff", "White"), ("#000000", "Black"),
                 ("custom", "Pick any color")]
        for i, (key, tip) in enumerate(solid):
            sw = Swatch(tip)
            sw.key = ("solid", key)
            sw.plus = key == "custom"
            sw.clicked.connect(lambda w=sw: self._pick_swatch(w))
            grid.addWidget(sw, 0, i)
            self.swatches.append(sw)
        sl.addLayout(grid)
        sl.addWidget(label("Animated", "Hint"))
        arow = QHBoxLayout()
        arow.setSpacing(2)
        for key, info in L.BORDER_STYLES.items():
            if not info["animated"]:
                continue
            sw = Swatch(f"{info['name']}: {info['tip']}")
            sw.key = (key, None)
            sw.style_key = key
            sw.clicked.connect(lambda w=sw: self._pick_swatch(w))
            arow.addWidget(sw)
            self.swatches.append(sw)
        arow.addStretch()
        sl.addLayout(arow)
        self.style_name = label("", "Muted", wrap=True)
        sl.addWidget(self.style_name)
        self._swatch_ticker = QTimer(self)
        self._swatch_ticker.setInterval(50)
        self._swatch_ticker.timeout.connect(
            lambda: [w.update() for w in self.swatches if w.style_key != "solid"])
        sl.addSpacing(8)
        sl.addWidget(label("Text reveal", "Hint"))
        self.reveal_box = QComboBox()
        for key, text, tip in REVEAL_CHOICES:
            self.reveal_box.addItem(text, key)
            self.reveal_box.setItemData(self.reveal_box.count() - 1, tip, Qt.ToolTipRole)
        self.reveal_box.setToolTip("How the post's lines appear as the voice reads them")
        self._load_reveal()
        self.reveal_box.currentIndexChanged.connect(self._reveal_changed)
        sl.addWidget(self.reveal_box)
        sl.addStretch()
        sl.addWidget(button("↺   Reset style", on_click=self.reset_style,
                            tip="Square corners, no shadow, no border"))
        self.tabs.addTab(style, "Style")
        self.tabs.addTab(self._brand_tab(s), "Brand")
        self.tabs.addTab(self._captions_tab(), "Captions")
        self.tabs.currentChanged.connect(lambda _: (self._tick_swatches(), self._brand_mode()))
        self.canvas.brand_committed.connect(self._brand_placed)

        cols.addWidget(tools, 0)
        root.addLayout(cols, 1)

        self._undo, self._redo = [], []
        self._last_snap = self._snapshot()
        self._undo_timer = QTimer(self)
        self._undo_timer.setSingleShot(True)
        self._undo_timer.setInterval(450)
        self._undo_timer.timeout.connect(self._record)
        state.settings.listeners.append(self._settings_saved)
        self._undo_buttons()

        self.canvas.set_overlay(self.overlay.isChecked())
        self.canvas.set_round(self.round.value() / 100)
        self._style_changed(save=False)
        self._apply_format(animate=False)
        self._apply_resolution()
        self._load_picture()

    # --- text reveal ------------------------------------------------------------------
    def _load_reveal(self):
        st = self.state.settings
        want = st["reveal_style"] if st["reveal"] else "off"
        self.reveal_box.blockSignals(True)
        self.reveal_box.setCurrentIndex(max(0, self.reveal_box.findData(want)))
        self.reveal_box.blockSignals(False)

    def _reveal_changed(self, _=None):
        key = self.reveal_box.currentData()
        st = self.state.settings
        st.values["reveal"] = key != "off"
        if key != "off":
            st.values["reveal_style"] = key
        st.save()
        self.changed.emit()

    # --- undo / redo ----------------------------------------------------------------
    UNDO_KEYS = ["reveal", "reveal_style", "post_display", "captions", "format", "resolution",
                 "fps", "mirror", "fit", "layouts", "post_round",
                 "post_shadow",
                 "post_shadow_strength", "post_border", "post_border_width", "post_border_style",
                 "post_border_color", "watermark", "endcard", "brand_pos"]

    def _snapshot(self) -> str:
        import json
        st = self.state.settings
        return json.dumps({k: st[k] for k in self.UNDO_KEYS}, sort_keys=True)

    def _settings_saved(self):
        self._undo_timer.start()        # wait for drags / slider moves to finish

    def _record(self):
        snap = self._snapshot()
        if snap == self._last_snap:
            return
        self._undo.append(self._last_snap)
        del self._undo[:-60]            # keep the last 60 steps
        self._redo.clear()
        self._last_snap = snap
        self._undo_buttons()

    def undo(self):
        self._step(self._undo, self._redo)

    def redo(self):
        self._step(self._redo, self._undo)

    def _step(self, src, dst):
        import json
        self._undo_timer.stop()
        self._record()                  # anything not yet recorded counts first
        if not src:
            return
        dst.append(self._last_snap)
        snap = src.pop()
        self._last_snap = snap
        st = self.state.settings
        st.values.update(json.loads(snap))
        st.save()
        self._undo_timer.stop()
        self.reload()
        self._undo_buttons()

    def _undo_buttons(self):
        self.undo_btn.setEnabled(bool(self._undo))
        self.redo_btn.setEnabled(bool(self._redo))

    def reload(self):
        """Re-read everything from the settings (a preset was applied)."""
        st = self.state.settings
        self.canvas.settle()
        self.fmt = st["format"] if st["format"] in L.FORMATS else L.DEFAULT_FORMAT
        self.res = st["resolution"] if st["resolution"] in L.RESOLUTIONS else L.DEFAULT_RESOLUTION
        widgets = (self.round, self.shadow_on, self.shadow, self.border_on, self.border_w)
        for wdg in widgets:
            wdg.blockSignals(True)
        self.round.setValue(int(st["post_round"] or 0))
        self.shadow_on.setChecked(bool(st["post_shadow"]))
        self.shadow.setValue(int(st["post_shadow_strength"]))
        self.border_on.setChecked(bool(st["post_border"]))
        self.border_w.setValue(int(st["post_border_width"]))
        for wdg in widgets:
            wdg.blockSignals(False)
        self.border_style = st["post_border_style"] if st["post_border_style"] in L.BORDER_STYLES \
            else "solid"
        self.border_color = st["post_border_color"] or "primary"
        self.canvas.set_round(self.round.value() / 100)
        self._apply_format(animate=True)
        self._apply_resolution()
        self._style_changed(save=False)
        self._load_reveal()
        self._captions_load()
        self._load_picture()
        self._brand_load()

    # --- wizard hooks -----------------------------------------------------------
    def is_complete(self):
        return True

    def on_enter(self):
        self._load_post()
        self._load_background()
        self.canvas.set_box(self.current_box())
        self._sync_controls()
        self.canvas.setFocus()
        self._style_changed(save=False)
        self._tick_swatches()
        self._captions_load()
        self._brand_load()
        if self.state.settings["clip_only"]:        # just the video: nothing on top
            self.canvas.show_post = False
            self.canvas.set_brand("captions", None, False)
            self.tip.setText("Just the video (no post). Pick the shape, frame rate, mirror "
                             "and fit here.")
        self.canvas.update()

    def on_leave(self):
        self.canvas.settle()
        self._swatch_ticker.stop()

    def refresh_theme(self):
        self._style_changed(save=False)
        for c in list(self.format_cards.values()) + list(self.quality_cards.values()):
            c.update()
        self.canvas.update()

    # --- what to show -----------------------------------------------------------
    def _post_path(self):
        pp = self.state.post_page
        if pp.drop.path:
            return pp.drop.path
        for it in self.state.queue:
            if it.get("image") and it.get("status") != "failed":
                return it["image"]
        return None

    def _load_post(self):
        path = self._post_path()
        if path == self._post_source:
            return
        self._post_source = path
        self.canvas.set_post(QPixmap(path) if path else None)

    def _gameplay_video(self):
        gp = self.state.gameplay_page
        if gp.mode == "file":
            return Path(gp.file) if gp.file and Path(gp.file).is_file() else None
        if gp.folder and Path(gp.folder).is_dir():
            vids = sorted(find_videos(Path(gp.folder)))
            return vids[0] if vids else None
        return None

    def _load_background(self):
        video = self._gameplay_video()
        if video == self._bg_source:
            return
        self._bg_source = video
        if video is None:
            self.canvas.set_background(None)
            return

        def done(path):
            if video == self._bg_source:
                self.canvas.set_background(QPixmap(str(path)) if path else None)
        run_task(self, lambda emit: L.grab_frame(video, cache_dir()), done,
                 lambda msg, e: None)

    # --- layout values ------------------------------------------------------------
    def saved_box(self, fmt=None):
        """The layout the user set for this shape, or None for the default."""
        box = (self.state.settings["layouts"] or {}).get(fmt or self.fmt)
        return dict(box) if box else None

    def current_box(self):
        return self.saved_box() or L.default_box(self.fmt, self.canvas.post_aspect)

    def _save(self):
        layouts = dict(self.state.settings["layouts"] or {})
        layouts[self.fmt] = {k: round(v, 4) for k, v in self.canvas.target_box().items()}
        self.state.settings["layouts"] = layouts

    def _sync_controls(self):
        """Slider and read-out follow the post (its final spot if it's animating)."""
        box = self.canvas.target_box()
        pct = round(box["w"] * 100)
        self.size.blockSignals(True)
        self.size.setValue(pct)
        self.size.blockSignals(False)
        self.size_label.setText(f"{pct}%")
        self.round_label.setText(L.corner_label(self.round.value() / 100,
                                                self.canvas.post_aspect))
        w, h = L.output_size(self.fmt, self.res)
        self.readout.setText(f"{L.FORMATS[self.fmt]['name']} {self.fmt}  ·  {w} × {h}")

    # --- actions ----------------------------------------------------------------
    def set_format(self, fmt):
        if fmt == self.fmt:
            return
        self.fmt = fmt
        self.state.settings["format"] = fmt
        self._apply_format(animate=True)
        self._apply_resolution()
        self.changed.emit()

    def _apply_format(self, animate):
        for k, c in self.format_cards.items():
            c.set_selected(k == self.fmt)
        for c in self.quality_cards.values():
            c.set_format(self.fmt)
        self.canvas.set_format(self.fmt, self.current_box(), animate=animate)
        self.overlay.setVisible(self.fmt == "9:16")
        if hasattr(self, "brand_bar"):
            self._brand_refresh()
        self._sync_controls()

    def set_resolution(self, res):
        self.res = res
        self.state.settings["resolution"] = res
        self._apply_resolution()
        self.changed.emit()

    def _apply_resolution(self):
        for k, c in self.quality_cards.items():
            c.set_selected(k == self.res)
        tip = L.RESOLUTIONS[self.res][1] + "."
        if L.RESOLUTIONS[self.res][0] > 1080:
            tip += " Most apps shrink videos to 1080p, so this mostly makes bigger files."
        self.quality_hint.setText(tip)
        self._sync_controls()

    # --- frame rate, mirror, fit ------------------------------------------------------
    def set_fps(self, fps):
        self.state.settings["fps"] = fps
        self._load_picture()
        self.changed.emit()

    def _picture_changed(self, _=None):
        if getattr(self, "_picture_loading", False):
            return
        st = self.state.settings
        st.values["mirror"] = self.mirror_box.currentData()
        st.values["fit"] = self.fit_box.currentData()
        st.save()
        self._load_picture()
        self.changed.emit()

    def _load_picture(self):
        st = self.state.settings
        fps = int(st["fps"] or 30)
        for f, c in self.fps_cards.items():
            c.set_selected(f == fps)
        self.fps_hint.setText(next((t for f, _, t in FPS_CHOICES if f == fps), ""))
        self._picture_loading = True
        self.mirror_box.setCurrentIndex(max(0, self.mirror_box.findData(st["mirror"] or "off")))
        self.fit_box.setCurrentIndex(max(0, self.fit_box.findData(st["fit"] or "fill")))
        self._picture_loading = False
        self.canvas.set_picture((st["mirror"] or "off") == "on", st["fit"] or "fill")

    def picture_summary(self) -> str:
        st = self.state.settings
        bits = [f"{int(st['fps'] or 30)} fps"]
        if (st["mirror"] or "off") != "off":
            bits.append("mirrored" if st["mirror"] == "on" else "random flips")
        if st["fit"] == "blur":
            bits.append("whole video, blurred behind")
        return " · ".join(bits)

    def _move(self, box):
        self.canvas.set_box(box, animate=True)
        self._save()
        self._sync_controls()

    def snap(self, where):
        self.canvas.settle()
        self._move(L.snap(self.fmt, where, self.canvas.box, self.canvas.post_aspect))

    def fit_width(self):
        self.canvas.settle()
        self._move(L.fit_width(self.fmt, self.canvas.box, self.canvas.post_aspect))

    def reset_layout(self):
        layouts = dict(self.state.settings["layouts"] or {})
        layouts.pop(self.fmt, None)
        self.state.settings["layouts"] = layouts
        self.canvas.set_box(L.default_box(self.fmt, self.canvas.post_aspect), animate=True)
        self._sync_controls()

    # --- brand: watermark and end card ----------------------------------------------
    def _brand_tab(self, s):
        from . import brand as B
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.viewport().setAutoFillBackground(False)
        w = QWidget()
        w.setObjectName("Transparent")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 6, 4)
        lay.setSpacing(6)
        outer.setWidget(w)

        self.brand_bar = QTabBar()
        self.brand_bar.addTab("Watermark")
        self.brand_bar.addTab("End card")
        self.brand_bar.setExpanding(True)
        self.brand_bar.setDrawBase(False)
        self.brand_bar.currentChanged.connect(lambda _: self._brand_load())
        lay.addWidget(self.brand_bar)

        self.b_on = QCheckBox("Show it")
        self.b_on.toggled.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_on)
        self.b_text = QPlainTextEdit()
        self.b_text.setFixedHeight(54)
        self.b_text.setPlaceholderText("@yourname")
        self.b_text.textChanged.connect(lambda: self._brand_changed(turn_on=True))
        lay.addWidget(self.b_text)

        lay.addWidget(label("Font", "Hint"))
        self.b_font = QFontComboBox()
        self.b_font.setMaximumWidth(200)
        self.b_font.currentFontChanged.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_font)

        row = QHBoxLayout()
        row.addWidget(label("Size", "Hint"))
        row.addStretch()
        self.b_size_label = label("", "Muted")
        row.addWidget(self.b_size_label)
        lay.addLayout(row)
        self.b_size = QSlider(Qt.Horizontal)
        self.b_size.setRange(14, 200)
        self.b_size.valueChanged.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_size)
        self.b_bold = QCheckBox("Bold")
        self.b_bold.toggled.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_bold)

        lay.addWidget(label("Color", "Hint"))
        grid = QGridLayout()
        grid.setSpacing(2)
        self.b_swatches = []
        for i, (key, tip) in enumerate([("primary", "Your main color"),
                                        ("secondary", "Your second color"),
                                        ("tertiary", "Your third color"), ("#ffffff", "White"),
                                        ("#000000", "Black"), ("custom", "Pick any color")]):
            sw = Swatch(tip, size=20)
            sw.key = key
            sw.plus = key == "custom"
            sw.clicked.connect(lambda w=sw: self._brand_color(w))
            grid.addWidget(sw, 0, i)
            self.b_swatches.append(sw)
        lay.addLayout(grid)

        row = QHBoxLayout()
        row.addWidget(label("Opacity", "Hint"))
        row.addStretch()
        self.b_op_label = label("", "Muted")
        row.addWidget(self.b_op_label)
        lay.addLayout(row)
        self.b_opacity = QSlider(Qt.Horizontal)
        self.b_opacity.setRange(10, 100)
        self.b_opacity.valueChanged.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_opacity)

        lay.addWidget(label("Look", "Hint"))
        self.b_look = QComboBox()
        for key, name in B.LOOKS:
            self.b_look.addItem(name, key)
        self.b_look.currentIndexChanged.connect(lambda _: self._brand_changed())
        lay.addWidget(self.b_look)

        # end card only
        self.b_end = QWidget()
        self.b_end.setObjectName("Transparent")
        el = QVBoxLayout(self.b_end)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(6)
        row = QHBoxLayout()
        row.addWidget(label("Show for", "Hint"))
        row.addStretch()
        self.b_len_label = label("", "Muted")
        row.addWidget(self.b_len_label)
        el.addLayout(row)
        self.b_len = QSlider(Qt.Horizontal)
        self.b_len.setRange(2, 12)            # half seconds
        self.b_len.valueChanged.connect(lambda _: self._brand_changed())
        el.addWidget(self.b_len)
        row = QHBoxLayout()
        row.addWidget(label("Darken video", "Hint"))
        row.addStretch()
        self.b_dim_label = label("", "Muted")
        row.addWidget(self.b_dim_label)
        el.addLayout(row)
        self.b_dim = QSlider(Qt.Horizontal)
        self.b_dim.setRange(0, 85)
        self.b_dim.valueChanged.connect(lambda _: self._brand_changed())
        el.addWidget(self.b_dim)
        lay.addWidget(self.b_end)

        lay.addWidget(label("Place it", "Hint"))
        spots = QGridLayout()
        spots.setSpacing(4)
        names = [["Top left", "Top", "Top right"], ["Left", "Middle", "Right"],
                 ["Bottom left", "Bottom", "Bottom right"]]
        for r in range(3):
            for c in range(3):
                b = QPushButton("•")
                b.setObjectName("Spot")
                b.setFixedSize(30, 24)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(names[r][c])
                b.clicked.connect(lambda _=False, c=c, r=r: self._brand_snap(c, r))
                spots.addWidget(b, r, c)
        srow = QHBoxLayout()
        srow.addLayout(spots)
        srow.addStretch()
        lay.addLayout(srow)
        lay.addWidget(label("Or drag it on the phone. Hold Shift to skip snapping.", "Hint",
                            wrap=True))
        lay.addStretch()
        self._brand_loading = False
        return outer

    def _brand_kind(self) -> str:
        return "watermark" if self.brand_bar.currentIndex() == 0 else "endcard"

    def _brand_load(self):
        """Fill the Brand controls from the saved settings for the chosen kind."""
        from . import brand as B
        kind = self._brand_kind()
        cfg = B.settings_for(self.state.settings, kind)
        self._brand_loading = True
        self.b_on.setText("Show my handle" if kind == "watermark" else "Show an end card")
        self.b_on.setChecked(bool(cfg["on"]))
        self.b_text.setPlaceholderText("@yourname" if kind == "watermark" else
                                       "Follow for part 2")
        if self.b_text.toPlainText() != cfg["text"]:
            self.b_text.setPlainText(cfg["text"])
        from PySide6.QtGui import QFont as _F
        self.b_font.setCurrentFont(_F(cfg["font"]))
        self.b_size.setValue(int(cfg["size"]))
        self.b_bold.setChecked(bool(cfg["bold"]))
        self.b_opacity.setValue(int(cfg["opacity"]))
        self.b_look.setCurrentIndex(max(0, self.b_look.findData(cfg["look"])))
        self.b_end.setVisible(kind == "endcard")
        if kind == "endcard":
            self.b_len.setValue(int(round(float(cfg["len"]) * 2)))
            self.b_dim.setValue(int(cfg["dim"]))
        self._brand_loading = False
        self._brand_labels(cfg)
        self._brand_mode()

    def _brand_labels(self, cfg):
        self.b_size_label.setText(f"{int(cfg['size'])} px")
        self.b_op_label.setText(f"{int(cfg['opacity'])}%")
        self.b_len_label.setText(f"{float(cfg.get('len', 2.5)):.1f}s")
        self.b_dim_label.setText(f"{int(cfg.get('dim', 0))}%")
        custom = cfg["color"] if cfg["color"].startswith("#") and \
            cfg["color"] not in ("#ffffff", "#000000") else ""
        for sw in self.b_swatches:
            if sw.key == "custom":
                sw.color = custom
                sw.selected = bool(custom)
            else:
                sw.color = theme.COLORS.get(sw.key, sw.key)
                sw.selected = sw.key == cfg["color"]
            sw.update()

    def _brand_changed(self, turn_on=False):
        if self._brand_loading:
            return
        from . import brand as B
        kind = self._brand_kind()
        cfg = B.settings_for(self.state.settings, kind)
        if turn_on and not self.b_on.isChecked() and self.b_text.toPlainText().strip():
            self._brand_loading = True
            self.b_on.setChecked(True)          # typing text switches it on
            self._brand_loading = False
        cfg.update(on=self.b_on.isChecked(), text=self.b_text.toPlainText(),
                   font=self.b_font.currentFont().family(), size=self.b_size.value(),
                   bold=self.b_bold.isChecked(), opacity=self.b_opacity.value(),
                   look=self.b_look.currentData())
        if kind == "endcard":
            cfg.update(len=self.b_len.value() / 2, dim=self.b_dim.value())
        self.state.settings[kind] = cfg
        self._brand_labels(cfg)
        self._brand_refresh()
        self.changed.emit()

    def _brand_color(self, sw):
        from . import brand as B
        kind = self._brand_kind()
        cfg = B.settings_for(self.state.settings, kind)
        key = sw.key
        if key == "custom":
            c = QColorDialog.getColor(QColor(B.resolve_color(cfg["color"])), self,
                                      "Pick a text color")
            if not c.isValid():
                return
            key = c.name()
        cfg["color"] = key
        self.state.settings[kind] = cfg
        self._brand_labels(cfg)
        self._brand_refresh()

    def _brand_mode(self):
        """On the Brand tab the phone shows what you're placing, and only it moves."""
        on_tab = self.tabs.currentIndex() == 2
        on_caps = self.tabs.currentIndex() == 3 and self._cap_mode() != "post"
        self.canvas.brand_edit = self._brand_kind() if on_tab else "captions" if on_caps \
            else None
        if on_tab:
            tip = "Drag your text on the phone to place it · hold Shift to skip snapping"
        elif on_caps:
            tip = "Drag the captions up or down on the phone · hold Shift to skip snapping"
        elif not self.canvas.show_post:
            tip = "Captions only: the post isn't shown. Style them on the Captions tab."
        else:
            tip = ("Drag the post to move it · drag a corner to resize · "
                   "hold Shift to skip snapping · arrow keys nudge it")
        self.tip.setText(tip)
        self._brand_refresh()

    def _brand_refresh(self):
        """Redraw the watermark / end card on the phone."""
        from . import brand as B
        size = L.output_size(self.fmt, self.res)
        u = L.unit(*size)
        editing = self.canvas.brand_edit
        for kind in B.KINDS:
            cfg = B.settings_for(self.state.settings, kind)
            if not cfg["on"] or not (cfg["text"] or "").strip():
                self.canvas.set_brand(kind, None, False)
                continue
            img = B.text_image(cfg, u)
            frac = (img.width() / size[0], img.height() / size[1])
            x, y = B.clamp_pos(*B.position(self.state.settings, self.fmt, kind), *frac)
            show = kind == "watermark" or editing == "endcard"
            self.canvas.set_brand(kind, {"img": img, "pos": [x, y], "frac": frac,
                                         "dim": cfg.get("dim", 0) / 100 if kind == "endcard"
                                         else 0}, show)
        self._captions_refresh(size)
        if editing and editing not in self.canvas.brand:
            self.canvas.brand_edit = None
        elif self.tabs.currentIndex() == 2:
            self.canvas.brand_edit = self._brand_kind()

    def _brand_snap(self, col, row):
        from . import brand as B
        kind = self._brand_kind()
        it = self.canvas.brand.get(kind)
        if not it:
            return
        x, y = B.snap_spot(self.fmt, col, row, *it["frac"])
        B.set_position(self.state.settings, self.fmt, kind, (x, y))
        self._brand_refresh()

    def _brand_placed(self, kind):
        from . import brand as B
        if kind == "captions":
            it = self.canvas.brand.get("captions")
            if it:
                self._cap_set(y=round(it["pos"][1], 4))
            return
        it = self.canvas.brand.get(kind)
        if it:
            B.set_position(self.state.settings, self.fmt, kind, it["pos"])

    # --- captions -------------------------------------------------------------------
    CAP_COLORS = [("primary", "Your main color"), ("secondary", "Your second color"),
                  ("tertiary", "Your third color"), ("#ffd400", "Yellow"), ("#ffffff", "White"),
                  ("custom", "Pick any color")]

    def _captions_tab(self):
        from .. import captions as C
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.NoFrame)
        outer.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.viewport().setAutoFillBackground(False)
        w = QWidget()
        w.setObjectName("Transparent")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 10, 6, 4)
        lay.setSpacing(6)
        outer.setWidget(w)
        self._cap_loading = True

        lay.addWidget(label("Show the post", "Hint"))
        self.cap_mode = QComboBox()
        for key, (name, tip) in C.MODES.items():
            self.cap_mode.addItem(name, key)
            self.cap_mode.setItemData(self.cap_mode.count() - 1, tip, Qt.ToolTipRole)
        self.cap_mode.setToolTip("Captions show the story as big words in time with the "
                                 "voice. Great for Reddit stories.")
        self.cap_mode.currentIndexChanged.connect(self._cap_mode_changed)
        lay.addWidget(self.cap_mode)
        self.cap_mode_tip = label("", "Muted", wrap=True)
        lay.addWidget(self.cap_mode_tip)

        self.cap_controls = QWidget()
        self.cap_controls.setObjectName("Transparent")
        cl = QVBoxLayout(self.cap_controls)
        cl.setContentsMargins(0, 4, 0, 0)
        cl.setSpacing(6)
        cl.addWidget(label("Words at a time", "Hint"))
        self.cap_words = QComboBox()
        for n, name in ((1, "1 word"), (2, "Up to 2 words"), (3, "Up to 3 words"),
                        (5, "Up to 5 words")):
            self.cap_words.addItem(name, n)
        self.cap_words.currentIndexChanged.connect(
            lambda _: self._cap_set(words=self.cap_words.currentData()))
        cl.addWidget(self.cap_words)

        cl.addWidget(label("Font", "Hint"))
        self.cap_font = QFontComboBox()
        self.cap_font.setToolTip("Any font on your PC. Downloaded a new one? Add its file "
                                 "below, or install it in Windows and restart the app.")
        self.cap_font.setMaxVisibleItems(16)
        self.cap_font.currentFontChanged.connect(
            lambda f: self._cap_set(font=f.family()))
        cl.addWidget(self.cap_font)
        frow = QHBoxLayout()
        self.cap_bold = QCheckBox("Bold")
        self.cap_bold.setToolTip("Use the font's boldest version, if it has one")
        self.cap_bold.toggled.connect(lambda on: self._cap_set(bold=on))
        frow.addWidget(self.cap_bold)
        frow.addStretch()
        frow.addWidget(button("＋ Add font file", "Link", self._cap_add_font,
                              tip="Use a font you downloaded (.ttf or .otf), e.g. from "
                                  "Google Fonts or DaFont"))
        cl.addLayout(frow)

        row = QHBoxLayout()
        row.addWidget(label("Size", "Hint"))
        row.addStretch()
        self.cap_size_label = label("", "Muted")
        row.addWidget(self.cap_size_label)
        cl.addLayout(row)
        self.cap_size = QSlider(Qt.Horizontal)
        self.cap_size.setRange(50, 170)
        self.cap_size.valueChanged.connect(lambda v: self._cap_set(size=v))
        cl.addWidget(self.cap_size)
        self.cap_upper = QCheckBox("ALL CAPS")
        self.cap_upper.toggled.connect(lambda on: self._cap_set(upper=on))
        cl.addWidget(self.cap_upper)

        cl.addWidget(label("Highlight", "Hint"))
        self.cap_hl = QComboBox()
        for key, name in C.HIGHLIGHTS.items():
            self.cap_hl.addItem(name, key)
        self.cap_hl.currentIndexChanged.connect(
            lambda _: self._cap_set(highlight=self.cap_hl.currentData()))
        cl.addWidget(self.cap_hl)
        grid = QGridLayout()
        grid.setSpacing(2)
        self.cap_swatches = []
        for i, (key, tip) in enumerate(self.CAP_COLORS):
            sw = Swatch(tip, size=20)
            sw.key = key
            sw.plus = key == "custom"
            sw.clicked.connect(lambda w=sw: self._cap_color(w))
            grid.addWidget(sw, 0, i)
            self.cap_swatches.append(sw)
        cl.addLayout(grid)

        cl.addWidget(label("Place them", "Hint"))
        prow = QHBoxLayout()
        prow.setSpacing(4)
        for text, y, tip in (("Top", 0.3, "Upper part of the video"),
                             ("Middle", 0.5, "Right in the middle"),
                             ("Low", 0.66, "Lower down, still clear of the app's buttons")):
            b = QPushButton(text)
            b.setObjectName("Spot")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, y=y: self._cap_set(y=y))
            prow.addWidget(b)
        cl.addLayout(prow)
        cl.addWidget(label("Or drag them on the phone.", "Hint", wrap=True))
        lay.addWidget(self.cap_controls)
        lay.addStretch()
        for box in (self.cap_mode, self.cap_words, self.cap_font, self.cap_hl):
            box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(8)
        self._cap_loading = False
        self._captions_load()
        return outer

    def _cap_mode(self) -> str:
        m = self.state.settings["post_display"]
        return m if m in ("post", "intro", "captions") else "post"

    def _cap_style(self) -> dict:
        from ..captions import DEFAULT_STYLE
        return {**DEFAULT_STYLE, "color": "primary", **(self.state.settings["captions"] or {})}

    def _captions_load(self):
        """Fill the Captions controls from the settings."""
        from .. import captions as C
        if not hasattr(self, "cap_mode"):
            return
        st = self._cap_style()
        mode = self._cap_mode()
        self._cap_loading = True
        self.cap_mode.setCurrentIndex(max(0, self.cap_mode.findData(mode)))
        self.cap_words.setCurrentIndex(max(0, self.cap_words.findData(int(st["words"]))))
        from PySide6.QtGui import QFont as _QF
        self.cap_font.setCurrentFont(_QF(self._cap_family(st["font"])))
        self.cap_bold.setChecked(bool(st.get("bold", True)))
        self.cap_size.setValue(int(st["size"]))
        self.cap_upper.setChecked(bool(st["upper"]))
        self.cap_hl.setCurrentIndex(max(0, self.cap_hl.findData(st["highlight"])))
        self._cap_loading = False
        self.cap_mode_tip.setText(C.MODES[mode][1])
        self.cap_controls.setEnabled(mode != "post")
        self.cap_size_label.setText(f"{int(st['size'])} px")
        known = [k for k, _ in self.CAP_COLORS if k != "custom"]
        for sw in self.cap_swatches:
            if sw.key == "custom":
                sw.color = st["color"] if st["color"] not in known else ""
                sw.selected = st["color"] not in known
            else:
                sw.color = theme.COLORS.get(sw.key, sw.key)
                sw.selected = sw.key == st["color"]
            sw.update()
        self.canvas.show_post = mode != "captions" and not self.state.settings["clip_only"]
        self._brand_mode()

    @staticmethod
    def _cap_family(font: str) -> str:
        """The font name to show in the picker (the built-in looks have file names)."""
        from .. import captions as C
        if font not in C.FONTS:
            return font
        from PySide6.QtGui import QFontDatabase
        have = set(QFontDatabase.families())
        names = {"heavy": ["Segoe UI Black", "Arial Black", "Impact", "DejaVu Sans"],
                 "impact": ["Impact", "Arial Black", "DejaVu Sans"],
                 "bold": ["Segoe UI", "Arial", "DejaVu Sans"]}[font]
        return next((n for n in names if n in have), names[-1])

    def _cap_add_font(self):
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        from .. import fonts
        path, _ = QFileDialog.getOpenFileName(self, "Add a font", str(Path.home() / "Downloads"),
                                              "Fonts (*.ttf *.otf *.ttc)")
        if not path:
            return
        try:
            name, dest = fonts.add_font_file(path)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "Couldn't add that font", str(e))
            return
        fid = QFontDatabase.addApplicationFont(dest)
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        family = fams[0] if fams else name
        self.cap_font.setCurrentFont(QFont(family))
        self._cap_set(font=family)

    def _cap_mode_changed(self, _=None):
        if self._cap_loading:
            return
        self.state.settings["post_display"] = self.cap_mode.currentData()
        self._captions_load()
        self.canvas.update()
        self.changed.emit()

    def _cap_set(self, **changes):
        if self._cap_loading:
            return
        st = dict(self.state.settings["captions"] or {})
        st.update(changes)
        self.state.settings["captions"] = st
        self._captions_load()
        self.changed.emit()

    def _cap_color(self, sw):
        key = sw.key
        if key == "custom":
            from .brand import resolve_color
            c = QColorDialog.getColor(QColor(resolve_color(self._cap_style()["color"])), self,
                                      "Pick a highlight color")
            if not c.isValid():
                return
            key = c.name()
        self._cap_set(color=key)

    def _captions_refresh(self, size):
        """The sample caption on the phone (captions only, or while on the Captions tab)."""
        from .. import captions as C
        mode = self._cap_mode()
        if mode == "post" or not hasattr(self, "cap_mode") or self.state.settings["clip_only"]:
            self.canvas.set_brand("captions", None, False)
            return
        st = self._cap_style()
        st["color"] = theme.COLORS.get(st["color"], st["color"])
        key = (tuple(sorted(st.items())), size)
        if getattr(self, "_cap_key", None) != key:
            im, _ = C.sample_image(st, *size)
            box = im.getbbox() or (0, 0, im.width, im.height)
            pad = int(10 * L.unit(*size))
            im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad),
                          min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
            q = QImage(im.tobytes("raw", "RGBA"), im.width, im.height,
                       QImage.Format_RGBA8888).copy()
            self._cap_img = (q, (im.width / size[0], im.height / size[1]))
            self._cap_key = key
        img, frac = self._cap_img
        from .brand import clamp_pos
        x, y = clamp_pos(0.5, float(st["y"]), *frac)
        show = mode == "captions" or self.tabs.currentIndex() == 3
        self.canvas.set_brand("captions", {"img": img, "pos": [x, y], "frac": frac, "dim": 0},
                              show)

    def caption_summary(self) -> str:
        mode = self._cap_mode()
        if mode == "post":
            return ""
        st = self._cap_style()
        n = int(st["words"])
        return (("post, then captions" if mode == "intro" else "captions only") +
                f" ({n} word{'s' if n > 1 else ''} at a time)")

    # --- style ------------------------------------------------------------------
    def _resolved_color(self) -> str:
        c = self.border_color
        return theme.COLORS[c] if c in theme.COLORS else c

    def _pick_swatch(self, sw):
        kind, key = sw.key
        if kind == "solid" and key == "custom":
            start = QColor(self.border_color if self.border_color.startswith("#") else
                           self._resolved_color())
            c = QColorDialog.getColor(start, self, "Pick a border color")
            if not c.isValid():
                return
            key = c.name()
        if kind == "solid":
            self.border_style, self.border_color = "solid", key
        else:
            self.border_style = kind
        self._style_changed(turn_on=self.border_on)

    def _tick_swatches(self):
        on = anim.ENABLED and self.isVisible() and self.tabs.currentIndex() == 1
        if on and not self._swatch_ticker.isActive():
            self._swatch_ticker.start()
        elif not on:
            self._swatch_ticker.stop()

    def _style_changed(self, turn_on=None, save=True):
        """Any style control moved: update the phone, labels and saved settings."""
        if turn_on is not None and not turn_on.isChecked():
            turn_on.blockSignals(True)
            turn_on.setChecked(True)           # touching a control switches it on
            turn_on.blockSignals(False)
        st = self.state.settings
        shadow = self.shadow.value() / 100
        self.shadow_label.setText(f"{self.shadow.value()}%" if self.shadow_on.isChecked() else "Off")
        self.border_label.setText(f"{self.border_w.value()} px" if self.border_on.isChecked()
                                  else "Off")
        custom = self.border_color if self.border_color.startswith("#") and \
            self.border_color not in ("#ffffff", "#000000") else ""
        for sw in self.swatches:
            kind, key = sw.key
            if kind == "solid":
                if key == "custom":
                    sw.color = custom
                else:
                    sw.color = theme.COLORS.get(key, key)
                sw.selected = self.border_style == "solid" and (
                    key == self.border_color or (key == "custom" and bool(custom)))
            else:
                sw.selected = self.border_style == kind
            sw.update()
        info = L.BORDER_STYLES[self.border_style]
        if self.border_style == "solid":
            names = {"primary": "Main color", "secondary": "Second color",
                     "tertiary": "Third color", "#ffffff": "White", "#000000": "Black"}
            self.style_name.setText("Border: " + names.get(self.border_color,
                                                           self._resolved_color().upper()))
        else:
            self.style_name.setText(f"Border: {info['name']} (animated)")
        self.canvas.set_style(max(shadow, 0.02) if self.shadow_on.isChecked() else 0.0,
                              self.border_w.value() if self.border_on.isChecked() else 0.0,
                              self.border_style, self._resolved_color())
        if save:
            st.values.update({"post_shadow": self.shadow_on.isChecked(),
                              "post_shadow_strength": self.shadow.value(),
                              "post_border": self.border_on.isChecked(),
                              "post_border_width": self.border_w.value(),
                              "post_border_style": self.border_style,
                              "post_border_color": self.border_color})
            st.save()
            self.changed.emit()

    def reset_style(self):
        for box in (self.shadow_on, self.border_on):
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
        self._style_changed()
        self._animate_round(0)

    def _animate_round(self, target):
        start = self.round.value()
        if start == target:
            return
        if not anim.ENABLED:
            self.round.setValue(target)
            self._save_round()
            return
        a = QVariantAnimation(self)
        a.setStartValue(float(start))
        a.setEndValue(float(target))
        a.setDuration(320)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v: self.round.setValue(int(round(v))))
        a.finished.connect(self._save_round)
        self._round_anim = a
        a.start(QVariantAnimation.DeleteWhenStopped)

    def _round_slid(self, v):
        self.canvas.set_round(v / 100)
        self._sync_controls()
        if not self.round.isSliderDown() and getattr(self, "_round_anim", None) is None:
            self._save_round()

    def _save_round(self):
        self._round_anim = None
        self.state.settings["post_round"] = self.round.value()
        self.changed.emit()

    def _size_slid(self, v):
        self.canvas.settle()
        self.canvas.set_box({**self.canvas.box, "w": v / 100})
        self._sync_controls()
        if not self.size.isSliderDown():      # clicked or keyboard, not dragging
            self._save()

    def _overlay_toggled(self, on):
        self.state.settings["show_app_overlay"] = on
        self.canvas.set_overlay(on)

    # --- for the renderer ----------------------------------------------------------
    def job_settings(self) -> dict:
        return {"fmt": self.fmt, "resolution": self.res, "post_box": self.saved_box(),
                "post_round": self.round.value() / 100,
                "shadow": self.canvas.shadow, "border": self.canvas.border,
                "border_style": self.border_style, "border_color": self._resolved_color(),
                "border_colors": theme_colors(),
                "fps": int(self.state.settings["fps"] or 30),
                "mirror": self.state.settings["mirror"] or "off",
                "fit": self.state.settings["fit"] or "fill"}

    def summary(self) -> str:
        return L.describe(self.fmt, self.res)

    def style_summary(self) -> str:
        bits = []
        v = self.round.value() / 100
        if v > 0.004:
            name = L.corner_label(v, self.canvas.post_aspect)
            bits.append(name.lower() if v >= 0.995 else f"{name.lower()} rounded corners")
        if self.canvas.shadow:
            bits.append("shadow")
        if self.canvas.border:
            bits.append("border" if self.border_style == "solid" else
                        L.BORDER_STYLES[self.border_style]["name"].lower() + " border")
        return " · ".join(bits) if bits else "square corners, no border"

    def brand_summary(self) -> str:
        from .brand import settings_for
        st = self.state.settings
        bits = []
        wm = settings_for(st, "watermark")
        if wm["on"] and (wm["text"] or "").strip():
            bits.append(f"watermark “{wm['text'].strip()}”")
        ec = settings_for(st, "endcard")
        if ec["on"] and (ec["text"] or "").strip():
            bits.append(f"end card “{ec['text'].strip()}”")
        return " · ".join(bits) if bits else "none"
