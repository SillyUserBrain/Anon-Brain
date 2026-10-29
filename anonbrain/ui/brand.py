"""Your handle on the video (watermark) and the end card ("Follow for part 2").

Settings (settings.json):
  watermark / endcard: {"on", "text", "font", "size", "bold", "color", "opacity",
                        "look": outline / box / plain, (end card) "len", "dim"}
  brand_pos: {format: {"watermark": [x, y], "endcard": [x, y]}}   centre, 0..1

The text is drawn here with Qt (any font on your PC) into a PNG at the
video's real size. The phone preview shows that same picture, scaled, so
what you place is exactly what you get.
"""

import hashlib
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
)

from .. import layout as L
from ..settings import cache_dir

KINDS = ("watermark", "endcard")
DEFAULTS = {
    "watermark": {"on": False, "text": "@yourname", "font": "Arial", "size": 40, "bold": True,
                  "color": "#ffffff", "opacity": 75, "look": "outline"},
    "endcard": {"on": False, "text": "Follow for part 2", "font": "Arial", "size": 84,
                "bold": True, "color": "#ffffff", "opacity": 100, "look": "box",
                "len": 2.5, "dim": 35},
}
LOOKS = [("outline", "Outline"), ("box", "Dark box"), ("plain", "Plain")]


def settings_for(settings, kind: str) -> dict:
    return {**DEFAULTS[kind], **(settings[kind] or {})}


def default_pos(fmt: str, kind: str) -> list[float]:
    m = L.margins(fmt)
    if kind == "watermark":
        return [0.5, 1 - m["bottom"] - 0.03] if fmt == "9:16" else [0.86, 0.92]
    return [0.5, 0.5]


def position(settings, fmt: str, kind: str) -> list[float]:
    pos = ((settings["brand_pos"] or {}).get(fmt) or {}).get(kind)
    return list(pos) if pos else default_pos(fmt, kind)


def set_position(settings, fmt: str, kind: str, xy):
    allpos = dict(settings["brand_pos"] or {})
    fpos = dict(allpos.get(fmt) or {})
    fpos[kind] = [round(xy[0], 4), round(xy[1], 4)]
    allpos[fmt] = fpos
    settings["brand_pos"] = allpos


def resolve_color(c: str) -> str:
    from . import theme
    return theme.COLORS.get(c, c)


def text_image(cfg: dict, px_per_unit: float) -> QImage:
    """The text as a transparent picture. px_per_unit: pixels per '1080p pixel'."""
    px = max(6, int(cfg["size"] * px_per_unit))
    f = QFont(cfg["font"])
    f.setPixelSize(px)
    f.setBold(bool(cfg["bold"]))
    fm = QFontMetricsF(f)
    lines = [l for l in (cfg["text"] or " ").replace("\\n", "\n").split("\n")] or [" "]
    widths = [fm.horizontalAdvance(l) for l in lines]
    lh = fm.lineSpacing()
    look = cfg.get("look", "outline")
    stroke = max(1.5, px * 0.09)
    pad = px * 0.42 if look == "box" else stroke * 1.5 + 2
    w = int(max(widths) + 2 * pad + 2)
    h = int(lh * len(lines) + 2 * pad - (fm.leading() if len(lines) else 0) + 2)
    img = QImage(max(w, 2), max(h, 2), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setOpacity(max(0.05, cfg["opacity"] / 100))
    if look == "box":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))
        r = min(h / 2, px * 0.5)
        p.drawRoundedRect(QRectF(0, 0, w, h), r, r)
    path = QPainterPath()
    for i, line in enumerate(lines):
        x = (w - widths[i]) / 2
        path.addText(QPointF(x, pad + fm.ascent() + i * lh), f, line)
    if look == "outline":
        p.strokePath(path, QPen(QColor(0, 0, 0, 210), stroke * 2, Qt.SolidLine, Qt.RoundCap,
                                Qt.RoundJoin))
    elif look == "plain":
        shadow = QPainterPath(path)
        shadow.translate(0, max(1.0, px * 0.05))
        p.fillPath(shadow, QColor(0, 0, 0, 120))
    p.fillPath(path, QColor(resolve_color(cfg["color"])))
    p.end()
    return img


def render_png(cfg: dict, size: tuple[int, int]) -> Path:
    """The overlay picture for a video of this size (cached)."""
    unit = L.unit(*size)
    key = hashlib.md5(repr((sorted(cfg.items()), resolve_color(cfg["color"]),
                            round(unit, 4))).encode()).hexdigest()[:14]
    out = cache_dir() / f"brand_{key}.png"
    if not out.exists():
        text_image(cfg, unit).save(str(out))
    return out


def job_brand(settings, fmt: str, size: tuple[int, int]) -> dict | None:
    """What the renderer needs: {"watermark": {...}, "endcard": {...}} or None."""
    out = {}
    for kind in KINDS:
        cfg = settings_for(settings, kind)
        if not cfg["on"] or not (cfg["text"] or "").strip():
            continue
        x, y = position(settings, fmt, kind)
        item = {"png": str(render_png(cfg, size)), "x": x, "y": y}
        if kind == "endcard":
            item["len"] = float(cfg["len"])
            item["dim"] = cfg["dim"] / 100
        out[kind] = item
    return out or None


def clamp_pos(x, y, w_frac, h_frac):
    """Keep the overlay fully on screen."""
    x = min(max(x, w_frac / 2), 1 - w_frac / 2) if w_frac < 1 else 0.5
    y = min(max(y, h_frac / 2), 1 - h_frac / 2) if h_frac < 1 else 0.5
    return x, y


def snap_spot(fmt: str, col: int, row: int, w_frac: float, h_frac: float):
    """One of 9 spots (col, row in 0..2), inside the safe area."""
    m = L.margins(fmt)
    xs = [m["side"] + w_frac / 2, 0.5, 1 - m["side"] - w_frac / 2]
    ys = [m["top"] + h_frac / 2, 0.5, 1 - m["bottom"] - h_frac / 2]
    return clamp_pos(xs[col], ys[row], w_frac, h_frac)
