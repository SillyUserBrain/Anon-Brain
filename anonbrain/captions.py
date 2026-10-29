"""Captions: the story as big words on screen, a few at a time, in time with the voice.

Used instead of (or after) the post image, the way Reddit story videos do it.
Each group of words pops in, and the word being read is highlighted.
"""

import re
from pathlib import Path

from PIL import Image, ImageDraw

from .hook import FONT_DIRS, ImageFont

FPS = 30
POP = (0.82, 0.96, 1.05, 1.0)    # size of a new group over its first frames
GAP_SPLIT = 0.5                  # a pause this long starts a new group
HOLD = 0.7                       # groups stay up through pauses shorter than this
EARLY = 0.04                     # groups appear this much before their first word

FONTS = {
    "heavy": ("Heavy", ["seguibl.ttf", "ariblk.ttf", "impact.ttf", "DejaVuSans-Bold.ttf"]),
    "impact": ("Impact", ["impact.ttf", "ariblk.ttf", "DejaVuSans-Bold.ttf"]),
    "bold": ("Bold", ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]),
}
HIGHLIGHTS = {
    "color": "Color the spoken word",
    "box": "Box behind the spoken word",
    "none": "No highlight",
}
MODES = {
    "post": ("Post image", "The post stays on screen the whole video"),
    "intro": ("Post first, then captions",
              "The post shows while its first line (the title) is read, then it goes "
              "away and captions take over"),
    "captions": ("Captions only", "No post image: just big captions over the gameplay"),
}

DEFAULT_STYLE = {"words": 3, "font": "heavy", "bold": True, "size": 96,
                 "highlight": "color", "color": "#8fc43f", "upper": True, "y": 0.5}


def _font(kind: str, size: int, bold: bool = True):
    """kind = one of FONTS, or the name of any font on this PC."""
    if kind not in FONTS:
        from .fonts import find
        path = find(kind, bold)
        if path:
            try:
                f = ImageFont.truetype(path, size)
            except OSError:
                f = None
            if f is not None:
                _set_weight(f, bold)
                return f
        kind = "heavy"          # that font is gone: fall back to the default
    for name in FONTS[kind][1]:
        for d in FONT_DIRS:
            p = d / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def _set_weight(f, bold: bool):
    """Variable fonts (one file, every weight): pick the weight by name."""
    try:
        names = [n.decode() if isinstance(n, bytes) else n for n in f.get_variation_names()]
    except Exception:
        return
    order = ("Black", "ExtraBold", "Extra Bold", "Bold") if bold else ("Regular",)
    for want in order:
        if want in names:
            try:
                f.set_variation_by_name(want)
            except Exception:
                pass
            return


def _clean(text: str, upper: bool) -> str:
    t = text.strip()
    t = re.sub(r"^[>\"'“‘(\[]+|[\"'”’)\]]+$", "", t) or t   # greentext arrows, quotes
    return t.upper() if upper else t


def groups(words, max_words: int) -> list[list]:
    """Words -> the groups shown together. A group ends at max_words, at the end
    of a sentence, or at a pause."""
    out, cur = [], []
    for w in words:
        if not _clean(w.text, False):
            continue
        if cur and (len(cur) >= max_words or w.start - cur[-1].end > GAP_SPLIT):
            out.append(cur)
            cur = []
        cur.append(w)
        if max_words > 1 and re.search(r"[.!?;:,]['\"”’)]*$", w.text.strip()):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _layout(draw, words, font, max_w):
    """Words -> lines of (word, width); the space width."""
    space = draw.textlength(" ", font=font)
    lines, line, lw = [], [], 0.0
    for w in words:
        ww = draw.textlength(w, font=font)
        if line and lw + space + ww > max_w:
            lines.append(line)
            line, lw = [], 0.0
        lw += (space if line else 0) + ww
        line.append((w, ww))
    if line:
        lines.append(line)
    return lines, space


