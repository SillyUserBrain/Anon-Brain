"""The hook: big attention-grabbing text for the first seconds of a video."""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "seguibl.ttf",      # Segoe UI Black (Windows)
    "ariblk.ttf",       # Arial Black (Windows)
    "impact.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
]
FONT_DIRS = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts")]


def _font(size: int):
    for name in FONT_CANDIDATES:
        for d in FONT_DIRS:
            p = d / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size=size)


def _wrap(draw, text, font, max_w):
    lines = []
    for para in text.splitlines() or [""]:
        line = ""
        for word in para.split():
            test = (line + " " + word).strip()
            if draw.textlength(test, font=font) <= max_w or not line:
                line = test
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return [l for l in lines if l] or [""]


def render_hook(text: str, out: Path, accent: str = "#8fc43f", width: int = 1000) -> Path:
    """White text with a heavy outline on a dark rounded card with a coloured edge."""
    text = text.strip()
    size = 96 if len(text) < 30 else 84 if len(text) < 50 else 70 if len(text) < 90 else 58
    font = _font(size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    pad_x, pad_y, gap = 46, 34, int(size * 0.18)
    lines = _wrap(probe, text, font, width - 2 * pad_x)
    line_h = [probe.textbbox((0, 0), l, font=font, stroke_width=6) for l in lines]
    heights = [b[3] - b[1] for b in line_h]
    text_h = sum(heights) + gap * (len(lines) - 1)
    text_w = max(b[2] - b[0] for b in line_h)
    w = min(width, text_w + 2 * pad_x)
    h = text_h + 2 * pad_y

    img = Image.new("RGBA", (w + 24, h + 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # soft shadow, card, accent edge
    d.rounded_rectangle((16, 18, w + 16, h + 18), radius=34, fill=(0, 0, 0, 90))
    d.rounded_rectangle((8, 8, w + 8, h + 8), radius=34, fill=(10, 12, 16, 215),
                        outline=accent, width=5)
    y = 8 + pad_y
    for line, bbox, lh in zip(lines, line_h, heights):
        lw = bbox[2] - bbox[0]
        x = 8 + (w - lw) / 2 - bbox[0]
        d.text((x, y - bbox[1]), line, font=font, fill="white",
               stroke_width=6, stroke_fill=(0, 0, 0))
        y += lh + gap
    img.save(out)
    return out