class Painter:
    """Draws one caption image (W x box_h, transparent)."""

    def __init__(self, style: dict, W: int, H: int):
        self.s = {**DEFAULT_STYLE, **(style or {})}
        self.W = W
        self.u = min(W, H) / 1080
        self.base = max(12, int(float(self.s["size"]) * self.u))
        self.max_w = W * 0.86
        self.box_h = int(self.base * 1.22 * 2 * max(POP) + self.base * 0.6)
        self.probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
        self._fonts = {}

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = _font(self.s["font"], size, bool(self.s.get("bold", True)))
        return self._fonts[size]

    def fit(self, words, scale=1.0):
        """Font + lines for these words, shrunk so they fit on two lines."""
        size = max(8, int(self.base * scale))
        while True:
            f = self.font(size)
            lines, space = _layout(self.probe, words, f, self.max_w)
            if len(lines) <= 2 or size <= self.base * scale * 0.55:
                return f, size, lines, space
            size = int(size * 0.9)

    def image(self, words: list[str], active: int, scale: float = 1.0) -> Image.Image:
        s = self.s
        f, size, lines, space = self.fit(words, scale)
        img = Image.new("RGBA", (self.W, self.box_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        stroke = max(2, int(size * 0.11))
        asc, desc = f.getmetrics()
        line_h = int((asc + desc) * 1.02)
        top = (self.box_h - line_h * len(lines)) / 2
        hi = s["color"] if s["highlight"] != "none" else "#ffffff"
        k = 0
        for li, line in enumerate(lines):
            width = sum(ww for _, ww in line) + space * (len(line) - 1)
            x = (self.W - width) / 2
            y = top + li * line_h
            for word, ww in line:
                on = k == active and s["highlight"] != "none"
                if on and s["highlight"] == "box":
                    pad = size * 0.14
                    d.rounded_rectangle((x - pad, y + size * 0.02, x + ww + pad,
                                         y + line_h - size * 0.02), radius=size * 0.18,
                                        fill=hi)
                    fill = "#ffffff"
                else:
                    fill = hi if on else "#ffffff"
                # a soft drop under the outline so it reads over bright gameplay
                off = max(2, int(size * 0.06))
                d.text((x + off, y + off), word, font=f, fill=(0, 0, 0, 110),
                       stroke_width=stroke, stroke_fill=(0, 0, 0, 110))
                d.text((x, y), word, font=f, fill=fill, stroke_width=stroke,
                       stroke_fill=(0, 0, 0))
                x += ww + space
                k += 1
        return img


def build_frames(spec: dict, W: int, H: int, folder: Path) -> tuple[list, int]:
    """Caption images for the video: ([(png, start_seconds), ...], image height).

    spec = {"words": [Word...] (video time), "style": {...}}"""
    folder.mkdir(parents=True, exist_ok=True)
    style = {**DEFAULT_STYLE, **(spec.get("style") or {})}
    words = spec.get("words") or []
    pnt = Painter(style, W, H)
    gs = groups(words, max(1, int(style["words"])))
    if not gs:
        return [], pnt.box_h
    events = []        # (time, group, active word, scale)
    for gi, g in enumerate(gs):
        t0 = max(0.0, g[0].start - EARLY)
        for k, sc in enumerate(POP):
            events.append((t0 + k / FPS, gi, 0, sc))
        for wi, w in enumerate(g[1:], 1):
            events.append((max(w.start, t0 + len(POP) / FPS), gi, wi, 1.0))
        nxt = gs[gi + 1][0].start - EARLY if gi + 1 < len(gs) else None
        end = g[-1].end + 0.25
        if nxt is None or nxt - g[-1].end > HOLD:
            events.append((end, -1, 0, 1.0))           # blank until the next group
    events.sort(key=lambda e: e[0])

    blank = folder / "cap_blank.png"
    Image.new("RGBA", (W, pnt.box_h), (0, 0, 0, 0)).save(blank)
    frames, cache = [(blank, 0.0)], {}
    for t, gi, wi, sc in events:
        if gi < 0:
            path = blank
        else:
            key = (gi, wi, sc)
            if key not in cache:
                text = [_clean(w.text, style["upper"]) for w in gs[gi]]
                path = folder / f"cap_{len(cache):04d}.png"
                pnt.image(text, wi, sc).save(path, compress_level=1)
                cache[key] = path
            path = cache[key]
        t = round(t, 4)
        if t <= frames[-1][1] + 0.002:     # two changes at once: the later one wins
            frames[-1] = (path, frames[-1][1])
        else:
            frames.append((path, t))
    return frames, pnt.box_h


def sample_image(style: dict, W: int, H: int, text="THIS IS HOW YOUR CAPTIONS LOOK"):
    """A still for the Layout screen's phone."""
    style = {**DEFAULT_STYLE, **(style or {})}
    words = text.split()[: max(1, int(style["words"]))] if int(style["words"]) < 4 else \
        text.split()[:3]
    if not style["upper"]:
        words = [w.capitalize() if i == 0 else w.lower() for i, w in enumerate(words)]
    pnt = Painter(style, W, H)
    return pnt.image(words, min(1, len(words) - 1)), pnt.box_h
